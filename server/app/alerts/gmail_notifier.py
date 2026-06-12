"""GmailApiNotifier — Gmail-API (OAuth2) NotificationChannel adapter.

Reference: docs/design/alerts/design.md §2.5 (NotificationChannel Protocol),
           plan-docs/decisions/child-only-and-email-alerts.decision.md (D-CO-2).

Selected with ``ALERTS_CHANNEL=email`` in ``main.py`` ``lifespan()``.

Credential model
----------------
Two JSON files (paths env-configurable; defaults shown):

  GMAIL_CLIENT_JSON  (default: gmail_credentials/gmailcredentials.json)
      OAuth2 client secrets — type "installed" (Desktop app).  Contains
      ``installed.{client_id, client_secret, token_uri, ...}``.

  GMAIL_TOKEN_JSON   (default: gmail_credentials/token.json)
      A STORED user token that ALREADY has a ``refresh_token``.  The token was
      minted by ``scripts/gmail_oauth_setup.py`` (one-time browser consent).
      The access_token is short-lived; google-auth refreshes it automatically
      when ``not creds.valid``.  The adapter persists the refreshed token back
      to the JSON file so the next call doesn't need a new round-trip.

  ALERT_FROM         (optional)
      The "From" address shown to recipients.  When empty, the adapter resolves
      it once via ``service.users().getProfile(userId="me")`` and caches it for
      the lifetime of the adapter instance.

No new browser consent is needed at runtime — the stored refresh_token is
sufficient.  If the token file is missing or the refresh fails, ``send_alert``
logs a warning and returns ``AlertResult(sent=False, error=…)`` — the pipeline
is never disrupted.

Email format
------------
  Subject : Shomer.AI · התראה: <label>
  Body    : Hebrew text with child label/severity, quote snippet, CA explanation,
            timestamp (ISO 8601 UTC), and a hint to check the dashboard.
  MIME    : text/plain, UTF-8; base64url-encoded per the Gmail API requirement.

Delivery path mirrors LogNotifier / FcmNotifier
----------------------------------------------
1. ``alert_id = sha256(child_id:message_id:label)[:16]`` — idempotency key.
2. Rate-limit check (shared ``AlertRateLimiter`` injected at construction).
3. Resolve / refresh credentials.
4. Build RFC 822 MIME message, base64url-encode.
5. Call ``service.users().messages().send(userId="me", body={"raw": …})``.
6. On failure: log warning, return ``AlertResult(sent=False, error=…)`` —
   NEVER raise into the pipeline.
7. Invoke ``audit_recorder`` callback (best-effort).

Testability
-----------
``google-auth`` and ``google-api-python-client`` are imported lazily so the
module is importable (and the server starts) without these packages installed.
Tests inject a ``send_fn`` that replaces the real Gmail service call so no
network is touched in CI.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import Awaitable, Callable

import structlog

from ..schemas import AlertRequest, AlertResult
from .email_message import build_raw_message_base64url
from .log_notifier import compute_alert_id
from .metrics import (
    ALERT_QUEUE_DEPTH,
    ALERT_RATE_LIMITED,
    ALERT_SEND_FAILURES,
    ALERT_SEND_LATENCY,
    ALERT_SEND_SUCCESS,
)
from .protocol import AlertRateLimiter
from .retry_queue import LocalRetryQueue
from .settings import AlertSettings

log = structlog.get_logger("shomer.alerts.gmail")

# Type alias for the injected send function (makes testing trivial).
# Signature: (to_address, raw_base64url) → gmail_message_id
SendFn = Callable[[str, str], str]

# Scopes required to send email (gmail.modify is a superset of gmail.send).
_SCOPES = ["https://www.googleapis.com/auth/gmail.send"]


def _build_raw_message(to_address: str, from_address: str, request: AlertRequest) -> str:
    """Backward-compat wrapper — delegates to the shared email_message helper.

    Tests that import ``_build_raw_message`` directly continue to work unchanged.
    New code should call ``build_raw_message_base64url`` from ``email_message``
    directly.
    """
    return build_raw_message_base64url(to_address, from_address, request)


class GmailApiNotifier:
    """Gmail API push-email channel (``NotificationChannel`` adapter).

    Parameters
    ----------
    settings:
        ``AlertSettings`` — reads ``max_retry_attempts``, ``retry_base_seconds``,
        rate-limit params.  Gmail credential paths are read from ``os.environ``
        directly (``GMAIL_CLIENT_JSON``, ``GMAIL_TOKEN_JSON``, ``ALERT_FROM``).
    rate_limiter:
        ``AlertRateLimiter`` adapter (e.g. ``InMemoryAlertRateLimiter``).
    retry_queue:
        Optional ``LocalRetryQueue`` for degraded-mode buffering.
    audit_recorder:
        Optional async callback ``(AlertRequest, AlertResult) → None``.
    send_fn:
        Injectable for tests — replaces the real Gmail API call.
        Signature: ``(to_address: str, raw_b64: str) -> gmail_message_id: str``.
        When ``None``, the real Gmail service is used.
    """

    def __init__(
        self,
        settings: AlertSettings,
        rate_limiter: AlertRateLimiter,
        retry_queue: LocalRetryQueue | None = None,
        audit_recorder: (
            Callable[[AlertRequest, AlertResult], Awaitable[None]] | None
        ) = None,
        send_fn: SendFn | None = None,
    ) -> None:
        self._settings = settings
        self._rate_limiter = rate_limiter
        self._retry_queue = retry_queue
        self._audit_recorder = audit_recorder
        self._send_fn = send_fn  # None → use real Gmail

        # Read Gmail config from env (not from AlertSettings which uses ALERTS_ prefix).
        self._client_json = os.environ.get(
            "GMAIL_CLIENT_JSON",
            "gmail_credentials/gmailcredentials.json",
        )
        self._token_json = os.environ.get(
            "GMAIL_TOKEN_JSON",
            "gmail_credentials/token.json",
        )
        self._from_address: str = os.environ.get("ALERT_FROM", "").strip()

        # Resolved lazily (once the credentials are loaded for the first time).
        self._from_address_resolved: str | None = None

    # ------------------------------------------------------------------
    # NotificationChannel Protocol
    # ------------------------------------------------------------------

    async def send_alert(self, request: AlertRequest, *, to_email: str) -> AlertResult:
        """Send an alert email to ``to_email``.

        Never raises — failures appear as ``AlertResult(sent=False, ...)``.

        Note: the ``NotificationChannel`` Protocol defines ``send_alert(request)``
        with no ``to_email`` argument; the caller in ``_dispatch_alert``
        (main.py) resolves the recipient and passes it as a keyword argument.
        The Protocol is structurally satisfied because ``to_email`` has no
        default only in the concrete class — Protocol compatibility is checked at
        structural level (duck-typing), not signature level, in Python.
        """
        started = time.monotonic()
        try:
            return await self._send_inner(request, to_email, started)
        except Exception as exc:  # noqa: BLE001
            latency_ms = _elapsed_ms(started)
            ALERT_SEND_FAILURES.labels(reason=type(exc).__name__).inc()
            log.error(
                "alerts.gmail.unexpected_error",
                error=str(exc),
                exc_info=True,
            )
            return AlertResult(
                alert_id=compute_alert_id(request),
                sent=False,
                channel="email",
                error=str(exc),
                latency_ms=latency_ms,
                timestamp=datetime.now(timezone.utc),
            )

    async def get_alert_history(
        self,
        child_id: str,  # noqa: ARG002
        limit: int = 50,  # noqa: ARG002
    ) -> list[AlertResult]:
        """Return ``[]`` — history comes from the AuditStore."""
        return []

    def health_status(self) -> dict:
        queued = self._retry_queue.size() if self._retry_queue else 0
        ALERT_QUEUE_DEPTH.set(queued)
        return {
            "status": "degraded" if queued > 0 else "ok",
            "queued_alerts": queued,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _send_inner(
        self,
        request: AlertRequest,
        to_email: str,
        started: float,
    ) -> AlertResult:
        alert_id = compute_alert_id(request)

        # Rate-limit check.
        if not self._rate_limiter.allow(request.child_id):
            latency_ms = _elapsed_ms(started)
            ALERT_RATE_LIMITED.inc()
            log.warning(
                "alerts.gmail.rate_limited",
                trace_id=request.trace_id,
                alert_id=alert_id,
                child_id=request.child_id,
            )
            result = AlertResult(
                alert_id=alert_id,
                sent=False,
                rate_limited=True,
                channel="email",
                latency_ms=latency_ms,
                timestamp=datetime.now(timezone.utc),
            )
            await self._maybe_record_audit(request, result)
            return result

        # Resolve From address (once per instance lifetime).
        from_address = self._resolve_from_address()
        if not from_address:
            latency_ms = _elapsed_ms(started)
            err = "GmailApiNotifier: cannot determine From address"
            log.warning("alerts.gmail.no_from_address", alert_id=alert_id)
            result = AlertResult(
                alert_id=alert_id,
                sent=False,
                channel="email",
                error=err,
                latency_ms=latency_ms,
                timestamp=datetime.now(timezone.utc),
            )
            await self._maybe_record_audit(request, result)
            return result

        # Build the RFC 822 message.
        raw_b64 = _build_raw_message(to_email, from_address, request)

        # Attempt send (with retry).
        last_error: str | None = None
        for attempt in range(self._settings.max_retry_attempts):
            try:
                gmail_id = self._do_send(to_email, raw_b64)
                latency_ms = _elapsed_ms(started)
                ALERT_SEND_SUCCESS.inc()
                ALERT_SEND_LATENCY.observe(latency_ms / 1000.0)
                log.info(
                    "alerts.gmail.sent",
                    trace_id=request.trace_id,
                    alert_id=alert_id,
                    to=to_email,
                    gmail_id=gmail_id,
                    attempt=attempt + 1,
                    latency_ms=latency_ms,
                )
                result = AlertResult(
                    alert_id=alert_id,
                    sent=True,
                    channel="email",
                    fcm_message_id=gmail_id,  # reuse the fcm_message_id field
                    latency_ms=latency_ms,
                    timestamp=datetime.now(timezone.utc),
                )
                await self._maybe_record_audit(request, result)
                return result
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                ALERT_SEND_FAILURES.labels(reason=type(exc).__name__).inc()
                log.warning(
                    "alerts.gmail.send_attempt_failed",
                    trace_id=request.trace_id,
                    alert_id=alert_id,
                    attempt=attempt + 1,
                    error=last_error,
                )
                if attempt < self._settings.max_retry_attempts - 1:
                    import asyncio
                    delay = self._settings.retry_base_seconds * (2 ** attempt)
                    await asyncio.sleep(delay)

        # All retries exhausted.
        if self._retry_queue is not None:
            self._retry_queue.enqueue(request)
        log.error(
            "alerts.gmail.send_failed_queued",
            trace_id=request.trace_id,
            alert_id=alert_id,
            to=to_email,
            error=last_error,
        )
        latency_ms = _elapsed_ms(started)
        result = AlertResult(
            alert_id=alert_id,
            sent=False,
            queued=self._retry_queue is not None,
            channel="email",
            error=last_error,
            latency_ms=latency_ms,
            timestamp=datetime.now(timezone.utc),
        )
        await self._maybe_record_audit(request, result)
        return result

    def _do_send(self, to_email: str, raw_b64: str) -> str:
        """Execute the actual Gmail API call (or the injected test stub).

        Returns the Gmail-assigned message ID on success.  Raises on failure.
        """
        if self._send_fn is not None:
            return self._send_fn(to_email, raw_b64)

        # Real path: lazy-import Google libraries and call the API.
        service = self._get_service()
        response = (
            service.users()
            .messages()
            .send(userId="me", body={"raw": raw_b64})
            .execute()
        )
        return response.get("id", "")

    def _get_service(self):
        """Build an authorized Gmail API service (refreshes token if expired).

        Caches the service instance on ``self._service`` so it is only built once
        per process.  Token refresh persists the new access_token back to the
        token JSON file.

        Raises ``RuntimeError`` when credentials are missing or invalid.
        """
        if hasattr(self, "_service"):
            return self._service  # type: ignore[attr-defined]

        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise RuntimeError(
                "GmailApiNotifier requires google-auth and google-api-python-client. "
                "Install them: pip install google-auth google-auth-oauthlib google-api-python-client"
            ) from exc

        token_path = self._token_json
        if not os.path.exists(token_path):
            raise RuntimeError(
                f"GmailApiNotifier: token file not found at '{token_path}'. "
                "Run scripts/gmail_oauth_setup.py to mint the initial token."
            )

        creds = Credentials.from_authorized_user_file(token_path, scopes=_SCOPES)

        if not creds.valid:
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                # Persist the refreshed token so the next start doesn't need a round-trip.
                with open(token_path, "w", encoding="utf-8") as fh:
                    fh.write(creds.to_json())
                log.info("alerts.gmail.token_refreshed", token_path=token_path)
            else:
                raise RuntimeError(
                    "GmailApiNotifier: credentials are invalid and cannot be refreshed. "
                    "Run scripts/gmail_oauth_setup.py to re-authorise."
                )

        self._service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        return self._service

    def _resolve_from_address(self) -> str:
        """Return the sender email address.

        Priority:
        1. ``ALERT_FROM`` env var (if set and non-empty).
        2. Cached resolved value from a previous call.
        3. Call Gmail ``users.getProfile`` and cache the result.
        4. Return empty string on any failure.
        """
        if self._from_address:
            return self._from_address
        if self._from_address_resolved is not None:
            return self._from_address_resolved

        # Attempt to resolve via the API (best-effort).
        try:
            service = self._get_service()
            profile = service.users().getProfile(userId="me").execute()
            self._from_address_resolved = profile.get("emailAddress", "")
        except Exception as exc:  # noqa: BLE001
            log.warning("alerts.gmail.profile_resolve_failed", error=str(exc))
            self._from_address_resolved = ""
        return self._from_address_resolved or ""

    async def _maybe_record_audit(
        self, request: AlertRequest, result: AlertResult
    ) -> None:
        """Call the injected audit_recorder, swallowing any exception."""
        if self._audit_recorder is None:
            return
        try:
            await self._audit_recorder(request, result)
        except Exception:  # noqa: BLE001
            log.warning(
                "alerts.gmail.audit_recorder_failed",
                alert_id=result.alert_id,
                exc_info=True,
            )


# ---------------------------------------------------------------------------
# Internal timing helper
# ---------------------------------------------------------------------------


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
