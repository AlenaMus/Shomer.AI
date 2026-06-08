"""Tests for NtfyNotifier (free push via ntfy.sh).

Mocks the HTTP transport with ``respx`` — no real ntfy server is contacted.
Covers: not-configured degradation, successful publish + JSON payload shape
(incl. Hebrew + auth header), retry→queue on failure, rate-limit short-circuit,
never-raises on transport error, and the health schema.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from app.alerts import (
    AlertSettings,
    LocalRetryQueue,
    NoOpAlertRateLimiter,
    NotificationChannel,
    NtfyNotifier,
)
from app.schemas import AlertRequest, AlertResult

NTFY_URL = "https://ntfy.sh"


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _settings(**overrides) -> AlertSettings:
    base = dict(
        channel="ntfy",
        ntfy_topic="shomer-test-topic-7f3k",
        max_retry_attempts=3,
        retry_base_seconds=0.0,  # keep retry tests instant
    )
    base.update(overrides)
    return AlertSettings(**base)


def _make(
    *,
    settings: AlertSettings | None = None,
    rate_limiter=None,
    retry_queue: LocalRetryQueue | None = None,
    audit_recorder=None,
) -> NtfyNotifier:
    return NtfyNotifier(
        settings or _settings(),
        rate_limiter or NoOpAlertRateLimiter(),
        retry_queue,
        audit_recorder,
    )


def _request(**overrides) -> AlertRequest:
    base = dict(
        child_id="child-1",
        message_id="m1",
        label="hate",
        severity="high",
        explanation="תוכן פוגעני זוהה בשיחה",  # Hebrew → must survive as UTF-8
        quote="...",
        source="context_agent",
        trace_id="t1",
        child_name="ילד",
    )
    base.update(overrides)
    return AlertRequest(**base)


class _DenyRateLimiter:
    def allow(self, key: str) -> bool:  # noqa: ARG002
        return False


# ---------------------------------------------------------------------------
# Conformance + not-configured
# ---------------------------------------------------------------------------


def test_is_notification_channel() -> None:
    assert isinstance(_make(), NotificationChannel)


@pytest.mark.asyncio
async def test_not_configured_when_topic_missing() -> None:
    """No topic → sent=False, never raises, no HTTP call."""
    notifier = _make(settings=_settings(ntfy_topic=""))
    async with respx.mock(assert_all_called=False):
        result = await notifier.send_alert(_request())
    assert isinstance(result, AlertResult)
    assert result.sent is False
    assert result.channel == "ntfy"
    assert "not configured" in (result.error or "")


# ---------------------------------------------------------------------------
# Success path + payload shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_success_publishes_and_returns_message_id() -> None:
    notifier = _make()
    async with respx.mock(assert_all_called=True) as router:
        route = router.post(NTFY_URL).mock(
            return_value=httpx.Response(200, json={"id": "nt-abc-1"})
        )
        result = await notifier.send_alert(_request())

    assert result.sent is True
    assert result.channel == "ntfy"
    assert result.fcm_message_id == "nt-abc-1"
    assert result.queued is False

    # Payload is JSON (UTF-8 → Hebrew preserved) with the documented fields.
    body = json.loads(route.calls.last.request.content)
    assert body["topic"] == "shomer-test-topic-7f3k"
    assert "Shomer.AI" in body["title"]
    assert "ילד" in body["title"]
    assert body["message"] == "תוכן פוגעני זוהה בשיחה"
    assert body["priority"] == 4  # high
    assert body["tags"] == ["hate", "high"]
    # No token configured → no Authorization header.
    assert "authorization" not in {
        k.lower() for k in route.calls.last.request.headers
    }


@pytest.mark.asyncio
async def test_click_url_and_token_included_when_set() -> None:
    notifier = _make(
        settings=_settings(
            ntfy_token="secret-123",
            ntfy_click_url="https://dash.example/alerts",
        )
    )
    async with respx.mock(assert_all_called=True) as router:
        route = router.post(NTFY_URL).mock(
            return_value=httpx.Response(200, json={"id": "x"})
        )
        await notifier.send_alert(_request())

    req = route.calls.last.request
    assert req.headers["authorization"] == "Bearer secret-123"
    assert json.loads(req.content)["click"] == "https://dash.example/alerts"


@pytest.mark.asyncio
async def test_priority_maps_low_severity() -> None:
    notifier = _make()
    async with respx.mock(assert_all_called=True) as router:
        route = router.post(NTFY_URL).mock(
            return_value=httpx.Response(200, json={"id": "x"})
        )
        await notifier.send_alert(_request(severity="low"))
    assert json.loads(route.calls.last.request.content)["priority"] == 2


# ---------------------------------------------------------------------------
# Failure handling — retry → queue, rate-limit, never-raises
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retries_then_queues_on_5xx() -> None:
    q = LocalRetryQueue(max_size=5)
    notifier = _make(retry_queue=q)
    async with respx.mock(assert_all_called=True) as router:
        route = router.post(NTFY_URL).mock(return_value=httpx.Response(503))
        result = await notifier.send_alert(_request())

    assert route.call_count == 3  # max_retry_attempts
    assert result.sent is False
    assert result.queued is True
    assert q.size() == 1


@pytest.mark.asyncio
async def test_transport_error_never_raises_and_queues() -> None:
    q = LocalRetryQueue(max_size=5)
    notifier = _make(retry_queue=q)
    async with respx.mock(assert_all_called=True) as router:
        router.post(NTFY_URL).mock(side_effect=httpx.ConnectError("boom"))
        result = await notifier.send_alert(_request())

    assert isinstance(result, AlertResult)
    assert result.sent is False
    assert result.queued is True
    assert q.size() == 1


@pytest.mark.asyncio
async def test_rate_limited_short_circuits_before_http() -> None:
    notifier = _make(rate_limiter=_DenyRateLimiter())
    async with respx.mock(assert_all_called=False) as router:
        route = router.post(NTFY_URL).mock(
            return_value=httpx.Response(200, json={"id": "x"})
        )
        result = await notifier.send_alert(_request())
    assert result.rate_limited is True
    assert result.sent is False
    assert route.call_count == 0


@pytest.mark.asyncio
async def test_audit_recorder_invoked_and_failure_swallowed() -> None:
    recorded: list[AlertResult] = []

    async def recorder(req: AlertRequest, res: AlertResult) -> None:  # noqa: ARG001
        recorded.append(res)
        raise RuntimeError("audit down")  # must be swallowed

    notifier = _make(audit_recorder=recorder)
    async with respx.mock(assert_all_called=True) as router:
        router.post(NTFY_URL).mock(
            return_value=httpx.Response(200, json={"id": "x"})
        )
        result = await notifier.send_alert(_request())

    assert result.sent is True
    assert len(recorded) == 1


@pytest.mark.asyncio
async def test_top_level_exception_is_captured() -> None:
    """An unexpected internal error (limiter raises) → AlertResult, not crash."""

    class _BoomLimiter:
        def allow(self, key: str) -> bool:  # noqa: ARG002
            raise RuntimeError("limiter exploded")

    notifier = _make(rate_limiter=_BoomLimiter())
    async with respx.mock(assert_all_called=False):
        result = await notifier.send_alert(_request())
    assert isinstance(result, AlertResult)
    assert result.sent is False
    assert result.error is not None


@pytest.mark.asyncio
async def test_success_with_non_json_body_returns_no_message_id() -> None:
    """A 200 with a non-JSON body still succeeds; message id is just None."""
    notifier = _make()
    async with respx.mock(assert_all_called=True) as router:
        router.post(NTFY_URL).mock(return_value=httpx.Response(200, text="ok"))
        result = await notifier.send_alert(_request())
    assert result.sent is True
    assert result.fcm_message_id is None


@pytest.mark.asyncio
async def test_get_alert_history_returns_empty() -> None:
    assert await _make().get_alert_history("child-1") == []


# ---------------------------------------------------------------------------
# health_status()
# ---------------------------------------------------------------------------


def test_health_status_schema_and_queue_depth() -> None:
    assert _make().health_status() == {"status": "ok", "queued_alerts": 0}

    q = LocalRetryQueue(max_size=5)
    q.enqueue(_request())
    h = _make(retry_queue=q).health_status()
    assert h["status"] == "degraded"
    assert h["queued_alerts"] == 1
