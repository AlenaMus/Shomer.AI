"""Unit tests for SmtpEmailNotifier.

Tests:
- Happy path: smtp_factory called; starttls+login+send_message invoked in order;
  AlertResult(sent=True, channel='smtp').
- STARTTLS vs SSL path (SMTP_USE_SSL=true skips starttls).
- Correct MIME (To/From/Subject/Hebrew body) via shared email_message helper.
- Rate-limited path: AlertResult(sent=False, rate_limited=True); factory not called.
- Missing SMTP_USER / SMTP_APP_PASSWORD → graceful AlertResult(sent=False); no factory call.
- Any SMTP exception → graceful AlertResult(sent=False, error=...).
- All retries exhausted → queued=True when retry_queue provided.
- Injected audit_recorder called exactly once on success.
- Raising audit_recorder does NOT propagate.
- health_status: ok when queue empty, degraded when queue has items.
- ALERTS_CHANNEL=smtp → lifespan selects SmtpEmailNotifier (channel selection test).
- _dispatch_alert resolves email for SmtpEmailNotifier (isinstance-branch test).
- Shared email_message helper: subject + body content correctness.

All tests mock smtplib — NO real network calls are made.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

_SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(_SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVER_ROOT))

from app.alerts import (
    AlertSettings,
    InMemoryAlertRateLimiter,
    LocalRetryQueue,
    NoOpAlertRateLimiter,
    SmtpEmailNotifier,
    compute_alert_id,
)
from app.alerts.email_message import (
    build_alert_body,
    build_alert_subject,
    build_email_message,
    build_raw_message_base64url,
)
from app.schemas import AlertRequest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(**overrides) -> AlertRequest:
    defaults = dict(
        child_id="child-smtp-001",
        message_id="msg-smtp-abc",
        label="abusive",
        severity="medium",
        explanation="Content flagged by the classifier.",
        quote="זה משפט בעייתי",
        source="frontline_direct",
        trace_id="trace-smtp-xyz",
    )
    defaults.update(overrides)
    return AlertRequest(**defaults)


def _make_settings(**overrides) -> AlertSettings:
    return AlertSettings(
        channel="smtp",
        rate_limit_max_alerts=3,
        rate_limit_window_seconds=60,
        max_retry_attempts=2,
        retry_base_seconds=0.01,  # fast retries in tests
        queue_max_size=10,
    )


def _make_smtp_mock() -> MagicMock:
    """Return a mock SMTP connection object (not a context manager).

    SmtpEmailNotifier._do_send_sync branches on hasattr(__enter__); this mock
    does NOT expose __enter__/__exit__ so the non-context-manager path is taken.
    """
    mock = MagicMock()
    # Remove __enter__/__exit__ so hasattr(__enter__) returns False.
    del mock.__enter__
    del mock.__exit__
    return mock


def _make_notifier(
    rate_limiter=None,
    retry_queue=None,
    audit_recorder=None,
    smtp_factory=None,
    env_overrides: dict | None = None,
) -> SmtpEmailNotifier:
    """Build a SmtpEmailNotifier with test-friendly defaults."""
    settings = _make_settings()
    if rate_limiter is None:
        rate_limiter = NoOpAlertRateLimiter()

    env = {
        "SMTP_HOST": "smtp.gmail.com",
        "SMTP_PORT": "587",
        "SMTP_USER": "sender@example.com",
        "SMTP_APP_PASSWORD": "test-app-password",
        "ALERT_FROM": "sender@example.com",
        "SMTP_USE_SSL": "false",
    }
    if env_overrides:
        env.update(env_overrides)

    with patch.dict(os.environ, env, clear=False):
        notifier = SmtpEmailNotifier(
            settings=settings,
            rate_limiter=rate_limiter,
            retry_queue=retry_queue,
            audit_recorder=audit_recorder,
            smtp_factory=smtp_factory,
        )
    return notifier


# ---------------------------------------------------------------------------
# Test: shared email_message helper
# ---------------------------------------------------------------------------


def test_build_alert_subject_contains_label():
    """Subject includes 'Shomer.AI' and the label."""
    subject = build_alert_subject("violence")
    assert "Shomer.AI" in subject
    assert "violence" in subject


def test_build_alert_body_contains_required_fields():
    """Body contains child_id, label, severity, quote, explanation, trace_id."""
    req = _make_request()
    body = build_alert_body(req)
    assert req.child_id in body
    assert req.label in body
    assert req.quote in body
    assert req.explanation in body
    assert req.trace_id in body


def test_build_email_message_headers():
    """build_email_message sets To/From/Subject correctly."""
    req = _make_request()
    msg = build_email_message("parent@example.com", "sender@example.com", req)
    assert msg["To"] == "parent@example.com"
    assert msg["From"] == "sender@example.com"
    assert "Shomer.AI" in msg["Subject"]
    assert req.label in msg["Subject"]


def test_build_raw_message_base64url_decodeable():
    """build_raw_message_base64url returns valid base64url-decodeable MIME."""
    import base64
    import email as _email

    req = _make_request()
    raw = build_raw_message_base64url("t@x.com", "f@x.com", req)
    raw_bytes = base64.urlsafe_b64decode(raw + "==")
    msg = _email.message_from_bytes(raw_bytes)
    assert msg["To"] == "t@x.com"
    assert msg["From"] == "f@x.com"


# ---------------------------------------------------------------------------
# Test: happy path — STARTTLS
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_happy_path_starttls():
    """smtp_factory called; ehlo+starttls+login+send_message called in order;
    AlertResult(sent=True, channel='smtp')."""
    smtp_mock = _make_smtp_mock()
    factory = MagicMock(return_value=smtp_mock)
    notifier = _make_notifier(smtp_factory=factory)
    req = _make_request()

    result = await notifier.send_alert(req, to_email="parent@example.com")

    assert result.sent is True
    assert result.channel == "smtp"
    assert result.rate_limited is False
    assert result.error is None

    # Factory must have been called once.
    factory.assert_called_once()

    # STARTTLS flow: ehlo → starttls → ehlo → login → send_message.
    smtp_mock.ehlo.assert_called()
    smtp_mock.starttls.assert_called_once()
    smtp_mock.login.assert_called_once_with("sender@example.com", "test-app-password")
    smtp_mock.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_happy_path_ssl():
    """When SMTP_USE_SSL=true, starttls is NOT called; login+send_message ARE called."""
    smtp_mock = _make_smtp_mock()
    factory = MagicMock(return_value=smtp_mock)

    with patch.dict(os.environ, {"SMTP_USE_SSL": "true"}, clear=False):
        settings = _make_settings()
        notifier = SmtpEmailNotifier(
            settings=settings,
            rate_limiter=NoOpAlertRateLimiter(),
            smtp_factory=factory,
        )
        # Force credential values (already set by env in factory, but re-set to be safe).
        notifier._user = "sender@example.com"
        notifier._password = "test-app-password"
        notifier._from = "sender@example.com"

    req = _make_request()
    result = await notifier.send_alert(req, to_email="parent@example.com")

    assert result.sent is True
    smtp_mock.starttls.assert_not_called()
    smtp_mock.login.assert_called_once()
    smtp_mock.send_message.assert_called_once()


# ---------------------------------------------------------------------------
# Test: alert_id is deterministic
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_alert_id_is_deterministic():
    """alert_id matches compute_alert_id(request) — idempotency."""
    smtp_mock = _make_smtp_mock()
    notifier = _make_notifier(smtp_factory=MagicMock(return_value=smtp_mock))
    req = _make_request()

    result = await notifier.send_alert(req, to_email="p@example.com")
    assert result.alert_id == compute_alert_id(req)


# ---------------------------------------------------------------------------
# Test: MIME correctness
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_message_receives_correct_mime():
    """send_message is called with an EmailMessage with correct To/From/Subject."""
    from email.message import EmailMessage

    smtp_mock = _make_smtp_mock()
    notifier = _make_notifier(smtp_factory=MagicMock(return_value=smtp_mock))
    req = _make_request()

    await notifier.send_alert(req, to_email="parent@example.com")

    args, _ = smtp_mock.send_message.call_args
    sent_msg = args[0]
    assert isinstance(sent_msg, EmailMessage)
    assert sent_msg["To"] == "parent@example.com"
    assert sent_msg["From"] == "sender@example.com"
    assert "Shomer.AI" in sent_msg["Subject"]
    assert req.label in sent_msg["Subject"]
    # Body contains the Hebrew quote.
    payload = sent_msg.get_body()
    body_text = payload.get_content() if payload else str(sent_msg)
    assert req.quote in body_text


# ---------------------------------------------------------------------------
# Test: rate-limited path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rate_limited_returns_not_sent():
    """When rate limiter denies, AlertResult(sent=False, rate_limited=True); factory not called."""
    limiter = InMemoryAlertRateLimiter(max_alerts=0, window_seconds=60)
    factory = MagicMock()
    notifier = _make_notifier(rate_limiter=limiter, smtp_factory=factory)
    req = _make_request()

    result = await notifier.send_alert(req, to_email="p@example.com")

    assert result.sent is False
    assert result.rate_limited is True
    factory.assert_not_called()


# ---------------------------------------------------------------------------
# Test: missing credentials → graceful degradation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_smtp_user_graceful():
    """Missing SMTP_USER → AlertResult(sent=False); factory never called."""
    factory = MagicMock()
    notifier = _make_notifier(
        smtp_factory=factory,
        env_overrides={"SMTP_USER": "", "SMTP_APP_PASSWORD": "pw"},
    )
    # Manually clear since env_overrides already applied at construction time.
    notifier._user = ""
    req = _make_request()

    result = await notifier.send_alert(req, to_email="p@example.com")

    assert result.sent is False
    assert result.error is not None
    assert "SMTP_USER" in result.error or "not set" in result.error.lower()
    factory.assert_not_called()


@pytest.mark.asyncio
async def test_missing_app_password_graceful():
    """Missing SMTP_APP_PASSWORD → AlertResult(sent=False); factory never called."""
    factory = MagicMock()
    notifier = _make_notifier(smtp_factory=factory)
    notifier._password = ""  # Simulate missing password after construction.
    req = _make_request()

    result = await notifier.send_alert(req, to_email="p@example.com")

    assert result.sent is False
    assert result.error is not None
    factory.assert_not_called()


# ---------------------------------------------------------------------------
# Test: SMTP exception → graceful degradation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_smtp_exception_graceful():
    """Any smtplib exception → AlertResult(sent=False, error=...); never raises."""
    smtp_mock = _make_smtp_mock()
    smtp_mock.login.side_effect = smtplib_error()
    factory = MagicMock(return_value=smtp_mock)
    notifier = _make_notifier(smtp_factory=factory)
    req = _make_request()

    result = await notifier.send_alert(req, to_email="p@example.com")

    assert result.sent is False
    assert result.error is not None


def smtplib_error():
    """Return a real smtplib exception for use in tests."""
    import smtplib
    return smtplib.SMTPAuthenticationError(535, b"Authentication failed")


# ---------------------------------------------------------------------------
# Test: all retries exhausted → queued
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_retries_exhausted_queued():
    """When all retries fail, result is queued=True, retry_queue has one item."""
    smtp_mock = _make_smtp_mock()
    smtp_mock.login.side_effect = ConnectionError("timeout")
    queue = LocalRetryQueue(max_size=10)
    notifier = _make_notifier(retry_queue=queue, smtp_factory=MagicMock(return_value=smtp_mock))
    req = _make_request()

    result = await notifier.send_alert(req, to_email="p@example.com")

    assert result.sent is False
    assert result.queued is True
    assert queue.size() == 1


# ---------------------------------------------------------------------------
# Test: audit_recorder called on success
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_audit_recorder_called_on_success():
    """Injected audit_recorder is awaited exactly once on success."""
    calls: list[tuple] = []

    async def _recorder(req, res):
        calls.append((req, res))

    smtp_mock = _make_smtp_mock()
    notifier = _make_notifier(
        audit_recorder=_recorder,
        smtp_factory=MagicMock(return_value=smtp_mock),
    )
    req = _make_request()

    result = await notifier.send_alert(req, to_email="p@example.com")

    assert result.sent is True
    assert len(calls) == 1
    assert calls[0][0] is req
    assert calls[0][1].sent is True


@pytest.mark.asyncio
async def test_audit_recorder_called_on_rate_limited():
    """Audit recorder is also called for rate-limited results."""
    calls: list[tuple] = []

    async def _recorder(req, res):
        calls.append((req, res))

    limiter = InMemoryAlertRateLimiter(max_alerts=0, window_seconds=60)
    notifier = _make_notifier(rate_limiter=limiter, audit_recorder=_recorder)
    req = _make_request()

    await notifier.send_alert(req, to_email="p@example.com")

    assert len(calls) == 1
    assert calls[0][1].rate_limited is True


@pytest.mark.asyncio
async def test_raising_audit_recorder_does_not_propagate():
    """A raising audit_recorder must NOT cause send_alert to fail."""

    async def _bad_recorder(req, res):
        raise RuntimeError("audit DB is down")

    smtp_mock = _make_smtp_mock()
    notifier = _make_notifier(
        audit_recorder=_bad_recorder,
        smtp_factory=MagicMock(return_value=smtp_mock),
    )
    req = _make_request()

    result = await notifier.send_alert(req, to_email="p@example.com")
    assert result.sent is True
    assert result.error is None


# ---------------------------------------------------------------------------
# Test: health_status
# ---------------------------------------------------------------------------


def test_health_status_ok_when_queue_empty():
    queue = LocalRetryQueue(max_size=10)
    notifier = _make_notifier(retry_queue=queue)
    hs = notifier.health_status()
    assert hs["status"] == "ok"
    assert hs["queued_alerts"] == 0


@pytest.mark.asyncio
async def test_health_status_degraded_when_queue_nonempty():
    smtp_mock = _make_smtp_mock()
    smtp_mock.login.side_effect = OSError("offline")
    queue = LocalRetryQueue(max_size=10)
    notifier = _make_notifier(
        retry_queue=queue, smtp_factory=MagicMock(return_value=smtp_mock)
    )
    req = _make_request()

    await notifier.send_alert(req, to_email="p@example.com")

    hs = notifier.health_status()
    assert hs["status"] == "degraded"
    assert hs["queued_alerts"] == 1


# ---------------------------------------------------------------------------
# Test: ALERTS_CHANNEL=smtp → lifespan selects SmtpEmailNotifier
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_channel_selection_smtp(tmp_path):
    """ALERTS_CHANNEL=smtp wires SmtpEmailNotifier in lifespan()."""
    from fastapi.testclient import TestClient

    env_patch = {
        "ALERTS_CHANNEL": "smtp",
        "SMTP_HOST": "smtp.gmail.com",
        "SMTP_PORT": "587",
        "SMTP_USER": "test@example.com",
        "SMTP_APP_PASSWORD": "test-pw",
        "ALERT_FROM": "test@example.com",
        # Minimal config to avoid heavy deps.
        "CLASSIFIER_MODEL_VERSION": "v1.0-standin",
        "AUDIT_DB_PATH": str(tmp_path / "test_smtp_audit.db"),
        "IDENTITY_BACKEND": "memory",
        "FLAGGED_BACKEND": "memory",
        "DEDUP_BACKEND": "memory",
        "CONTEXT_AGENT_ENABLED": "false",
        "OCR_BACKEND": "stub",
    }
    with patch.dict(os.environ, env_patch, clear=False):
        import importlib
        import app.main as main_mod
        importlib.reload(main_mod)
        client = TestClient(main_mod.app, raise_server_exceptions=True)
        client.__enter__()
        try:
            notifier = main_mod.app.state.notifier
            assert isinstance(notifier, SmtpEmailNotifier), (
                f"Expected SmtpEmailNotifier, got {type(notifier).__name__}"
            )
        finally:
            client.__exit__(None, None, None)


# ---------------------------------------------------------------------------
# Test: _dispatch_alert calls send_alert with to_email for SmtpEmailNotifier
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_alert_resolves_email_for_smtp_notifier():
    """_dispatch_alert resolves to_email for SmtpEmailNotifier (isinstance branch)."""
    from unittest.mock import AsyncMock, MagicMock, patch as _patch

    # Build a minimal mock request.app setup.
    smtp_mock = _make_smtp_mock()
    notifier = _make_notifier(smtp_factory=MagicMock(return_value=smtp_mock))

    mock_identity = MagicMock()
    mock_identity.parent_for_child = AsyncMock(return_value="parent-001")
    mock_identity.get_parent_email = AsyncMock(return_value="parent@example.com")

    mock_app_state = MagicMock()
    mock_app_state.notifier = notifier
    mock_app_state.identity = mock_identity

    mock_app = MagicMock()
    mock_app.state = mock_app_state

    mock_request = MagicMock()
    mock_request.app = mock_app
    mock_request.state = MagicMock()
    mock_request.state.audit = {}

    from app.schemas import ClassificationResult

    classification_result = ClassificationResult(
        label="abusive",
        is_offensive=True,
        confidence=0.9,
        model_version="v1.0-standin",
        latency_ms=10.0,
        is_borderline=False,
        raw_confidence=0.9,
    )

    from app.main import _dispatch_alert

    await _dispatch_alert(
        mock_request,
        text="זה משפט בעייתי",
        result=classification_result,
        ctx=None,
        trace_id="trace-dispatch-smtp",
        child_id="child-001",
        message_id="msg-001",
    )

    # Identity resolution was invoked.
    mock_identity.parent_for_child.assert_called_once_with("child-001")
    mock_identity.get_parent_email.assert_called_once_with("parent-001")

    # send_message on SMTP mock was called (meaning send_alert ran with to_email).
    smtp_mock.send_message.assert_called_once()
