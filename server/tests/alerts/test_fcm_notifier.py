"""Tests for FcmNotifier (real NotificationChannel adapter).

Reference: docs/design/alerts/design.md §3, backlog task M6-ALERTS-FCM.

Two test surfaces:
- **Not configured** (firebase-admin absent OR no creds): the adapter degrades
  to ``AlertResult(sent=False, error="FCM not configured: …")`` and never raises.
- **Configured** (an injected ``send_fn`` stands in for ``messaging.send`` so
  the rate-limit / retry / queue logic is exercised without real Firebase).
"""

from __future__ import annotations

import sys
import types

import pytest

from app.alerts import (
    AlertSettings,
    FcmNotifier,
    LocalRetryQueue,
    NoOpAlertRateLimiter,
    NotificationChannel,
)
from app.schemas import AlertRequest, AlertResult


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _make_request(**overrides) -> AlertRequest:
    base = dict(
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
    base.update(overrides)
    return AlertRequest(**base)


def _make_fcm(
    *,
    send_fn=None,
    rate_limiter=None,
    retry_queue: LocalRetryQueue | None = None,
    audit_recorder=None,
    settings: AlertSettings | None = None,
) -> FcmNotifier:
    return FcmNotifier(
        settings=settings or AlertSettings(),
        rate_limiter=rate_limiter or NoOpAlertRateLimiter(),
        retry_queue=retry_queue,
        audit_recorder=audit_recorder,
        send_fn=send_fn,
    )


class _DenyRateLimiter:
    """Rate limiter that always suppresses (for the rate-limited path)."""

    def allow(self, key: str) -> bool:  # noqa: ARG002
        return False


@pytest.fixture
def fake_firebase(monkeypatch: pytest.MonkeyPatch):
    """Install a stand-in ``firebase_admin`` so the real resolution + message
    build + send code runs without the heavy library or a Firebase project.

    Exposes ``.messaging._sent`` (list of built Messages) and ``.init_calls``
    so tests can assert on the payload and on idempotent app initialisation.
    """
    fb = types.ModuleType("firebase_admin")
    state: dict = {"apps": [], "init_calls": 0}

    def get_app():
        if not state["apps"]:
            raise ValueError("The default Firebase app does not exist.")
        return state["apps"][0]

    def initialize_app(cred=None):  # noqa: ARG001
        state["init_calls"] += 1
        app = object()
        state["apps"].append(app)
        return app

    fb.get_app = get_app
    fb.initialize_app = initialize_app
    fb.init_calls = lambda: state["init_calls"]

    creds = types.ModuleType("firebase_admin.credentials")
    creds.Certificate = lambda path: {"cred_path": path}
    fb.credentials = creds

    messaging = types.ModuleType("firebase_admin.messaging")
    sent: list = []

    class _Notification:
        def __init__(self, title=None, body=None):
            self.title, self.body = title, body

    class _AndroidNotification:
        def __init__(self, channel_id=None, priority=None):
            self.channel_id, self.priority = channel_id, priority

    class _AndroidConfig:
        def __init__(self, priority=None, notification=None):
            self.priority, self.notification = priority, notification

    class _Message:
        def __init__(self, notification=None, data=None, token=None, android=None):
            self.notification, self.data = notification, data
            self.token, self.android = token, android

    def _send(message):
        sent.append(message)
        return "fake-fcm-id-999"

    messaging.Notification = _Notification
    messaging.AndroidNotification = _AndroidNotification
    messaging.AndroidConfig = _AndroidConfig
    messaging.Message = _Message
    messaging.send = _send
    messaging._sent = sent
    fb.messaging = messaging

    monkeypatch.setitem(sys.modules, "firebase_admin", fb)
    monkeypatch.setitem(sys.modules, "firebase_admin.credentials", creds)
    monkeypatch.setitem(sys.modules, "firebase_admin.messaging", messaging)
    return fb


# ---------------------------------------------------------------------------
# Importability + Protocol conformance
# ---------------------------------------------------------------------------


def test_fcm_notifier_importable() -> None:
    """FcmNotifier imports even without firebase-admin installed."""
    assert FcmNotifier is not None


def test_fcm_notifier_is_notification_channel() -> None:
    notifier = _make_fcm()
    assert isinstance(notifier, NotificationChannel)


# ---------------------------------------------------------------------------
# Not-configured path (no injected send_fn, no creds)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_returns_not_configured_when_no_firebase_or_creds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """firebase-admin missing OR creds absent → sent=False, never raises."""
    monkeypatch.delenv("FCM_SERVICE_ACCOUNT_PATH", raising=False)
    notifier = _make_fcm()  # no send_fn → real resolution path

    result = await notifier.send_alert(_make_request())

    assert isinstance(result, AlertResult)
    assert result.sent is False
    assert result.channel == "fcm"
    assert result.error is not None
    assert "FCM not configured" in result.error


@pytest.mark.asyncio
async def test_send_alert_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FCM_SERVICE_ACCOUNT_PATH", raising=False)
    notifier = _make_fcm()
    try:
        result = await notifier.send_alert(_make_request())
    except Exception as exc:  # noqa: BLE001
        pytest.fail(f"send_alert() raised unexpectedly: {exc!r}")
    assert isinstance(result, AlertResult)


@pytest.mark.asyncio
async def test_get_history_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FCM_SERVICE_ACCOUNT_PATH", raising=False)
    notifier = _make_fcm()
    assert await notifier.get_alert_history("child-fcm-001") == []


# ---------------------------------------------------------------------------
# Configured path — injected send_fn (no real Firebase needed)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_success_path_returns_sent_with_message_id() -> None:
    """A working sender → sent=True with the FCM message id, never queued."""
    calls: list[tuple[str, str]] = []

    def fake_send(req: AlertRequest, alert_id: str) -> str:
        calls.append((req.child_id, alert_id))
        return "fcm-msg-123"

    q = LocalRetryQueue(max_size=5)
    notifier = _make_fcm(send_fn=fake_send, retry_queue=q)

    result = await notifier.send_alert(_make_request())

    assert result.sent is True
    assert result.channel == "fcm"
    assert result.fcm_message_id == "fcm-msg-123"
    assert result.queued is False
    assert result.rate_limited is False
    assert len(calls) == 1
    assert q.size() == 0


@pytest.mark.asyncio
async def test_retries_then_queues_on_persistent_failure() -> None:
    """3 failed attempts → queued=True and the request lands in the queue."""
    attempts = {"n": 0}

    def always_fail(req: AlertRequest, alert_id: str) -> str:  # noqa: ARG001
        attempts["n"] += 1
        raise RuntimeError("fcm down")

    # retry_base_seconds=0.0 keeps the test instant (sleep(0)).
    settings = AlertSettings(max_retry_attempts=3, retry_base_seconds=0.0)
    q = LocalRetryQueue(max_size=5)
    notifier = _make_fcm(send_fn=always_fail, retry_queue=q, settings=settings)

    result = await notifier.send_alert(_make_request())

    assert result.sent is False
    assert result.queued is True
    assert result.error is not None
    assert attempts["n"] == 3
    assert q.size() == 1


@pytest.mark.asyncio
async def test_rate_limited_short_circuits_before_send() -> None:
    """When the limiter denies, no send is attempted and rate_limited=True."""
    sent = {"called": False}

    def fake_send(req: AlertRequest, alert_id: str) -> str:  # noqa: ARG001
        sent["called"] = True
        return "should-not-happen"

    notifier = _make_fcm(send_fn=fake_send, rate_limiter=_DenyRateLimiter())

    result = await notifier.send_alert(_make_request())

    assert result.rate_limited is True
    assert result.sent is False
    assert sent["called"] is False


@pytest.mark.asyncio
async def test_idempotent_alert_id_on_configured_path() -> None:
    notifier = _make_fcm(send_fn=lambda req, aid: "x")
    r1 = await notifier.send_alert(_make_request())
    r2 = await notifier.send_alert(_make_request())
    assert r1.alert_id == r2.alert_id


@pytest.mark.asyncio
async def test_audit_recorder_invoked_on_success() -> None:
    recorded: list[AlertResult] = []

    async def recorder(req: AlertRequest, res: AlertResult) -> None:  # noqa: ARG001
        recorded.append(res)

    notifier = _make_fcm(send_fn=lambda req, aid: "ok", audit_recorder=recorder)
    await notifier.send_alert(_make_request())

    assert len(recorded) == 1
    assert recorded[0].sent is True


# ---------------------------------------------------------------------------
# Real-Firebase path — exercised against a stand-in firebase_admin module
# (covers _resolve_send_fn init branch, _build_message, _build_real_send_fn).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_real_resolution_builds_and_sends(fake_firebase) -> None:
    """With firebase_admin present + creds set, the real path builds a Message,
    initialises the app once, sends it, and returns the FCM id."""
    notifier = FcmNotifier(
        AlertSettings(),
        NoOpAlertRateLimiter(),
        service_account_path="/fake/service-account.json",
    )

    result = await notifier.send_alert(_make_request())

    assert result.sent is True
    assert result.channel == "fcm"
    assert result.fcm_message_id == "fake-fcm-id-999"

    # The app was initialised exactly once (idempotent get_app guard).
    assert fake_firebase.init_calls() == 1

    # The built Message carries the full LLD §3 payload.
    msg = fake_firebase.messaging._sent[0]
    assert msg.token == "fake-fcm-token-for-testing"
    assert set(msg.data) == {
        "alert_id",
        "child_id",
        "message_id",
        "label",
        "severity",
        "quote",
        "source",
        "trace_id",
        "deep_link",
    }
    assert msg.data["alert_id"] == result.alert_id
    assert msg.data["deep_link"] == f"shomer://alert/{result.alert_id}"
    assert msg.android.priority == "high"
    assert msg.android.notification.channel_id == "shomer_alerts"


@pytest.mark.asyncio
async def test_init_failure_degrades_to_not_configured(
    fake_firebase,
) -> None:
    """A bad service account (Certificate raises) → sent=False, never crashes."""

    def _boom(path):  # noqa: ARG001
        raise RuntimeError("invalid service account")

    fake_firebase.credentials.Certificate = _boom

    notifier = FcmNotifier(
        AlertSettings(),
        NoOpAlertRateLimiter(),
        service_account_path="/fake/bad.json",
    )
    result = await notifier.send_alert(_make_request())

    assert result.sent is False
    assert result.error is not None
    assert "init failed" in result.error


@pytest.mark.asyncio
async def test_firebase_present_but_no_creds_degrades(fake_firebase) -> None:  # noqa: ARG001
    """firebase-admin installed but no service-account path → not configured."""
    notifier = FcmNotifier(
        AlertSettings(),
        NoOpAlertRateLimiter(),
        service_account_path="",  # present lib, empty creds → no-creds branch
    )
    result = await notifier.send_alert(_make_request())
    assert result.sent is False
    assert result.error is not None
    assert "FCM_SERVICE_ACCOUNT_PATH not set" in result.error


@pytest.mark.asyncio
async def test_audit_recorder_failure_is_swallowed() -> None:
    """A raising audit_recorder must not break send_alert()."""

    async def _boom(req: AlertRequest, res: AlertResult) -> None:  # noqa: ARG001
        raise RuntimeError("audit store down")

    notifier = _make_fcm(send_fn=lambda req, aid: "ok", audit_recorder=_boom)
    result = await notifier.send_alert(_make_request())
    assert result.sent is True  # delivery still succeeds despite audit failure


@pytest.mark.asyncio
async def test_real_path_send_failure_queues(fake_firebase) -> None:
    """messaging.send raising on every attempt → queued=True via the real path."""

    def _always_fail(message):  # noqa: ARG001
        raise RuntimeError("FCM unavailable")

    fake_firebase.messaging.send = _always_fail

    settings = AlertSettings(max_retry_attempts=2, retry_base_seconds=0.0)
    q = LocalRetryQueue(max_size=5)
    notifier = FcmNotifier(
        settings,
        NoOpAlertRateLimiter(),
        retry_queue=q,
        service_account_path="/fake/service-account.json",
    )

    result = await notifier.send_alert(_make_request())

    assert result.sent is False
    assert result.queued is True
    assert q.size() == 1


# ---------------------------------------------------------------------------
# Top-level safety net — send_alert() never raises even on internal error.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_top_level_exception_is_captured() -> None:
    """An unexpected internal error (limiter raises) → AlertResult, not crash."""

    class _BoomLimiter:
        def allow(self, key: str) -> bool:  # noqa: ARG002
            raise RuntimeError("limiter exploded")

    notifier = _make_fcm(send_fn=lambda req, aid: "x", rate_limiter=_BoomLimiter())
    result = await notifier.send_alert(_make_request())

    assert isinstance(result, AlertResult)
    assert result.sent is False
    assert result.error is not None


# ---------------------------------------------------------------------------
# health_status() schema
# ---------------------------------------------------------------------------


def test_health_status_schema_without_queue() -> None:
    h = _make_fcm().health_status()
    assert isinstance(h, dict)
    assert h["status"] in ("ok", "degraded")
    assert isinstance(h["queued_alerts"], int)
    assert h["queued_alerts"] >= 0


def test_health_status_reflects_queue_depth() -> None:
    q = LocalRetryQueue(max_size=5)
    q.enqueue(
        AlertRequest(
            child_id="c",
            message_id="m",
            label="hate",
            severity="low",
            explanation="x",
            quote="",
            source="frontline_direct",
            trace_id="t",
        )
    )
    notifier = _make_fcm(retry_queue=q)
    h = notifier.health_status()
    assert h["status"] == "degraded"
    assert h["queued_alerts"] == 1
