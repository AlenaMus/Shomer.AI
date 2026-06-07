"""Tests for FcmNotifier (the backlog skeleton).

Reference: docs/design/alerts/design.md §3, backlog task M6-ALERTS-FCM.

These tests verify that the FcmNotifier skeleton:
(a) Is importable without ``firebase-admin`` installed.
(b) Returns the documented "not enabled" AlertResult without raising when
    ``firebase-admin`` is not installed or no credentials are configured.
(c) Satisfies isinstance(adapter, NotificationChannel).
(d) health_status() returns the documented schema.
"""

from __future__ import annotations

import os

import pytest

from app.alerts import (
    AlertSettings,
    FcmNotifier,
    LocalRetryQueue,
    NoOpAlertRateLimiter,
    NotificationChannel,
)
from app.schemas import AlertRequest, AlertResult


def _make_fcm_notifier(retry_queue: LocalRetryQueue | None = None) -> FcmNotifier:
    settings = AlertSettings()
    return FcmNotifier(
        settings=settings,
        rate_limiter=NoOpAlertRateLimiter(),
        retry_queue=retry_queue,
    )


def _make_request() -> AlertRequest:
    return AlertRequest(
        child_id="child-fcm-001",
        message_id="msg-fcm-abc",
        label="pornographic",
        severity="high",
        explanation="Pornographic content detected.",
        quote="...",
        source="context_agent",
        trace_id="trace-fcm-xyz",
        parent_fcm_token="fake-fcm-token-for-testing",
        child_name="Test Child",
    )


# ---------------------------------------------------------------------------
# (a) Importable without firebase-admin
# ---------------------------------------------------------------------------


def test_fcm_notifier_importable() -> None:
    """FcmNotifier can be imported even without firebase-admin installed."""
    # If we got here without ImportError, the import is safe.
    assert FcmNotifier is not None


# ---------------------------------------------------------------------------
# (c) isinstance check
# ---------------------------------------------------------------------------


def test_fcm_notifier_is_notification_channel() -> None:
    """FcmNotifier satisfies isinstance(adapter, NotificationChannel)."""
    notifier = _make_fcm_notifier()
    assert isinstance(notifier, NotificationChannel)


# ---------------------------------------------------------------------------
# (b) Returns "not enabled" result without raising
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fcm_notifier_returns_not_enabled_result_when_no_firebase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When firebase-admin is unavailable or creds are absent, returns 'not enabled'."""
    # Ensure FCM_SERVICE_ACCOUNT_PATH is not set.
    monkeypatch.delenv("FCM_SERVICE_ACCOUNT_PATH", raising=False)

    notifier = _make_fcm_notifier()
    req = _make_request()

    # Must NOT raise.
    result = await notifier.send_alert(req)

    assert isinstance(result, AlertResult)
    assert result.sent is False
    assert result.channel == "fcm"
    assert result.error is not None
    assert "M6-ALERTS-FCM" in result.error, (
        f"Expected 'M6-ALERTS-FCM' in error message, got: {result.error!r}"
    )


@pytest.mark.asyncio
async def test_fcm_notifier_never_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """send_alert() on the skeleton NEVER raises, regardless of environment."""
    monkeypatch.delenv("FCM_SERVICE_ACCOUNT_PATH", raising=False)
    notifier = _make_fcm_notifier()

    try:
        result = await notifier.send_alert(_make_request())
    except Exception as exc:
        pytest.fail(f"send_alert() raised unexpectedly: {exc!r}")

    assert isinstance(result, AlertResult)


@pytest.mark.asyncio
async def test_fcm_notifier_get_history_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """get_alert_history() returns [] (no local persistence in skeleton)."""
    monkeypatch.delenv("FCM_SERVICE_ACCOUNT_PATH", raising=False)
    notifier = _make_fcm_notifier()
    history = await notifier.get_alert_history("child-fcm-001")
    assert history == []


# ---------------------------------------------------------------------------
# (d) health_status() schema
# ---------------------------------------------------------------------------


def test_fcm_health_status_schema_without_queue() -> None:
    """health_status() returns the documented dict when no retry queue."""
    notifier = _make_fcm_notifier()
    h = notifier.health_status()
    assert isinstance(h, dict)
    assert h["status"] in ("ok", "degraded")
    assert isinstance(h["queued_alerts"], int)
    assert h["queued_alerts"] >= 0


def test_fcm_health_status_reflects_queue_depth() -> None:
    """health_status() shows 'degraded' when the retry queue has items."""
    q = LocalRetryQueue(max_size=5)
    req = AlertRequest(
        child_id="c",
        message_id="m",
        label="hate",
        severity="low",
        explanation="x",
        quote="",
        source="frontline_direct",
        trace_id="t",
    )
    q.enqueue(req)
    notifier = _make_fcm_notifier(retry_queue=q)
    h = notifier.health_status()
    assert h["status"] == "degraded"
    assert h["queued_alerts"] == 1
