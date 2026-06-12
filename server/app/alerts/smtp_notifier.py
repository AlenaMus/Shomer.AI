"""SmtpEmailNotifier — stdlib SMTP alert-email channel (NotificationChannel adapter).

Reference: docs/design/alerts/design.md §2.5 (NotificationChannel Protocol),
           plan-docs/decisions/child-only-and-email-alerts.decision.md (D-CO-2
           implementation note — SMTP recommended path).

Selected with ``ALERTS_CHANNEL=smtp`` in ``main.py`` ``lifespan()``.

Why SMTP over the Gmail API
---------------------------
The Gmail API (OAuth2) requires a Google Cloud project, restricted-scope
verification, and a one-time browser consent flow.  For the Shomer.AI MVP,
Gmail App Passwords + SMTP STARTTLS (or SSL) is simpler: add a 16-char app
password in Google Account Security settings, set four env vars, and the
adapter works — no Cloud Console, no OAuth consent screen, no redirect URIs.

Transport options
-----------------
STARTTLS (default, port 587)
    ``SMTP(host, port)`` → ``starttls()`` → ``login(user, app_password)``
    → ``send_message(msg)``.

SSL (SMTP_USE_SSL=true, typically port 465)
    ``SMTP_SSL(host, port)`` — negotiates TLS on connect, no STARTTLS upgrade.

Env vars (read from ``os.environ``; NOT from AlertSettings / ALERTS_ prefix)
-----------------------------------------------------------------------------
SMTP_HOST         SMTP server hostname.   Default: ``smtp.gmail.com``.
SMTP_PORT         SMTP port.              Default: ``587``.
SMTP_USER         SMTP login username.    **Required** (graceful no-send if absent).
SMTP_APP_PASSWORD App-specific password.  **Required** (graceful no-send if absent).
ALERT_FROM        Sender "From" address.  Default: ``SMTP_USER``.
SMTP_USE_SSL      Use SMTP_SSL on connect. Default: ``false``.

Failure semantics
-----------------
- Missing ``SMTP_USER`` / ``SMTP_APP_PASSWORD`` → warn + return
  ``AlertResult(sent=False, error=...)`` immediately — NEVER raise.
- Any SMTP exception (auth failure, connection refused, timeout) →
  ``AlertResult(sent=False, error=...)``, NEVER raise into the pipeline.

Testability
-----------
An injectable ``smtp_factory`` replaces the real ``smtplib.SMTP`` /
``smtplib.SMTP_SSL`` call.  Factory signature:
    ``() -> context-manager exposing .starttls(), .login(), .send_message()``

Tests pass a MagicMock factory — no real socket is ever opened.

Alert email content
-------------------
Delegates to ``alerts.email_message`` (shared with ``GmailApiNotifier``):
``build_email_message(to, from, request) → EmailMessage``.

Delivery path mirrors GmailApiNotifier
--------------------------------------
1. ``alert_id = sha256(child_id:message_id:label)[:16]`` — idempotency key.
2. Rate-limit check.
3. Validate credentials are configured (warn + return if missing).
4. Build MIME message via the shared helper.
5. Run blocking SMTP call in ``asyncio.to_thread`` (never blocks the loop).
6. On failure → ``AlertResult(sent=False, error=...)``; NEVER raise.
7. Invoke ``audit_recorder`` callback (best-effort).
"""

from __future__ import annotations

import asyncio
import os
import smtplib
import time
from datetime import datetime, timezone
from typing import Awaitable, Callable

import structlog

from ..schemas import AlertRequest, AlertResult
from .email_message import build_email_message
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

log = structlog.get_logger("shomer.alerts.smtp")

# Type alias for the injectable SMTP factory (enables socket-free testing).
# The factory is a zero-argument callable that returns a context manager whose
# object exposes .starttls(), .ehlo(), .login(user, pw), .send_message(msg).
SmtpFactory = Callable[[], object]


def _make_default_factory(
    host: str, port: int, use_ssl: bool, timeout_s: float = 15.0
) -> SmtpFactory:
    """Return a factory that opens a real SMTP connection."""

    def _factory():
        if use_ssl:
            return smtplib.SMTP_SSL(host, port, timeout=timeout_s)
        return smtplib.SMTP(host, port, timeout=timeout_s)

    return _factory


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


class SmtpEmailNotifier:
    """SMTP alert-email channel (``NotificationChannel`` adapter).

    Parameters
    ----------
    settings:
        ``AlertSettings`` — rate-limit / retry / queue params.
        SMTP credential env vars are read from ``os.environ`` directly
        (``SMTP_HOST``, ``SMTP_PORT``, ``SMTP_USER``, ``SMTP_APP_PASSWORD``,
        ``ALERT_FROM``, ``SMTP_USE_SSL``).
    rate_limiter:
        ``AlertRateLimiter`` adapter.
    retry_queue:
        Optional ``LocalRetryQueue`` for degraded-mode buffering.
    audit_recorder:
        Optional async callback ``(AlertRequest, AlertResult) → None``.
    smtp_factory:
        Injectable for tests — replaces the real smtplib SMTP constructor.
        When ``None``, the real SMTP connection is used.
    """

    def __init__(
        self,
        settings: AlertSettings,
        rate_limiter: AlertRateLimiter,
        retry_queue: LocalRetryQueue | None = None,
        audit_recorder: (
            Callable[[AlertRequest, AlertResult], Awaitable[None]] | None
        ) = None,
        smtp_factory: SmtpFactory | None = None,
    ) -> None:
        self._settings = settings
        self._rate_limiter = rate_limiter
        self._retry_queue = retry_queue
        self._audit_recorder = audit_recorder

        # Read SMTP config from env (not from AlertSettings / ALERTS_ prefix).
        self._host: str = os.environ.get("SMTP_HOST", "smtp.gmail.com").strip()
        raw_port = os.environ.get("SMTP_PORT", "587").strip()
        try:
            self._port: int = int(raw_port)
        except ValueError:
            log.warning("smtp_notifier.invalid_port", raw=raw_port, fallback=587)
            self._port = 587
        # Accept GMAIL_USER / GMAIL_PASSWORD as friendly aliases for the
        # SMTP_* names (Gmail App Password setup) — SMTP_* wins if both set.
        self._user: str = (
            os.environ.get("SMTP_USER", "").strip()
            or os.environ.get("GMAIL_USER", "").strip()
        )
        self._password: str = (
            os.environ.get("SMTP_APP_PASSWORD", "").strip()
            or os.environ.get("GMAIL_PASSWORD", "").strip()
        )
        self._from: str = (
            os.environ.get("ALERT_FROM", "").strip() or self._user
        )
        _use_ssl_raw = os.environ.get("SMTP_USE_SSL", "false").strip().lower()
        self._use_ssl: bool = _use_ssl_raw in ("1", "true", "yes")

        # If an injectable factory was supplied, use it; otherwise build the
        # real one now so it can be replaced cheaply in tests.
        self._smtp_factory: SmtpFactory = smtp_factory or _make_default_factory(
            self._host, self._port, self._use_ssl
        )

    # ------------------------------------------------------------------
    # NotificationChannel Protocol
    # ------------------------------------------------------------------

    async def send_alert(self, request: AlertRequest, *, to_email: str) -> AlertResult:
        """Send an alert email to ``to_email`` via SMTP.

        Never raises — failures appear as ``AlertResult(sent=False, ...)``.
        """
        started = time.monotonic()
        try:
            return await self._send_inner(request, to_email, started)
        except Exception as exc:  # noqa: BLE001
            latency_ms = _elapsed_ms(started)
            ALERT_SEND_FAILURES.labels(reason=type(exc).__name__).inc()
            log.error(
                "alerts.smtp.unexpected_error",
                error=str(exc),
                exc_info=True,
            )
            return AlertResult(
                alert_id=compute_alert_id(request),
                sent=False,
                channel="smtp",
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
                "alerts.smtp.rate_limited",
                trace_id=request.trace_id,
                alert_id=alert_id,
                child_id=request.child_id,
            )
            result = AlertResult(
                alert_id=alert_id,
                sent=False,
                rate_limited=True,
                channel="smtp",
                latency_ms=latency_ms,
                timestamp=datetime.now(timezone.utc),
            )
            await self._maybe_record_audit(request, result)
            return result

        # Validate credentials are present.
        if not self._user or not self._password:
            latency_ms = _elapsed_ms(started)
            err = (
                "SmtpEmailNotifier: SMTP_USER and/or SMTP_APP_PASSWORD are not set. "
                "Set them in server/.env to enable SMTP email alerts."
            )
            log.warning("alerts.smtp.credentials_missing", alert_id=alert_id)
            result = AlertResult(
                alert_id=alert_id,
                sent=False,
                channel="smtp",
                error=err,
                latency_ms=latency_ms,
                timestamp=datetime.now(timezone.utc),
            )
            await self._maybe_record_audit(request, result)
            return result

        # Attempt send (with retry).
        last_error: str | None = None
        for attempt in range(self._settings.max_retry_attempts):
            try:
                await asyncio.to_thread(
                    self._do_send_sync, to_email, request
                )
                latency_ms = _elapsed_ms(started)
                ALERT_SEND_SUCCESS.inc()
                ALERT_SEND_LATENCY.observe(latency_ms / 1000.0)
                log.info(
                    "alerts.smtp.sent",
                    trace_id=request.trace_id,
                    alert_id=alert_id,
                    to=to_email,
                    host=self._host,
                    port=self._port,
                    ssl=self._use_ssl,
                    attempt=attempt + 1,
                    latency_ms=latency_ms,
                )
                result = AlertResult(
                    alert_id=alert_id,
                    sent=True,
                    channel="smtp",
                    latency_ms=latency_ms,
                    timestamp=datetime.now(timezone.utc),
                )
                await self._maybe_record_audit(request, result)
                return result
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                ALERT_SEND_FAILURES.labels(reason=type(exc).__name__).inc()
                log.warning(
                    "alerts.smtp.send_attempt_failed",
                    trace_id=request.trace_id,
                    alert_id=alert_id,
                    attempt=attempt + 1,
                    host=self._host,
                    port=self._port,
                    error=last_error,
                )
                if attempt < self._settings.max_retry_attempts - 1:
                    delay = self._settings.retry_base_seconds * (2 ** attempt)
                    await asyncio.sleep(delay)

        # All retries exhausted — enqueue if possible.
        if self._retry_queue is not None:
            self._retry_queue.enqueue(request)
        log.error(
            "alerts.smtp.send_failed_queued",
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
            channel="smtp",
            error=last_error,
            latency_ms=latency_ms,
            timestamp=datetime.now(timezone.utc),
        )
        await self._maybe_record_audit(request, result)
        return result

    def _do_send_sync(self, to_email: str, request: AlertRequest) -> None:
        """Blocking SMTP send — called via ``asyncio.to_thread``.

        Raises on any SMTP error (the async caller handles retries).
        """
        msg = build_email_message(to_email, self._from, request)

        smtp_conn = self._smtp_factory()

        # If the factory returns a context manager use it; otherwise call directly.
        if hasattr(smtp_conn, "__enter__"):
            with smtp_conn as smtp:
                if not self._use_ssl:
                    smtp.ehlo()
                    smtp.starttls()
                    smtp.ehlo()
                smtp.login(self._user, self._password)
                smtp.send_message(msg)
        else:
            # Injectable mock path — the mock is not a context manager; call directly.
            if not self._use_ssl:
                smtp_conn.ehlo()
                smtp_conn.starttls()
                smtp_conn.ehlo()
            smtp_conn.login(self._user, self._password)
            smtp_conn.send_message(msg)

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
                "alerts.smtp.audit_recorder_failed",
                alert_id=result.alert_id,
                exc_info=True,
            )
