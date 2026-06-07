"""FcmNotifier — Firebase Cloud Messaging NotificationChannel adapter.

Reference: docs/design/alerts/design.md §3 (FCMNotificationService),
           §5 (Firebase Admin Initialization), §8 (Failure Modes).

Backlog task: M6-ALERTS-FCM
----------------------------
This is a SKELETON implementation.  The complete FCM delivery path is a
Sprint 2 / Meeting-6 backlog task.  The code below:

1. Is importable without ``firebase-admin`` installed — the import is
   deferred until ``send_alert()`` is actually called.
2. Captures the full FCM payload structure and idempotency logic as
   commented code so the real implementation can be dropped in cleanly.
3. Returns ``AlertResult(sent=False, channel="fcm", error="FcmNotifier not
   enabled — backlog task M6-ALERTS-FCM")`` when ``firebase-admin`` is
   unavailable or no credentials are configured.

To enable FcmNotifier:
- Set ``FCM_SERVICE_ACCOUNT_PATH`` in ``server/.env`` to a valid Firebase
  service account JSON path.
- Run ``pip install firebase-admin`` inside the server venv.
- In ``server/app/main.py`` ``lifespan()`` swap ``LogNotifier`` for
  ``FcmNotifier``.
"""

from __future__ import annotations

import hashlib
import os
import time
from datetime import datetime, timezone

import structlog

from ..schemas import AlertRequest, AlertResult
from .log_notifier import compute_alert_id
from .protocol import AlertRateLimiter
from .retry_queue import LocalRetryQueue
from .settings import AlertSettings

log = structlog.get_logger("shomer.alerts")

# Friendly constant for the error message surfaced in AlertResult.
_NOT_ENABLED_MSG = "FcmNotifier not enabled — backlog task M6-ALERTS-FCM"


class FcmNotifier:
    """FCM push-notification channel (skeleton; see module docstring).

    Implements ``NotificationChannel`` so callers are unaffected when the real
    FCM path replaces this skeleton.  ``firebase-admin`` is lazy-imported
    inside ``send_alert()`` so this file can be imported on any machine.

    Parameters
    ----------
    settings:
        ``AlertSettings`` — reads ``fcm_channel_id``.
    rate_limiter:
        ``AlertRateLimiter`` adapter (e.g. ``InMemoryAlertRateLimiter``).
    retry_queue:
        ``LocalRetryQueue`` for degraded-mode buffering.
    """

    def __init__(
        self,
        settings: AlertSettings,
        rate_limiter: AlertRateLimiter,
        retry_queue: LocalRetryQueue | None = None,
    ) -> None:
        self._settings = settings
        self._rate_limiter = rate_limiter
        self._retry_queue = retry_queue

    # ------------------------------------------------------------------
    # NotificationChannel Protocol
    # ------------------------------------------------------------------

    async def send_alert(self, request: AlertRequest) -> AlertResult:
        """Attempt to send via FCM.  Returns a 'not enabled' result if
        ``firebase-admin`` is not installed or no credentials are configured.

        Backlog task M6-ALERTS-FCM: replace the body below with real FCM
        delivery code.  The scaffold is commented in-line for the implementor.
        """
        started = time.monotonic()
        alert_id = compute_alert_id(request)
        latency_ms = int((time.monotonic() - started) * 1000)

        # --- Lazy-import firebase_admin (M6-ALERTS-FCM: remove guard when live)
        try:
            import firebase_admin  # noqa: F401
            from firebase_admin import messaging  # noqa: F401
        except ImportError:
            log.warning(
                "alerts.fcm_unavailable",
                reason="firebase-admin not installed",
                trace_id=request.trace_id,
                alert_id=alert_id,
            )
            return AlertResult(
                alert_id=alert_id,
                sent=False,
                channel="fcm",
                error=_NOT_ENABLED_MSG,
                latency_ms=latency_ms,
                timestamp=datetime.now(timezone.utc),
            )

        # --- Check for credentials (M6-ALERTS-FCM: real init lives here) -----
        fcm_creds_path = os.environ.get("FCM_SERVICE_ACCOUNT_PATH", "").strip()
        if not fcm_creds_path:
            log.warning(
                "alerts.fcm_no_creds",
                reason="FCM_SERVICE_ACCOUNT_PATH not set",
                trace_id=request.trace_id,
                alert_id=alert_id,
            )
            return AlertResult(
                alert_id=alert_id,
                sent=False,
                channel="fcm",
                error=_NOT_ENABLED_MSG,
                latency_ms=latency_ms,
                timestamp=datetime.now(timezone.utc),
            )

        # --- M6-ALERTS-FCM: real delivery path (scaffold) --------------------
        # 1. Rate-limit check:
        #    if not self._rate_limiter.allow(request.child_id):
        #        return AlertResult(sent=False, rate_limited=True, ...)
        #
        # 2. Build FCM message payload:
        #    severity_icon = {"low": "🟡", "medium": "🟠",
        #                     "high": "🔴", "critical": "🚨"}
        #    fcm_msg = messaging.Message(
        #        notification=messaging.Notification(
        #            title=f"{severity_icon} Shomer.AI — {request.child_name}",
        #            body=request.explanation,
        #        ),
        #        data={
        #            "alert_id": alert_id,
        #            "child_id": request.child_id,
        #            "message_id": request.message_id,
        #            "label": request.label,
        #            "severity": request.severity,
        #            "quote": request.quote,
        #            "source": request.source,
        #            "trace_id": request.trace_id,
        #            "deep_link": f"shomer://alert/{alert_id}",
        #        },
        #        token=request.parent_fcm_token,
        #        android=messaging.AndroidConfig(
        #            priority="high",
        #            notification=messaging.AndroidNotification(
        #                channel_id=self._settings.fcm_channel_id,
        #                priority="high",
        #            ),
        #        ),
        #    )
        #
        # 3. Send with exponential backoff (max_retry_attempts attempts):
        #    for attempt in range(self._settings.max_retry_attempts):
        #        try:
        #            fcm_id = await asyncio.get_event_loop().run_in_executor(
        #                None, messaging.send, fcm_msg
        #            )
        #            return AlertResult(sent=True, fcm_message_id=fcm_id, ...)
        #        except Exception as exc:
        #            if attempt < max - 1:
        #                await asyncio.sleep(base * 2**attempt)
        #
        # 4. All retries exhausted → enqueue:
        #    if self._retry_queue:
        #        self._retry_queue.enqueue(request)
        #    return AlertResult(sent=False, queued=True, ...)
        # ---------------------------------------------------------------------

        # Fallback until M6-ALERTS-FCM is implemented:
        return AlertResult(
            alert_id=alert_id,
            sent=False,
            channel="fcm",
            error=_NOT_ENABLED_MSG,
            latency_ms=latency_ms,
            timestamp=datetime.now(timezone.utc),
        )

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
        return {
            "status": "degraded" if queued > 0 else "ok",
            "queued_alerts": queued,
        }
