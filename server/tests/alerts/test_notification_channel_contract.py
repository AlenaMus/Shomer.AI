"""NotificationChannel Protocol contract tests.

Reference: docs/design/alerts/design.md §2.5 (NotificationChannel Protocol),
           docs/design/README.md §5 (contract-test convention).

Parametrized over ``LogNotifier`` and ``StubNotifier`` (NOT ``FcmNotifier`` —
it is in a separate test file because it is a backlog skeleton).

Contract invariants (every adapter MUST satisfy):
(a) ``send_alert()`` NEVER raises. Failures appear as
    ``AlertResult(sent=False, ...)``.
(b) Idempotency: the same ``AlertRequest`` inputs always produce the same
    ``alert_id``, regardless of call count.
(c) ``health_status()`` returns a dict with exactly the documented keys
    (``"status"`` in {``"ok"``, ``"degraded"``} and ``"queued_alerts"`` >= 0).
(d) ``send_alert()`` returns an ``AlertResult`` with all required fields.
(e) ``isinstance(adapter, NotificationChannel)`` is True (runtime_checkable).
"""

from __future__ import annotations

import pytest

from app.alerts import (
    AlertSettings,
    InMemoryAlertRateLimiter,
    LogNotifier,
    NotificationChannel,
    NoOpAlertRateLimiter,
    StubNotifier,
)
from app.schemas import AlertRequest, AlertResult


# ---------------------------------------------------------------------------
# Adapter builders
# ---------------------------------------------------------------------------


def _build_log_notifier() -> LogNotifier:
    settings = AlertSettings(
        rate_limit_max_alerts=3,
        rate_limit_window_seconds=60,
    )
    return LogNotifier(settings=settings, rate_limiter=NoOpAlertRateLimiter())


def _build_stub_notifier() -> StubNotifier:
    return StubNotifier()


ADAPTER_BUILDERS = {
    "LogNotifier": _build_log_notifier,
    "StubNotifier": _build_stub_notifier,
}


@pytest.fixture(params=list(ADAPTER_BUILDERS.keys()))
def adapter(request: pytest.FixtureRequest) -> NotificationChannel:
    return ADAPTER_BUILDERS[request.param]()


@pytest.fixture
def base_request() -> AlertRequest:
    return AlertRequest(
        child_id="child-contract-001",
        message_id="msg-contract-abc",
        label="hate",
        severity="medium",
        explanation="Hateful content detected.",
        quote="...",
        source="context_agent",
        trace_id="trace-contract-xyz",
    )


# ---------------------------------------------------------------------------
# (e) runtime_checkable isinstance check
# ---------------------------------------------------------------------------


def test_isinstance_notification_channel(adapter: NotificationChannel) -> None:
    """Every adapter satisfies isinstance(adapter, NotificationChannel)."""
    assert isinstance(adapter, NotificationChannel), (
        f"{type(adapter).__name__} is not a NotificationChannel"
    )


# ---------------------------------------------------------------------------
# (a) send_alert() never raises
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_alert_never_raises_on_happy_path(
    adapter: NotificationChannel,
    base_request: AlertRequest,
) -> None:
    """send_alert() returns an AlertResult even on a normal call."""
    result = await adapter.send_alert(base_request)
    assert isinstance(result, AlertResult)


@pytest.mark.asyncio
async def test_send_alert_never_raises_on_stub_failure() -> None:
    """StubNotifier(fail=True) returns AlertResult(sent=False) without raising."""
    failing_stub = StubNotifier(fail=True)
    req = AlertRequest(
        child_id="c",
        message_id="m",
        label="violence",
        severity="critical",
        explanation="x",
        quote="",
        source="frontline_direct",
        trace_id="t",
    )
    result = await failing_stub.send_alert(req)
    assert isinstance(result, AlertResult)
    assert result.sent is False
    assert result.error is not None


# ---------------------------------------------------------------------------
# (b) Idempotency — same request → same alert_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_idempotent_alert_id(
    adapter: NotificationChannel,
    base_request: AlertRequest,
) -> None:
    """Same AlertRequest inputs always produce the same alert_id."""
    result1 = await adapter.send_alert(base_request)
    result2 = await adapter.send_alert(base_request)
    assert result1.alert_id == result2.alert_id, (
        "alert_id must be deterministic for the same input"
    )


@pytest.mark.asyncio
async def test_alert_id_differs_for_different_message_id(
    adapter: NotificationChannel,
) -> None:
    """Different message_ids produce different alert_ids."""
    req_a = AlertRequest(
        child_id="child-x",
        message_id="msg-1",
        label="abusive",
        severity="medium",
        explanation="test",
        quote="",
        source="frontline_direct",
        trace_id="t",
    )
    req_b = req_a.model_copy(update={"message_id": "msg-2"})
    r1 = await adapter.send_alert(req_a)
    r2 = await adapter.send_alert(req_b)
    assert r1.alert_id != r2.alert_id


# ---------------------------------------------------------------------------
# (c) health_status() schema
# ---------------------------------------------------------------------------


def test_health_status_schema(adapter: NotificationChannel) -> None:
    """health_status() returns the documented dict shape."""
    h = adapter.health_status()
    assert isinstance(h, dict), "health_status() must return a dict"
    assert "status" in h, "missing key: 'status'"
    assert "queued_alerts" in h, "missing key: 'queued_alerts'"
    assert h["status"] in ("ok", "degraded"), (
        f"'status' must be 'ok' or 'degraded', got {h['status']!r}"
    )
    assert isinstance(h["queued_alerts"], int) and h["queued_alerts"] >= 0, (
        "'queued_alerts' must be a non-negative int"
    )


# ---------------------------------------------------------------------------
# (d) AlertResult field completeness
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_result_has_required_fields(
    adapter: NotificationChannel,
    base_request: AlertRequest,
) -> None:
    """send_alert() returns an AlertResult with all required fields populated."""
    result = await adapter.send_alert(base_request)
    assert result.alert_id, "alert_id must be non-empty"
    assert isinstance(result.sent, bool)
    assert isinstance(result.queued, bool)
    assert isinstance(result.rate_limited, bool)
    assert isinstance(result.latency_ms, int)
    assert result.latency_ms >= 0
    assert result.channel, "channel must be non-empty"
    assert result.timestamp is not None
