"""StubNotifier — in-memory NotificationChannel adapter for tests.

Reference: docs/design/alerts/design.md §2.5 (NotificationChannel Protocol).

``StubNotifier`` records every ``send_alert()`` call in an internal list and
returns it via ``get_alert_history()``.  It NEVER raises, requires no network,
and has no rate-limiting — making it ideal for contract tests and integration
tests that need to assert on the full call history.

To simulate failures, construct with ``fail=True``: every call returns
``AlertResult(sent=False, error="stub_forced_failure")``.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from ..schemas import AlertRequest, AlertResult
from .log_notifier import compute_alert_id


class StubNotifier:
    """Records all send_alert() calls in memory.  Used by tests only.

    Parameters
    ----------
    fail:
        When ``True`` every ``send_alert()`` returns a failed ``AlertResult``
        with ``error="stub_forced_failure"``.  Useful for testing callers'
        error-handling paths.
    """

    def __init__(self, fail: bool = False) -> None:
        self._fail = fail
        self._history: list[AlertResult] = []
        self.requests: list[AlertRequest] = []  # raw inputs for assertion

    # ------------------------------------------------------------------
    # NotificationChannel Protocol
    # ------------------------------------------------------------------

    async def send_alert(self, request: AlertRequest) -> AlertResult:
        """Record the call and return a result.  NEVER raises."""
        started = time.monotonic()
        alert_id = compute_alert_id(request)
        latency_ms = int((time.monotonic() - started) * 1000)

        self.requests.append(request)

        if self._fail:
            result = AlertResult(
                alert_id=alert_id,
                sent=False,
                channel="stub",
                error="stub_forced_failure",
                latency_ms=latency_ms,
                timestamp=datetime.now(timezone.utc),
            )
        else:
            result = AlertResult(
                alert_id=alert_id,
                sent=True,
                channel="stub",
                fcm_message_id=None,
                latency_ms=latency_ms,
                timestamp=datetime.now(timezone.utc),
            )

        self._history.append(result)
        return result

    async def get_alert_history(
        self,
        child_id: str,  # noqa: ARG002
        limit: int = 50,
    ) -> list[AlertResult]:
        """Return recorded results (most recent last, up to ``limit``)."""
        return self._history[-limit:]

    def health_status(self) -> dict:
        """Always healthy — stubs don't have external dependencies."""
        return {"status": "ok", "queued_alerts": 0}
