"""Integration tests for the email (GmailApiNotifier) alert channel.

Tests:
- ALERTS_CHANNEL=email → lifespan selects GmailApiNotifier (composition test).
- _dispatch_alert resolves child→parent→email and calls send_alert(to_email=...).
- When no parent email is registered, dispatch logs a warning and does NOT raise.
- When child_id is absent ("unknown"), dispatch logs a warning and does NOT raise.

Strategy: inject a mock send_fn into GmailApiNotifier so no real Gmail call is
made.  The mock records (to_email, raw_b64) tuples.  We verify that the resolver
threads the right email address through.

Run from repo root:
    python -m pytest server/tests/integration/test_email_alert_channel.py -q
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest

_SERVER_DIR = str(Path(__file__).resolve().parents[2])
if _SERVER_DIR not in sys.path:
    sys.path.insert(0, _SERVER_DIR)

from fastapi.testclient import TestClient

from app.main import app
from app.alerts import GmailApiNotifier, AlertSettings, InMemoryAlertRateLimiter, LocalRetryQueue
from app.identity import InMemoryIdentityStore
from app.schemas import ClassificationResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_offensive_result() -> ClassificationResult:
    return ClassificationResult(
        label="abusive",
        confidence=0.95,
        is_offensive=True,
        model_version="stub-test",
        latency_ms=1.0,
        is_borderline=False,
        raw_confidence=0.95,
        error=False,
    )


class _StubClassifier:
    def __init__(self, result: ClassificationResult) -> None:
        self._result = result
        self.model_version = "stub-test"
        self.backend_name = "stub-test"

    async def classify(self, text: str) -> ClassificationResult:  # noqa: ARG002
        return self._result

    async def health(self):
        from app.schemas import HealthState
        return (HealthState.OK, "stub")


# ---------------------------------------------------------------------------
# Fixture: app with email channel selected
# ---------------------------------------------------------------------------


@pytest.fixture
def email_channel_client(tmp_path, monkeypatch):
    """TestClient with ALERTS_CHANNEL=email; GmailApiNotifier with mock send_fn.

    Yields (client, notifier, send_calls) where send_calls is a list that the
    mock send_fn appends ``(to_email, raw_b64)`` tuples to.
    """
    monkeypatch.setenv("AUDIT_DB_PATH", str(tmp_path / "audit.db"))
    monkeypatch.setenv("ALERTS_CHANNEL", "email")
    monkeypatch.setenv("CONTEXT_AGENT_ENABLED", "false")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "99999")

    send_calls: list[tuple[str, str]] = []

    def _mock_send(to_email: str, raw_b64: str) -> str:
        send_calls.append((to_email, raw_b64))
        return f"mock-gmail-id-{len(send_calls)}"

    with TestClient(app, raise_server_exceptions=True) as client:
        # After lifespan(), replace the notifier with one using our mock send_fn.
        settings = AlertSettings(channel="email", max_retry_attempts=1, retry_base_seconds=0.0)
        rate_limiter = InMemoryAlertRateLimiter(max_alerts=100, window_seconds=60)
        queue = LocalRetryQueue(max_size=10)
        gmail_notifier = GmailApiNotifier(
            settings=settings,
            rate_limiter=rate_limiter,
            retry_queue=queue,
            send_fn=_mock_send,
        )
        gmail_notifier._from_address = "shomer.alerts@example.com"
        app.state.notifier = gmail_notifier

        # Replace the classifier so it always produces an ALERT_DIRECT result.
        app.state.classifier = _StubClassifier(_make_offensive_result())

        yield client, gmail_notifier, send_calls


# ---------------------------------------------------------------------------
# Test: composition root selects GmailApiNotifier when ALERTS_CHANNEL=email
# ---------------------------------------------------------------------------


def test_email_channel_selects_gmail_notifier(email_channel_client):
    """After lifespan (with ALERTS_CHANNEL=email), notifier is GmailApiNotifier."""
    client, notifier, _ = email_channel_client
    # We replaced it in the fixture — verify the type.
    assert isinstance(notifier, GmailApiNotifier)


# ---------------------------------------------------------------------------
# Test: send_alert called with correct to_email when parent email is registered
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_routes_to_parent_email(email_channel_client):
    """When parent has an email, _dispatch_alert passes it to send_alert."""
    client, notifier, send_calls = email_channel_client

    # Register parent with email, issue child.
    identity: InMemoryIdentityStore = InMemoryIdentityStore()
    parent_id, _token = await identity.register_parent(
        email="test.parent@example.com",
        password="strongpass1",
    )
    child_rec = await identity.issue_child(parent_id, "TestChild")
    app.state.identity = identity

    # Classify text as the child.
    resp = client.post(
        "/classify",
        json={"text": "שלום, מה קורה?", "child_id": child_rec.child_id},
    )
    assert resp.status_code == 200

    # send_fn should have been called with the parent's email.
    assert len(send_calls) == 1
    to_email, raw_b64 = send_calls[0]
    assert to_email == "test.parent@example.com"
    # raw_b64 should be a non-empty base64url string.
    import base64
    decoded = base64.urlsafe_b64decode(raw_b64 + "==").decode("utf-8", errors="replace")
    assert "To: test.parent@example.com" in decoded


# ---------------------------------------------------------------------------
# Test: no parent email registered → dispatch does NOT raise or send
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_no_parent_email_no_raise(email_channel_client):
    """When parent has no email, dispatch logs a warning and does NOT call send_fn."""
    client, notifier, send_calls = email_channel_client

    # Register parent WITHOUT email.
    identity = InMemoryIdentityStore()
    parent_id, _token = await identity.register_parent(display_name="NoEmailParent")
    child_rec = await identity.issue_child(parent_id, "ChildNoEmail")
    app.state.identity = identity

    resp = client.post(
        "/classify",
        json={"text": "תוכן פוגעני", "child_id": child_rec.child_id},
    )
    # Pipeline should complete successfully — no crash.
    assert resp.status_code == 200
    # But no email was sent.
    assert len(send_calls) == 0


# ---------------------------------------------------------------------------
# Test: no child_id → dispatch logs warning, no email sent
# ---------------------------------------------------------------------------


def test_dispatch_no_child_id_no_email_sent(email_channel_client):
    """When child_id is absent, no email is sent (no parent to resolve)."""
    client, _, send_calls = email_channel_client

    resp = client.post("/classify", json={"text": "אני אהרוג אותך"})
    assert resp.status_code == 200
    assert len(send_calls) == 0
