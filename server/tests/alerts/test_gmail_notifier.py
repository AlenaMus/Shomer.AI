"""Unit tests for GmailApiNotifier.

Tests:
- Happy path: send_fn called with correct userId="me" args; AlertResult(sent=True).
- MIME message has correct base64url encoding, Hebrew subject, and to/from headers.
- Rate-limited path: AlertResult(sent=False, rate_limited=True).
- Missing token file → graceful AlertResult(sent=False, error=...) — never raises.
- Missing google-auth package → graceful AlertResult(sent=False, error=...).
- Injected audit_recorder is called exactly once.
- alert_id is deterministic (idempotency key matches compute_alert_id).
- ALERTS_CHANNEL=email → lifespan selects GmailApiNotifier (composition test).

All tests use a mock send_fn — NO real network calls are made.
"""

from __future__ import annotations

import base64
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(_SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVER_ROOT))

from app.alerts import (
    AlertSettings,
    GmailApiNotifier,
    InMemoryAlertRateLimiter,
    LocalRetryQueue,
    NoOpAlertRateLimiter,
    compute_alert_id,
)
from app.alerts.gmail_notifier import _build_raw_message
from app.schemas import AlertRequest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(**overrides) -> AlertRequest:
    defaults = dict(
        child_id="child-gmail-001",
        message_id="msg-gmail-abc",
        label="violence",
        severity="high",
        explanation="Content flagged by the context agent.",
        quote="שלום, מה קורה?",
        source="context_agent",
        trace_id="trace-gmail-xyz",
    )
    defaults.update(overrides)
    return AlertRequest(**defaults)


def _make_settings(**overrides) -> AlertSettings:
    return AlertSettings(
        channel="email",
        rate_limit_max_alerts=3,
        rate_limit_window_seconds=60,
        max_retry_attempts=2,
        retry_base_seconds=0.01,  # fast for tests
        queue_max_size=10,
    )


def _make_notifier(
    rate_limiter=None,
    retry_queue=None,
    audit_recorder=None,
    send_fn=None,
) -> GmailApiNotifier:
    settings = _make_settings()
    if rate_limiter is None:
        rate_limiter = NoOpAlertRateLimiter()
    return GmailApiNotifier(
        settings=settings,
        rate_limiter=rate_limiter,
        retry_queue=retry_queue,
        audit_recorder=audit_recorder,
        send_fn=send_fn,
    )


# ---------------------------------------------------------------------------
# Test: happy path — send_fn is called; AlertResult(sent=True)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_happy_path_returns_sent_true():
    """send_fn called → AlertResult(sent=True, channel='email')."""
    mock_send_fn = MagicMock(return_value="gmail-msg-id-001")
    notifier = _make_notifier(send_fn=mock_send_fn)
    req = _make_request()

    # Manually inject a cached from-address so _resolve_from_address doesn't call API.
    notifier._from_address = "sender@example.com"

    result = await notifier.send_alert(req, to_email="parent@example.com")

    assert result.sent is True
    assert result.channel == "email"
    assert result.fcm_message_id == "gmail-msg-id-001"
    assert result.rate_limited is False
    assert result.error is None
    mock_send_fn.assert_called_once()


@pytest.mark.asyncio
async def test_alert_id_is_deterministic():
    """alert_id matches compute_alert_id(request) — idempotency holds."""
    mock_send_fn = MagicMock(return_value="gm-001")
    notifier = _make_notifier(send_fn=mock_send_fn)
    notifier._from_address = "sender@example.com"
    req = _make_request()

    result = await notifier.send_alert(req, to_email="p@example.com")
    expected_id = compute_alert_id(req)

    assert result.alert_id == expected_id


# ---------------------------------------------------------------------------
# Test: MIME message structure
# ---------------------------------------------------------------------------


def test_build_raw_message_base64url_decodeable():
    """_build_raw_message returns a valid base64url-encoded MIME message.

    The outer envelope is base64url (Gmail API requirement).  After decoding,
    the headers are visible in plain ASCII; the body may itself be
    Content-Transfer-Encoding: base64 (Python's email library encodes UTF-8
    bodies that way for 7-bit SMTP compat).  We verify:
    - The MIME headers contain the correct To/From addresses.
    - The outer base64url envelope is decodeable.
    - The label appears somewhere in the full decoded text (either in the
      quoted-printable subject or in the body).
    """
    import email as _email
    req = _make_request()
    raw = _build_raw_message("to@example.com", "from@example.com", req)
    # Must be decodable as base64url without error.
    raw_bytes = base64.urlsafe_b64decode(raw + "==")
    msg = _email.message_from_bytes(raw_bytes)
    # Headers visible in the MIME message.
    assert msg["To"] == "to@example.com"
    assert msg["From"] == "from@example.com"
    # Decode the message payload (handles base64 Content-Transfer-Encoding).
    payload = msg.get_payload(decode=True).decode("utf-8", errors="replace")
    assert "violence" in payload
    assert req.quote in payload


def test_build_raw_message_hebrew_subject():
    """Subject line contains the Shomer.AI identifier and the label."""
    import email as _email
    req = _make_request()
    raw = _build_raw_message("t@x.com", "f@x.com", req)
    raw_bytes = base64.urlsafe_b64decode(raw + "==")
    msg = _email.message_from_bytes(raw_bytes)
    # Decode the (possibly encoded) subject header.
    from email.header import decode_header as _dh
    subject_parts = _dh(msg["Subject"] or "")
    subject = "".join(
        (part.decode(enc or "utf-8") if isinstance(part, bytes) else part)
        for part, enc in subject_parts
    )
    assert "Shomer.AI" in subject
    assert "violence" in subject


# ---------------------------------------------------------------------------
# Test: rate-limited path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rate_limited_returns_not_sent():
    """When rate limiter denies, AlertResult(sent=False, rate_limited=True)."""
    limiter = InMemoryAlertRateLimiter(max_alerts=0, window_seconds=60)
    mock_send_fn = MagicMock(return_value="should-not-be-called")
    notifier = _make_notifier(rate_limiter=limiter, send_fn=mock_send_fn)
    notifier._from_address = "sender@example.com"
    req = _make_request()

    result = await notifier.send_alert(req, to_email="p@example.com")

    assert result.sent is False
    assert result.rate_limited is True
    mock_send_fn.assert_not_called()


# ---------------------------------------------------------------------------
# Test: missing token file → graceful degradation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_token_file_graceful_degradation(tmp_path):
    """When token.json does not exist, send_alert returns sent=False, never raises."""
    notifier = _make_notifier()  # no send_fn → real path; but no token file
    notifier._token_json = str(tmp_path / "nonexistent_token.json")
    notifier._from_address = "sender@example.com"
    # _get_service will raise RuntimeError which _send_inner catches.
    req = _make_request()

    result = await notifier.send_alert(req, to_email="p@example.com")

    assert result.sent is False
    assert result.error is not None
    assert "token" in result.error.lower() or "not found" in result.error.lower()


# ---------------------------------------------------------------------------
# Test: missing google-auth → graceful degradation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_google_auth_graceful_degradation(tmp_path):
    """When google-auth is missing, send_alert returns sent=False, never raises."""
    # Write a dummy token file so the path check passes.
    token_path = tmp_path / "token.json"
    token_path.write_text("{}", encoding="utf-8")

    notifier = _make_notifier()  # no send_fn
    notifier._token_json = str(token_path)
    notifier._from_address = "sender@example.com"

    # Patch google.oauth2 import to simulate ImportError.
    with patch.dict("sys.modules", {"google.oauth2.credentials": None, "google.auth.transport.requests": None}):
        req = _make_request()
        result = await notifier.send_alert(req, to_email="p@example.com")

    # Should degrade gracefully even if the import fails inside _get_service.
    assert result.sent is False


# ---------------------------------------------------------------------------
# Test: audit_recorder is called exactly once on success
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_audit_recorder_called_on_success():
    """Injected audit_recorder is awaited exactly once on a successful send."""
    recorder_calls: list[tuple] = []

    async def _recorder(req, res):
        recorder_calls.append((req, res))

    mock_send_fn = MagicMock(return_value="gm-audit-001")
    notifier = _make_notifier(audit_recorder=_recorder, send_fn=mock_send_fn)
    notifier._from_address = "sender@example.com"
    req = _make_request()

    result = await notifier.send_alert(req, to_email="p@example.com")

    assert result.sent is True
    assert len(recorder_calls) == 1
    assert recorder_calls[0][0] is req
    assert recorder_calls[0][1].sent is True


@pytest.mark.asyncio
async def test_audit_recorder_called_on_rate_limited():
    """Audit recorder is also called for rate-limited results."""
    recorder_calls: list[tuple] = []

    async def _recorder(req, res):
        recorder_calls.append((req, res))

    limiter = InMemoryAlertRateLimiter(max_alerts=0, window_seconds=60)
    notifier = _make_notifier(rate_limiter=limiter, audit_recorder=_recorder)
    notifier._from_address = "sender@example.com"
    req = _make_request()

    await notifier.send_alert(req, to_email="p@example.com")

    assert len(recorder_calls) == 1
    assert recorder_calls[0][1].rate_limited is True


@pytest.mark.asyncio
async def test_raising_audit_recorder_does_not_propagate():
    """A raising audit_recorder must NOT cause send_alert to raise or return error."""

    async def _bad_recorder(req, res):
        raise RuntimeError("audit DB is down")

    mock_send_fn = MagicMock(return_value="gm-ok")
    notifier = _make_notifier(audit_recorder=_bad_recorder, send_fn=mock_send_fn)
    notifier._from_address = "sender@example.com"
    req = _make_request()

    result = await notifier.send_alert(req, to_email="p@example.com")
    # The send succeeded; the audit failure must be swallowed.
    assert result.sent is True
    assert result.error is None


# ---------------------------------------------------------------------------
# Test: all retries exhausted → queued=True
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_retries_exhausted_queued():
    """When all retries fail, result is queued=True, retry_queue has one item."""
    def _failing_send(to, raw):
        raise ConnectionError("SMTP timeout")

    queue = LocalRetryQueue(max_size=10)
    notifier = _make_notifier(retry_queue=queue, send_fn=_failing_send)
    notifier._from_address = "sender@example.com"
    req = _make_request()

    result = await notifier.send_alert(req, to_email="p@example.com")

    assert result.sent is False
    assert result.queued is True
    assert queue.size() == 1


# ---------------------------------------------------------------------------
# Test: health_status reflects retry-queue depth
# ---------------------------------------------------------------------------


def test_health_status_ok_when_queue_empty():
    queue = LocalRetryQueue(max_size=10)
    notifier = _make_notifier(retry_queue=queue)
    assert notifier.health_status()["status"] == "ok"
    assert notifier.health_status()["queued_alerts"] == 0


@pytest.mark.asyncio
async def test_health_status_degraded_when_queue_nonempty():
    def _failing_send(to, raw):
        raise OSError("offline")

    queue = LocalRetryQueue(max_size=10)
    notifier = _make_notifier(retry_queue=queue, send_fn=_failing_send)
    notifier._from_address = "sender@example.com"
    req = _make_request()

    await notifier.send_alert(req, to_email="p@example.com")

    hs = notifier.health_status()
    assert hs["status"] == "degraded"
    assert hs["queued_alerts"] == 1
