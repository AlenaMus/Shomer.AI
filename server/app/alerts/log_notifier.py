"""LogNotifier — default NotificationChannel adapter for the Alerts module.

Reference: docs/design/alerts/design.md §2.5 (NotificationChannel Protocol),
           decisions/meeting-6-server-flow.decision.md (D1: LogNotifier default).

Sprint decision (D1)
--------------------
For this sprint the default notification channel is ``LogNotifier``.  It
makes the full pipeline ``ALERT_DIRECT → send_alert() → recorded``
demonstrable and testable WITHOUT any Firebase setup.  The real FCM path
(``FcmNotifier``) is deliberately deferred to backlog task ``M6-ALERTS-FCM``.

Behaviour of send_alert()
--------------------------
1. Compute ``alert_id = sha256(f"{child_id}:{message_id}:{label}")[:16]``.
2. Rate-limit check via ``rate_limiter.allow(request.child_id)``.
   If denied → return ``AlertResult(sent=False, rate_limited=True, ...)``.
3. Emit a structured ``structlog`` line ``event="alerts.sent"`` with all
   diagnostic fields.  Return ``AlertResult(sent=True, channel="log", ...)``.
4. If an ``audit_recorder`` callback was injected, ``await`` it (errors
   from the callback are swallowed — NEVER propagated).

Failure contract: ``send_alert()`` NEVER raises.  Any internal error is
captured into ``AlertResult(sent=False, error=str(exc))``.

get_alert_history()
-------------------
Returns ``[]``.  Real history comes from the AuditStore once Phase B wires
``SqliteAuditStore`` and the injected ``audit_recorder`` persists to it.
"""

from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone
from typing import Awaitable, Callable

import structlog

from ..schemas import AlertRequest, AlertResult
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


# ---------------------------------------------------------------------------
# Helper — shared with FcmNotifier and tests.
# ---------------------------------------------------------------------------


def compute_alert_id(request: AlertRequest) -> str:
    """Deterministic idempotency key: sha256(child_id:message_id:label)[:16].

    Same inputs always produce the same 16-hex-char string regardless of
    call site or retry attempt, so the Android parent app can deduplicate
    duplicate pushes via ``NotificationManager.cancel(alertId)``.
    """
    raw = f"{request.child_id}:{request.message_id}:{request.label}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# LogNotifier
# ---------------------------------------------------------------------------


class LogNotifier:
    """Default NotificationChannel — emits a structured log line per alert.

    No external dependencies (no Firebase, no network).  Satisfies the full
    ``NotificationChannel`` Protocol so it can be swapped for ``FcmNotifier``
    with a single line change in ``lifespan()``.

    Parameters
    ----------
    settings:
        Module-level configuration (channel, rate-limit params, etc.).
    rate_limiter:
        ``AlertRateLimiter`` adapter (e.g. ``InMemoryAlertRateLimiter``).
    retry_queue:
        Optional ``LocalRetryQueue``.  When present its depth is reflected
        in ``health_status()``; when absent the queue depth is always 0.
    audit_recorder:
        Optional async callback ``(AlertRequest, AlertResult) → None``.
        Phase B will pass an adapter that writes to ``SqliteAuditStore``.
        Errors from the callback are silently swallowed.
    """

    def __init__(
        self,
        settings: AlertSettings,
        rate_limiter: AlertRateLimiter,
        retry_queue: LocalRetryQueue | None = None,
        audit_recorder: (
            Callable[[AlertRequest, AlertResult], Awaitable[None]] | None
        ) = None,
    ) -> None:
        self._settings = settings
        self._rate_limiter = rate_limiter
        self._retry_queue = retry_queue
        self._audit_recorder = audit_recorder

    # ------------------------------------------------------------------
    # NotificationChannel Protocol
    # ------------------------------------------------------------------

    async def send_alert(self, request: AlertRequest) -> AlertResult:
        """Emit a structured log line for the alert.

        Never raises — failures appear as ``AlertResult(sent=False, ...)``.
        """
        started = time.monotonic()
        try:
            return await self._send_inner(request, started)
        except Exception as exc:  # noqa: BLE001
            latency_ms = _elapsed_ms(started)
            ALERT_SEND_FAILURES.labels(reason=type(exc).__name__).inc()
            log.error(
                "alerts.unexpected_error",
                error=str(exc),
                exc_info=True,
            )
            return AlertResult(
                alert_id=compute_alert_id(request),
                sent=False,
                channel="log",
                error=str(exc),
                latency_ms=latency_ms,
                timestamp=datetime.now(timezone.utc),
            )

    async def _send_inner(
        self, request: AlertRequest, started: float
    ) -> AlertResult:
        alert_id = compute_alert_id(request)

        # Step 2 — rate-limit check.
        if not self._rate_limiter.allow(request.child_id):
            latency_ms = _elapsed_ms(started)
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
                channel="log",
                latency_ms=latency_ms,
                timestamp=datetime.now(timezone.utc),
            )
            await self._maybe_record_audit(request, result)
            return result

        # Step 3 — emit structured log line.
        latency_ms = _elapsed_ms(started)
        log.info(
            "alerts.sent",
            trace_id=request.trace_id,
            alert_id=alert_id,
            child_id=request.child_id,
            label=request.label,
            severity=request.severity,
            quote=request.quote,
            explanation=request.explanation,
            source=request.source,
        )
        ALERT_SEND_SUCCESS.inc()
        ALERT_SEND_LATENCY.observe(latency_ms / 1000.0)

        result = AlertResult(
            alert_id=alert_id,
            sent=True,
            channel="log",
            fcm_message_id=None,
            latency_ms=latency_ms,
            timestamp=datetime.now(timezone.utc),
        )

        # Step 4 — optional audit recorder (NEVER raises to caller).
        await self._maybe_record_audit(request, result)

        return result

    async def get_alert_history(
        self,
        child_id: str,  # noqa: ARG002
        limit: int = 50,  # noqa: ARG002
    ) -> list[AlertResult]:
        """Return ``[]`` — history comes from the AuditStore in Phase B.

        ``LogNotifier`` does not persist history internally.  Phase B wires
        the ``audit_recorder`` so that every send is persisted; then this
        method can query it.  Until then, callers must use the AuditStore
        directly for history queries.
        """
        return []

    def health_status(self) -> dict:
        """Return the health dict for the ``/health`` rollup.

        ``status`` is ``"degraded"`` when the retry queue has items (meaning
        previous sends failed).  ``"ok"`` otherwise.
        """
        queued = self._retry_queue.size() if self._retry_queue else 0
        ALERT_QUEUE_DEPTH.set(queued)
        return {
            "status": "degraded" if queued > 0 else "ok",
            "queued_alerts": queued,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

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
                "alerts.audit_recorder_failed",
                alert_id=result.alert_id,
                exc_info=True,
            )


# ---------------------------------------------------------------------------
# Internal timing helper
# ---------------------------------------------------------------------------


def _elapsed_ms(started: float) -> int:
    """Return elapsed wall-clock milliseconds since ``started``."""
    return int((time.monotonic() - started) * 1000)
