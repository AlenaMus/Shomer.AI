"""Public ports for the Alerts module.

Reference: docs/design/alerts/design.md §2, §2.5.

Two Protocols:
- ``NotificationChannel`` — delivery port (how the push is sent).
- ``AlertRateLimiter``    — anti-storm guard port (when a push is allowed).

Separating them lets the channel (FCM, SMS, log-line) and the rate limiter
(in-memory deque, Redis) evolve independently.  Both are swapped in
``server/app/main.py`` ``lifespan()`` — never here.

Concrete adapters for NotificationChannel:
    LogNotifier    (default, no Firebase setup required)
    StubNotifier   (tests)
    FcmNotifier    (real FCM delivery; opt-in via ALERTS_CHANNEL=fcm)

Concrete adapters for AlertRateLimiter:
    InMemoryAlertRateLimiter  (default, sliding-window deque)
    NoOpAlertRateLimiter      (load-test / diagnostic mode)
    StubAlertRateLimiter      (tests)
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..schemas import AlertRequest, AlertResult


@runtime_checkable
class NotificationChannel(Protocol):
    """Send an alert push notification to a parent device.

    Contract (every adapter MUST satisfy):
    - ``send_alert()`` NEVER raises. Any failure is captured in
      ``AlertResult(sent=False, error=str(exc))``.
    - Idempotency: same ``AlertRequest`` inputs produce the same
      ``alert_id`` regardless of how many times ``send_alert`` is called.
      Adapters that communicate with an external service MUST NOT duplicate
      delivery for the same ``alert_id``.
    - ``get_alert_history()`` returns ``[]`` when the adapter does not
      persist history (e.g. ``LogNotifier``).  Phase B wires a real
      AuditStore query here.
    - ``health_status()`` is synchronous and fast (no I/O) — it reflects
      the adapter's internal state (queue depth, reachability).
    """

    async def send_alert(self, request: AlertRequest) -> AlertResult:
        """Send the alert. Never raises — failures captured in AlertResult."""
        ...

    async def get_alert_history(
        self,
        child_id: str,
        limit: int = 50,
    ) -> list[AlertResult]:
        """Return recent alerts for a child.

        Default implementation returns ``[]``.  Real history comes from the
        AuditStore once Phase B wires ``SqliteAuditStore``.
        """
        ...

    def health_status(self) -> dict:
        """Return ``{'status': 'ok'|'degraded', 'queued_alerts': int}``.

        Called by the ``/health`` rollup (Phase B wiring).
        Must not perform I/O.
        """
        ...


@runtime_checkable
class AlertRateLimiter(Protocol):
    """Anti-storm guard — decides whether a new alert for a key is permitted.

    Contract:
    - ``allow()`` is thread-safe.
    - ``allow()`` returns ``True`` when a new alert is permitted under the
      configured sliding-window budget for ``key`` (typically ``child_id``).
    - ``allow()`` returns ``False`` when the budget is exhausted; the call
      is a pure check — it does NOT consume a slot.  Only a ``True`` return
      consumes a slot.
    """

    def allow(self, key: str) -> bool:
        """True if a new alert for ``key`` is permitted; False if suppressed."""
        ...
