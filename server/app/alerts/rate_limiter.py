"""Rate-limiter adapters for the Alerts module.

Reference: docs/design/alerts/design.md §2.5 (AlertRateLimiter Protocol),
           §3 (Rate Limiter internal design).

Three adapters:
- ``InMemoryAlertRateLimiter`` — sliding-window deque, thread-safe (default).
- ``NoOpAlertRateLimiter``     — always returns True (load-test / diagnostic).
- ``StubAlertRateLimiter``     — configurable for tests.

All three satisfy the ``AlertRateLimiter`` Protocol defined in ``protocol.py``.
"""

from __future__ import annotations

import time
from collections import deque
from threading import Lock


class InMemoryAlertRateLimiter:
    """Sliding-window rate limiter keyed by an arbitrary string (child_id).

    Thread-safe via an internal ``threading.Lock``.

    Algorithm
    ---------
    Each key maps to a ``deque`` of monotonic timestamps (``time.monotonic()``).
    On every ``allow()`` call:
    1. Evict timestamps older than ``window_seconds`` from the left end.
    2. If ``len(deque) >= max_alerts``: return ``False`` (suppress).
    3. Otherwise: append the current timestamp and return ``True`` (permit).

    Memory is O(max_alerts × number_of_active_keys) — trivial at MVP scale.

    Parameters
    ----------
    max_alerts:
        Maximum number of alerts allowed within the sliding window per key.
    window_seconds:
        Sliding-window duration in seconds.
    """

    def __init__(
        self,
        max_alerts: int = 3,
        window_seconds: int = 60,
    ) -> None:
        self._max = max_alerts
        self._window = window_seconds
        self._windows: dict[str, deque[float]] = {}
        self._lock = Lock()

    def allow(self, key: str) -> bool:
        """Return ``True`` and consume a slot; ``False`` if budget exhausted."""
        now = time.monotonic()
        with self._lock:
            dq = self._windows.setdefault(key, deque())
            # Evict expired timestamps from the left end.
            while dq and now - dq[0] > self._window:
                dq.popleft()
            if len(dq) >= self._max:
                return False
            dq.append(now)
            return True


class NoOpAlertRateLimiter:
    """Rate limiter that always permits — intended for load-test / diagnostic mode.

    In production, wire ``InMemoryAlertRateLimiter`` instead.
    """

    def allow(self, key: str) -> bool:  # noqa: ARG002
        """Always returns ``True``; no slot is consumed."""
        return True


class StubAlertRateLimiter:
    """Configurable rate limiter for tests.

    Parameters
    ----------
    always_allow:
        When ``True`` (default) every call returns ``True``.
        Set to ``False`` to simulate a fully exhausted budget.
    """

    def __init__(self, always_allow: bool = True) -> None:
        self._allow = always_allow
        # Track calls for assertion in tests.
        self.calls: list[str] = []

    def allow(self, key: str) -> bool:
        """Return the configured value and record the call for test assertion."""
        self.calls.append(key)
        return self._allow
