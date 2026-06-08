"""NtfyNotifier — free push delivery via ntfy.sh (no Firebase, no account).

Reference: docs/design/alerts/design.md §2.5 (NotificationChannel Protocol).

ntfy (https://ntfy.sh) is an open-source pub-sub push service. The server
publishes a JSON notification to a *topic*; the parent installs the free ntfy
app (Android/iOS/web), subscribes to that topic, and receives proactive pushes
on their phone. There is no account, no credential file, and no per-message
cost — the easiest "real phone notification" channel to stand up.

Why JSON publish (not the header API)
-------------------------------------
ntfy's simple API puts the title in an ``X-Title`` HTTP header, but HTTP
headers are latin-1 and would mangle Hebrew. The JSON publish endpoint
(``POST {server}`` with ``{"topic", "title", "message", …}``) is UTF-8 and
carries Hebrew titles/bodies cleanly.

Delivery path mirrors LogNotifier/FcmNotifier: idempotency key → rate-limit →
build payload → POST with exponential-backoff retry → LocalRetryQueue fallback
→ best-effort audit callback. ``send_alert`` NEVER raises.

Enable with ``ALERTS_CHANNEL=ntfy`` + ``ALERTS_NTFY_TOPIC=<your-topic>``.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Awaitable, Callable

import httpx
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

_SEVERITY_ICON = {"low": "🟡", "medium": "🟠", "high": "🔴", "critical": "🚨"}

# ntfy priority is 1 (min) … 5 (max). Map our 4-level severity onto it.
_NTFY_PRIORITY = {"low": 2, "medium": 3, "high": 4, "critical": 5}


class NtfyNotifier:
    """ntfy.sh push-notification channel (``NotificationChannel`` adapter).

    Parameters
    ----------
    settings:
        ``AlertSettings`` — reads ``ntfy_server``, ``ntfy_topic``,
        ``ntfy_token``, ``ntfy_click_url``, ``ntfy_timeout_s`` and the shared
        retry knobs (``max_retry_attempts``, ``retry_base_seconds``).
    rate_limiter:
        ``AlertRateLimiter`` adapter (e.g. ``InMemoryAlertRateLimiter``).
    retry_queue:
        Optional ``LocalRetryQueue`` for degraded-mode buffering.
    audit_recorder:
        Optional async ``(AlertRequest, AlertResult) → None`` callback; errors
        are swallowed (best-effort persistence).
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
        self._server = settings.ntfy_server.rstrip("/")
        self._topic = settings.ntfy_topic.strip()
        self._token = settings.ntfy_token.strip()
        self._click_url = settings.ntfy_click_url.strip()
        self._timeout = settings.ntfy_timeout_s

    # ------------------------------------------------------------------
    # NotificationChannel Protocol
    # ------------------------------------------------------------------

    async def send_alert(self, request: AlertRequest) -> AlertResult:
        """Publish to ntfy. NEVER raises — failures become AlertResult."""
        started = time.monotonic()
        try:
            return await self._send_inner(request, started)
        except Exception as exc:  # noqa: BLE001 — contract: never raises
            ALERT_SEND_FAILURES.labels(reason=type(exc).__name__).inc()
            log.error("alerts.ntfy_unexpected_error", error=str(exc), exc_info=True)
            result = AlertResult(
                alert_id=compute_alert_id(request),
                sent=False,
                channel="ntfy",
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

        # Step 1 — config check.
        if not self._topic:
            ALERT_SEND_FAILURES.labels(reason="not_configured").inc()
            log.warning(
                "alerts.ntfy_no_topic",
                reason="ALERTS_NTFY_TOPIC not set",
                trace_id=request.trace_id,
                alert_id=alert_id,
            )
            result = AlertResult(
                alert_id=alert_id,
                sent=False,
                channel="ntfy",
                error="ntfy not configured: ALERTS_NTFY_TOPIC not set",
                latency_ms=_elapsed_ms(started),
                timestamp=datetime.now(timezone.utc),
            )
            await self._maybe_record_audit(request, result)
            return result

        # Step 2 — rate-limit check.
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
                channel="ntfy",
                latency_ms=_elapsed_ms(started),
                timestamp=datetime.now(timezone.utc),
            )
            await self._maybe_record_audit(request, result)
            return result

        # Step 3 — publish with exponential backoff.
        payload = self._build_payload(request, alert_id)
        headers = {"Authorization": f"Bearer {self._token}"} if self._token else {}
        attempts = max(1, self._settings.max_retry_attempts)
        last_error: str | None = None

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            for attempt in range(attempts):
                try:
                    resp = await client.post(
                        self._server, json=payload, headers=headers
                    )
                    resp.raise_for_status()
                    msg_id = _extract_message_id(resp)
                    latency_ms = _elapsed_ms(started)
                    ALERT_SEND_SUCCESS.inc()
                    ALERT_SEND_LATENCY.observe(latency_ms / 1000.0)
                    log.info(
                        "alerts.sent",
                        channel="ntfy",
                        trace_id=request.trace_id,
                        alert_id=alert_id,
                        child_id=request.child_id,
                        label=request.label,
                        severity=request.severity,
                        ntfy_message_id=msg_id,
                        attempt=attempt + 1,
                    )
                    result = AlertResult(
                        alert_id=alert_id,
                        sent=True,
                        channel="ntfy",
                        fcm_message_id=msg_id,
                        latency_ms=latency_ms,
                        timestamp=datetime.now(timezone.utc),
                    )
                    await self._maybe_record_audit(request, result)
                    return result
                except Exception as exc:  # noqa: BLE001 — retry then queue
                    last_error = str(exc)
                    ALERT_SEND_FAILURES.labels(reason=type(exc).__name__).inc()
                    log.warning(
                        "alerts.ntfy_send_failed",
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
            "alerts.ntfy_queued",
            trace_id=request.trace_id,
            alert_id=alert_id,
            attempts=attempts,
            error=last_error,
        )
        result = AlertResult(
            alert_id=alert_id,
            sent=False,
            queued=True,
            channel="ntfy",
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

    def _build_payload(self, request: AlertRequest, alert_id: str) -> dict:
        """Build the ntfy JSON publish body (UTF-8, carries Hebrew cleanly)."""
        icon = _SEVERITY_ICON.get(request.severity, "🔔")
        title = f"{icon} Shomer.AI — {request.child_name}".strip()
        payload: dict = {
            "topic": self._topic,
            "title": title,
            "message": request.explanation or request.quote,
            "priority": _NTFY_PRIORITY.get(request.severity, 3),
            "tags": [request.label, request.severity],
        }
        if self._click_url:
            payload["click"] = self._click_url
        return payload

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


def _extract_message_id(resp: httpx.Response) -> str | None:
    """ntfy returns the published message as JSON with an ``id`` field."""
    try:
        return resp.json().get("id")
    except Exception:  # noqa: BLE001 — id is best-effort metadata
        return None


def _elapsed_ms(started: float) -> int:
    """Return elapsed wall-clock milliseconds since ``started``."""
    return int((time.monotonic() - started) * 1000)
