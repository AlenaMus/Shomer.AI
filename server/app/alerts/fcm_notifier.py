"""FcmNotifier — Firebase Cloud Messaging NotificationChannel adapter.

Reference: docs/design/alerts/design.md §3 (FCMNotificationService),
           §5 (Firebase Admin Initialization), §8 (Failure Modes).
Backlog task: M6-ALERTS-FCM (implemented).

Delivery path (``send_alert``)
------------------------------
1. ``alert_id = sha256(child_id:message_id:label)[:16]`` — idempotency key
   (shared with ``LogNotifier`` via ``compute_alert_id``).
2. Resolve the FCM sender.  If ``firebase-admin`` is not installed OR no
   credentials are configured, return ``AlertResult(sent=False,
   error="FCM not configured: …")`` — the channel degrades gracefully and
   NEVER crashes.
3. Rate-limit via ``rate_limiter.allow(child_id)`` → ``rate_limited=True`` if denied.
4. Build the ``messaging.Message`` (Hebrew title/body + ``data`` payload +
   high-priority ``AndroidConfig``) and send it with exponential backoff
   (``max_retry_attempts`` attempts; delays ``retry_base * 2**n``).
5. All attempts exhausted → ``retry_queue.enqueue(request)`` and return
   ``AlertResult(sent=False, queued=True, …)``.
6. Every disposition is passed to the injected ``audit_recorder`` (best-effort).

Testability
-----------
``firebase-admin`` is an optional, heavy dependency (only needed when
``ALERTS_CHANNEL=fcm``).  This module is importable without it: the import is
deferred to first send, and tests inject a fake ``send_fn`` so the
rate-limit / retry / queue logic is exercised with no real Firebase.

To enable in production:
- ``pip install firebase-admin`` inside the server venv.
- Set ``FCM_SERVICE_ACCOUNT_PATH`` to a valid Firebase service-account JSON.
- Set ``ALERTS_CHANNEL=fcm`` (``main.py`` ``lifespan()`` then selects this adapter).
"""

from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timezone
from typing import Awaitable, Callable

import structlog

from ..schemas import AlertRequest, AlertResult
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

log = structlog.get_logger("shomer.alerts")

# ``send_fn(request, alert_id) -> fcm_message_id``.  Synchronous (runs in a
# thread-pool executor); raises on delivery failure.  Injectable for tests.
SendFn = Callable[[AlertRequest, str], str]

_SEVERITY_ICON = {"low": "🟡", "medium": "🟠", "high": "🔴", "critical": "🚨"}


class FcmNotifier:
    """FCM push-notification channel (``NotificationChannel`` adapter).

    Parameters
    ----------
    settings:
        ``AlertSettings`` — reads ``fcm_channel_id``, ``max_retry_attempts``,
        ``retry_base_seconds``.
    rate_limiter:
        ``AlertRateLimiter`` adapter (e.g. ``InMemoryAlertRateLimiter``).
    retry_queue:
        Optional ``LocalRetryQueue`` for degraded-mode buffering.
    audit_recorder:
        Optional async ``(AlertRequest, AlertResult) → None`` callback; errors
        are swallowed (best-effort persistence).
    service_account_path:
        Firebase service-account JSON path.  Defaults to the
        ``FCM_SERVICE_ACCOUNT_PATH`` env var (kept as a bare read — not an
        ``ALERTS_`` setting — per LLD §6, because it is a Firebase credential).
    send_fn:
        Test seam.  When provided, FCM is considered configured and this
        callable is used instead of the real ``firebase_admin.messaging.send``.
    """

    def __init__(
        self,
        settings: AlertSettings,
        rate_limiter: AlertRateLimiter,
        retry_queue: LocalRetryQueue | None = None,
        audit_recorder: (
            Callable[[AlertRequest, AlertResult], Awaitable[None]] | None
        ) = None,
        *,
        service_account_path: str | None = None,
        send_fn: SendFn | None = None,
    ) -> None:
        self._settings = settings
        self._rate_limiter = rate_limiter
        self._retry_queue = retry_queue
        self._audit_recorder = audit_recorder
        self._creds_path = (
            service_account_path
            if service_account_path is not None
            else os.environ.get("FCM_SERVICE_ACCOUNT_PATH", "").strip()
        )
        self._injected_send_fn = send_fn
        # Cached real sender once Firebase is initialised (lazy, idempotent).
        self._resolved_send_fn: SendFn | None = send_fn

    # ------------------------------------------------------------------
    # NotificationChannel Protocol
    # ------------------------------------------------------------------

    async def send_alert(self, request: AlertRequest) -> AlertResult:
        """Deliver via FCM.  NEVER raises — failures become AlertResult."""
        started = time.monotonic()
        try:
            return await self._send_inner(request, started)
        except Exception as exc:  # noqa: BLE001 — contract: never raises
            ALERT_SEND_FAILURES.labels(reason=type(exc).__name__).inc()
            log.error("alerts.fcm_unexpected_error", error=str(exc), exc_info=True)
            result = AlertResult(
                alert_id=compute_alert_id(request),
                sent=False,
                channel="fcm",
                error=str(exc),
                latency_ms=_elapsed_ms(started),
                timestamp=datetime.now(timezone.utc),
            )
            await self._maybe_record_audit(request, result)
            return result

    async def _send_inner(
        self, request: AlertRequest, started: float
    ) -> AlertResult:
        alert_id = compute_alert_id(request)

        # Step 1 — resolve the sender (firebase init / config check).
        send_fn, disabled_reason = self._resolve_send_fn(request, alert_id)
        if send_fn is None:
            ALERT_SEND_FAILURES.labels(reason="not_configured").inc()
            result = AlertResult(
                alert_id=alert_id,
                sent=False,
                channel="fcm",
                error=disabled_reason,
                latency_ms=_elapsed_ms(started),
                timestamp=datetime.now(timezone.utc),
            )
            await self._maybe_record_audit(request, result)
            return result

        # Step 2 — rate-limit check (anti-storm guard).
        if not self._rate_limiter.allow(request.child_id):
            ALERT_RATE_LIMITED.inc()
            log.warning(
                "alerts.rate_limited",
                trace_id=request.trace_id,
                alert_id=alert_id,
                child_id=request.child_id,
            )
            result = AlertResult(
                alert_id=alert_id,
                sent=False,
                rate_limited=True,
                channel="fcm",
                latency_ms=_elapsed_ms(started),
                timestamp=datetime.now(timezone.utc),
            )
            await self._maybe_record_audit(request, result)
            return result

        # Step 3 — send with exponential backoff.
        loop = asyncio.get_event_loop()
        attempts = max(1, self._settings.max_retry_attempts)
        last_error: str | None = None
        for attempt in range(attempts):
            try:
                fcm_id = await loop.run_in_executor(
                    None, send_fn, request, alert_id
                )
                latency_ms = _elapsed_ms(started)
                ALERT_SEND_SUCCESS.inc()
                ALERT_SEND_LATENCY.observe(latency_ms / 1000.0)
                log.info(
                    "alerts.sent",
                    channel="fcm",
                    trace_id=request.trace_id,
                    alert_id=alert_id,
                    child_id=request.child_id,
                    label=request.label,
                    severity=request.severity,
                    fcm_message_id=fcm_id,
                    attempt=attempt + 1,
                )
                result = AlertResult(
                    alert_id=alert_id,
                    sent=True,
                    channel="fcm",
                    fcm_message_id=str(fcm_id) if fcm_id is not None else None,
                    latency_ms=latency_ms,
                    timestamp=datetime.now(timezone.utc),
                )
                await self._maybe_record_audit(request, result)
                return result
            except Exception as exc:  # noqa: BLE001 — retry then queue
                last_error = str(exc)
                ALERT_SEND_FAILURES.labels(reason=type(exc).__name__).inc()
                log.warning(
                    "alerts.fcm_send_failed",
                    trace_id=request.trace_id,
                    alert_id=alert_id,
                    attempt=attempt + 1,
                    error=last_error,
                )
                if attempt < attempts - 1:
                    await asyncio.sleep(
                        self._settings.retry_base_seconds * (2**attempt)
                    )

        # Step 4 — all attempts exhausted → queue for later drain.
        if self._retry_queue is not None:
            self._retry_queue.enqueue(request)
            ALERT_QUEUE_DEPTH.set(self._retry_queue.size())
        log.error(
            "alerts.fcm_queued",
            trace_id=request.trace_id,
            alert_id=alert_id,
            attempts=attempts,
            error=last_error,
        )
        result = AlertResult(
            alert_id=alert_id,
            sent=False,
            queued=True,
            channel="fcm",
            error=last_error,
            latency_ms=_elapsed_ms(started),
            timestamp=datetime.now(timezone.utc),
        )
        await self._maybe_record_audit(request, result)
        return result

    async def get_alert_history(
        self,
        child_id: str,  # noqa: ARG002
        limit: int = 50,  # noqa: ARG002
    ) -> list[AlertResult]:
        """Return ``[]`` — history is stored in the AuditStore (Phase B)."""
        return []

    def health_status(self) -> dict:
        """Reflect retry-queue depth; ``"degraded"`` when queue is non-empty."""
        queued = self._retry_queue.size() if self._retry_queue else 0
        ALERT_QUEUE_DEPTH.set(queued)
        return {
            "status": "degraded" if queued > 0 else "ok",
            "queued_alerts": queued,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_send_fn(
        self, request: AlertRequest, alert_id: str
    ) -> tuple[SendFn | None, str | None]:
        """Return ``(send_fn, None)`` when FCM is usable, else ``(None, reason)``.

        Lazily imports ``firebase-admin`` and initialises the default app once
        (idempotent).  An injected ``send_fn`` short-circuits this entirely.
        """
        if self._resolved_send_fn is not None:
            return self._resolved_send_fn, None

        try:
            import firebase_admin
            from firebase_admin import credentials, messaging
        except ImportError:
            log.warning(
                "alerts.fcm_unavailable",
                reason="firebase-admin not installed",
                trace_id=request.trace_id,
                alert_id=alert_id,
            )
            return None, "FCM not configured: firebase-admin not installed"

        if not self._creds_path:
            log.warning(
                "alerts.fcm_no_creds",
                reason="FCM_SERVICE_ACCOUNT_PATH not set",
                trace_id=request.trace_id,
                alert_id=alert_id,
            )
            return None, "FCM not configured: FCM_SERVICE_ACCOUNT_PATH not set"

        # Initialise the default Firebase app exactly once (idempotent).
        try:
            firebase_admin.get_app()
        except ValueError:
            try:
                cred = credentials.Certificate(self._creds_path)
                firebase_admin.initialize_app(cred)
            except Exception as exc:  # noqa: BLE001 — bad creds → disabled
                log.error(
                    "alerts.fcm_init_failed",
                    error=str(exc),
                    creds_path=self._creds_path,
                )
                return None, f"FCM not configured: init failed ({exc})"

        self._resolved_send_fn = self._build_real_send_fn(messaging)
        return self._resolved_send_fn, None

    def _build_real_send_fn(self, messaging) -> SendFn:  # noqa: ANN001
        """Closure that builds the FCM message and sends it (blocking)."""

        def _send(request: AlertRequest, alert_id: str) -> str:
            message = self._build_message(messaging, request, alert_id)
            return messaging.send(message)

        return _send

    def _build_message(self, messaging, request: AlertRequest, alert_id: str):  # noqa: ANN001, ANN201
        """Build the FCM ``Message`` per LLD §3 (Hebrew title + data payload)."""
        icon = _SEVERITY_ICON.get(request.severity, "🔔")
        return messaging.Message(
            notification=messaging.Notification(
                title=f"{icon} Shomer.AI — {request.child_name}".strip(),
                body=request.explanation,
            ),
            data={
                "alert_id": alert_id,
                "child_id": request.child_id,
                "message_id": request.message_id,
                "label": request.label,
                "severity": request.severity,
                "quote": request.quote,
                "source": request.source,
                "trace_id": request.trace_id,
                "deep_link": f"shomer://alert/{alert_id}",
            },
            token=request.parent_fcm_token,
            android=messaging.AndroidConfig(
                priority="high",
                notification=messaging.AndroidNotification(
                    channel_id=self._settings.fcm_channel_id,
                    priority="high",
                ),
            ),
        )

    async def _maybe_record_audit(
        self, request: AlertRequest, result: AlertResult
    ) -> None:
        """Call the injected audit_recorder, swallowing any exception."""
        if self._audit_recorder is None:
            return
        try:
            await self._audit_recorder(request, result)
        except Exception:  # noqa: BLE001 — audit is best-effort
            log.warning(
                "alerts.audit_recorder_failed",
                alert_id=result.alert_id,
                exc_info=True,
            )


def _elapsed_ms(started: float) -> int:
    """Return elapsed wall-clock milliseconds since ``started``."""
    return int((time.monotonic() - started) * 1000)
