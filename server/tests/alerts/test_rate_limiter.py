"""Tests for AlertRateLimiter adapters.

Reference: docs/design/alerts/design.md §2.5 (AlertRateLimiter Protocol), §3.

Tests:
- InMemoryAlertRateLimiter allows first max_alerts calls per key, denies after.
- Per-key isolation: one child's limit does not affect another's.
- Window reset: after the window elapses, the budget refills.
- NoOpAlertRateLimiter always returns True.
- StubAlertRateLimiter respects its configured always_allow flag.
- Thread-safety: concurrent allow() calls do not over-permit.
"""

from __future__ import annotations

import time
import threading

import pytest

from app.alerts import (
    AlertRateLimiter,
    InMemoryAlertRateLimiter,
    NoOpAlertRateLimiter,
    StubAlertRateLimiter,
)


# ---------------------------------------------------------------------------
# InMemoryAlertRateLimiter — basic allow / deny
# ---------------------------------------------------------------------------


def test_allows_first_n_then_denies() -> None:
    """True for first max_alerts; False for subsequent calls within window."""
    rl = InMemoryAlertRateLimiter(max_alerts=3, window_seconds=60)
    assert rl.allow("child-a") is True
    assert rl.allow("child-a") is True
    assert rl.allow("child-a") is True
    assert rl.allow("child-a") is False   # 4th call exceeds budget
    assert rl.allow("child-a") is False   # 5th call still denied


def test_denies_immediately_when_max_is_zero() -> None:
    """max_alerts=0 means all calls are denied immediately."""
    rl = InMemoryAlertRateLimiter(max_alerts=0, window_seconds=60)
    assert rl.allow("child-x") is False


def test_max_alerts_one() -> None:
    """max_alerts=1: first call allowed, second denied."""
    rl = InMemoryAlertRateLimiter(max_alerts=1, window_seconds=60)
    assert rl.allow("child-b") is True
    assert rl.allow("child-b") is False


# ---------------------------------------------------------------------------
# Per-key isolation
# ---------------------------------------------------------------------------


def test_per_key_isolation() -> None:
    """One child's budget being exhausted does not affect another child."""
    rl = InMemoryAlertRateLimiter(max_alerts=2, window_seconds=60)

    # Exhaust budget for child-a.
    assert rl.allow("child-a") is True
    assert rl.allow("child-a") is True
    assert rl.allow("child-a") is False   # exhausted

    # child-b still has its own fresh budget.
    assert rl.allow("child-b") is True
    assert rl.allow("child-b") is True
    assert rl.allow("child-b") is False   # child-b exhausted too


def test_many_keys_do_not_interfere() -> None:
    """Many independent keys each get their own sliding window."""
    rl = InMemoryAlertRateLimiter(max_alerts=1, window_seconds=60)
    keys = [f"child-{i}" for i in range(20)]
    for key in keys:
        assert rl.allow(key) is True, f"Expected True for first call on {key}"
    for key in keys:
        assert rl.allow(key) is False, f"Expected False for second call on {key}"


# ---------------------------------------------------------------------------
# Window reset
# ---------------------------------------------------------------------------


def test_window_reset_after_expiry() -> None:
    """After window_seconds elapses, the budget refills (old timestamps evicted)."""
    rl = InMemoryAlertRateLimiter(max_alerts=2, window_seconds=1)

    assert rl.allow("child-c") is True
    assert rl.allow("child-c") is True
    assert rl.allow("child-c") is False   # budget exhausted

    # Wait for the 1-second window to expire.
    time.sleep(1.1)

    # Budget should be fully reset.
    assert rl.allow("child-c") is True
    assert rl.allow("child-c") is True
    assert rl.allow("child-c") is False   # exhausted again


# ---------------------------------------------------------------------------
# Thread-safety
# ---------------------------------------------------------------------------


def test_thread_safety_does_not_over_permit() -> None:
    """Concurrent allow() calls do not exceed max_alerts due to race conditions."""
    max_alerts = 5
    rl = InMemoryAlertRateLimiter(max_alerts=max_alerts, window_seconds=60)
    results: list[bool] = []
    lock = threading.Lock()

    def call_allow() -> None:
        result = rl.allow("child-concurrent")
        with lock:
            results.append(result)

    threads = [threading.Thread(target=call_allow) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    allowed = sum(1 for r in results if r)
    denied = sum(1 for r in results if not r)

    assert allowed == max_alerts, (
        f"Expected exactly {max_alerts} allowed, got {allowed}"
    )
    assert denied == 20 - max_alerts


# ---------------------------------------------------------------------------
# NoOpAlertRateLimiter
# ---------------------------------------------------------------------------


def test_noop_always_allows() -> None:
    """NoOpAlertRateLimiter.allow() always returns True, for any key."""
    rl = NoOpAlertRateLimiter()
    for _ in range(100):
        assert rl.allow("any-key") is True


def test_noop_is_alert_rate_limiter() -> None:
    """NoOpAlertRateLimiter satisfies the AlertRateLimiter Protocol."""
    assert isinstance(NoOpAlertRateLimiter(), AlertRateLimiter)


# ---------------------------------------------------------------------------
# StubAlertRateLimiter
# ---------------------------------------------------------------------------


def test_stub_always_allow_true() -> None:
    """StubAlertRateLimiter(always_allow=True) always returns True."""
    stub = StubAlertRateLimiter(always_allow=True)
    assert stub.allow("child-x") is True
    assert stub.allow("child-x") is True


def test_stub_always_allow_false() -> None:
    """StubAlertRateLimiter(always_allow=False) always returns False."""
    stub = StubAlertRateLimiter(always_allow=False)
    assert stub.allow("child-x") is False
    assert stub.allow("child-x") is False


def test_stub_records_calls() -> None:
    """StubAlertRateLimiter records the key of each call for assertion."""
    stub = StubAlertRateLimiter(always_allow=True)
    stub.allow("child-a")
    stub.allow("child-b")
    assert stub.calls == ["child-a", "child-b"]
