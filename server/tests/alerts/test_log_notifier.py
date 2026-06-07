"""Unit tests for LogNotifier.

Reference: docs/design/alerts/design.md §2.5 (LogNotifier spec).

Tests:
- Happy path returns AlertResult(sent=True, channel="log").
- Rate-limited path returns AlertResult(sent=False, rate_limited=True).
- Injected audit_recorder is awaited exactly once.
- A raising audit_recorder does NOT bubble up to the caller.
- health_status() reflects retry-queue depth.
- alert_id is deterministic (idempotency key).
"""

from __future__ import annotations

import pytest

from app.alerts import (
    AlertSettings,
    InMemoryAlertRateLimiter,
    LocalRetryQueue,
    LogNotifier,
    NoOpAlertRateLimiter,
    StubAlertRateLimiter,
    compute_alert_id,
)
from app.schemas import AlertRequest, AlertResult


def _make_request(**overrides) -> AlertRequest:
    defaults = dict(
        child_id="child-log-001",
        message_id="msg-log-abc",
        label="violence",
        severity="high",
        explanation="Violent content detected.",
        quote="...",
        source="frontline_direct",
        trace_id="trace-log-xyz",
    )
    defaults.update(overrides)
    return AlertRequest(**defaults)


def _make_notifier(
    rate_limiter=None,
    retry_queue=None,
    audit_recorder=None,
) -> LogNotifier:
    settings = AlertSettings(
        rate_limit_max_alerts=3,
        rate_limit_window_seconds=60,
    )
    if rate_limiter is None:
        rate_limiter = NoOpAlertRateLimiter()
    return LogNotifier(
        settings=settings,
        rate_limiter=rate_limiter,
        retry_queue=retry_queue,
        audit_recorder=audit_recorder,
    )


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_happy_path_returns_sent_true() -> None:
    """Happy-path call returns AlertResult(sent=True, channel='log')."""
    notifier = _make_notifier()
    req = _make_request()
    result = await notifier.send_alert(req)

    assert result.sent is True
    assert result.channel == "log"
    assert result.rate_limited is False
    assert result.queued is False
    assert result.error is None
    assert result.fcm_message_id is None


@pytest.mark.asyncio
async def test_alert_id_matches_compute_helper() -> None:
    """alert_id in result equals compute_alert_id(request)."""
    notifier = _make_notifier()
    req = _make_request()
    result = await notifier.send_alert(req)
    assert result.alert_id == compute_alert_id(req)


@pytest.mark.asyncio
async def test_latency_ms_is_non_negative() -> None:
    """latency_ms is always a non-negative int."""
    notifier = _make_notifier()
    result = await notifier.send_alert(_make_request())
    assert isinstance(result.latency_ms, int)
    assert result.latency_ms >= 0


# ---------------------------------------------------------------------------
# Rate-limited path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rate_limited_returns_sent_false() -> None:
    """When rate limiter denies the call, result has sent=False, rate_limited=True."""
    stub_rl = StubAlertRateLimiter(always_allow=False)
    notifier = _make_notifier(rate_limiter=stub_rl)
    result = await notifier.send_alert(_make_request())

    assert result.sent is False
    assert result.rate_limited is True
    assert result.error is None


@pytest.mark.asyncio
async def test_rate_limited_after_n_calls() -> None:
    """After max_alerts calls, the in-memory rate limiter kicks in."""
    rl = InMemoryAlertRateLimiter(max_alerts=2, window_seconds=60)
    notifier = _make_notifier(rate_limiter=rl)
    req = _make_request()

    r1 = await notifier.send_alert(req)
    r2 = await notifier.send_alert(req)
    r3 = await notifier.send_alert(req)

    assert r1.sent is True
    assert r2.sent is True
    assert r3.sent is False
    assert r3.rate_limited is True


# ---------------------------------------------------------------------------
# audit_recorder injection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_audit_recorder_is_awaited() -> None:
    """Injected audit_recorder is called with (request, result)."""
    calls: list[tuple] = []

    async def recorder(req: AlertRequest, res: AlertResult) -> None:
        calls.append((req, res))

    notifier = _make_notifier(audit_recorder=recorder)
    req = _make_request()
    await notifier.send_alert(req)

    assert len(calls) == 1
    recorded_req, recorded_res = calls[0]
    assert recorded_req is req
    assert recorded_res.sent is True


@pytest.mark.asyncio
async def test_rate_limited_path_also_calls_audit_recorder() -> None:
    """audit_recorder is called even when the alert is rate-limited."""
    calls: list[tuple] = []

    async def recorder(req: AlertRequest, res: AlertResult) -> None:
        calls.append((req, res))

    stub_rl = StubAlertRateLimiter(always_allow=False)
    notifier = _make_notifier(rate_limiter=stub_rl, audit_recorder=recorder)
    await notifier.send_alert(_make_request())

    assert len(calls) == 1
    _, res = calls[0]
    assert res.rate_limited is True


@pytest.mark.asyncio
async def test_raising_audit_recorder_does_not_bubble_up() -> None:
    """A recorder that raises must NOT cause send_alert() to raise."""
    async def bad_recorder(req: AlertRequest, res: AlertResult) -> None:
        raise RuntimeError("recorder exploded")

    notifier = _make_notifier(audit_recorder=bad_recorder)
    # Must not raise — result should still be returned normally.
    result = await notifier.send_alert(_make_request())
    assert isinstance(result, AlertResult)
    assert result.sent is True  # happy path completed before recorder failed


# ---------------------------------------------------------------------------
# health_status() with retry queue
# ---------------------------------------------------------------------------


def test_health_status_ok_when_queue_empty() -> None:
    """health_status returns 'ok' when the retry queue is empty."""
    q = LocalRetryQueue(max_size=10)
    notifier = _make_notifier(retry_queue=q)
    h = notifier.health_status()
    assert h["status"] == "ok"
    assert h["queued_alerts"] == 0


def test_health_status_degraded_when_queue_has_items() -> None:
    """health_status returns 'degraded' when the retry queue has items."""
    q = LocalRetryQueue(max_size=10)
    q.enqueue(_make_request())
    notifier = _make_notifier(retry_queue=q)
    h = notifier.health_status()
    assert h["status"] == "degraded"
    assert h["queued_alerts"] == 1


def test_health_status_ok_without_queue() -> None:
    """health_status returns 'ok' when no retry queue is injected."""
    notifier = _make_notifier()
    h = notifier.health_status()
    assert h["status"] == "ok"
    assert h["queued_alerts"] == 0


# ---------------------------------------------------------------------------
# get_alert_history() returns []
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_alert_history_returns_empty_list() -> None:
    """LogNotifier.get_alert_history() returns [] (no local persistence)."""
    notifier = _make_notifier()
    history = await notifier.get_alert_history("child-log-001")
    assert history == []
