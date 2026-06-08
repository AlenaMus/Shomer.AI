"""test_digest_delivery.py — Tests for ManualDigestRunner.deliver.

Covers:
  1. deliver resolves parent FCM token and calls the NotificationChannel once.
  2. deliver saves the digest to the DigestStore regardless of send result.
  3. deliver returns True when channel.sent=True; False when sent=False.
  4. If FCM token is None, the AlertRequest is sent with parent_fcm_token="".
  5. The AlertRequest message_id is "digest:{child_id}:{date}" (idempotency key).

No real Firebase — uses a stub NotificationChannel.

Run from repo root:
    .\\server\\.venv\\Scripts\\python.exe -m pytest server/tests/digest/test_digest_delivery.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SERVER_DIR = str(Path(__file__).resolve().parents[2])
if _SERVER_DIR not in sys.path:
    sys.path.insert(0, _SERVER_DIR)

from app.digest.in_memory_store import InMemoryDigestStore
from app.digest.manual_runner import ManualDigestRunner
from app.digest.protocol import ChildDigest, DigestEntry
from app.flagged.in_memory_adapter import InMemoryFlaggedEventStore
from app.schemas import AlertResult

_NOW = 1_700_000_200.0


def _make_digest(child_id: str = "child-1", date: str = "2023-11-14") -> ChildDigest:
    return ChildDigest(
        child_id=child_id,
        parent_id="parent-1",
        date=date,
        generated_at=_NOW,
        total_flagged=2,
        review_needed=1,
        by_severity={"medium": 1, "high": 1},
        by_label={"abusive": 2},
        entries=[
            DigestEntry(
                flag_id="f1",
                app_package="com.whatsapp",
                direction="inbound",
                label="abusive",  # type: ignore[arg-type]
                severity="high",  # type: ignore[arg-type]
                quote="שלום",
                status="alerted",  # type: ignore[arg-type]
                created_at=_NOW - 3600,
            ),
            DigestEntry(
                flag_id="f2",
                app_package="com.whatsapp",
                direction="inbound",
                label="abusive",  # type: ignore[arg-type]
                severity="medium",  # type: ignore[arg-type]
                quote="שלום",
                status="review_needed",  # type: ignore[arg-type]
                created_at=_NOW - 7200,
            ),
        ],
    )


class _FakeChannel:
    """Stub NotificationChannel that records calls and returns a configurable result."""

    def __init__(self, sent: bool = True):
        self.calls: list = []
        self._sent = sent

    async def send_alert(self, req):
        self.calls.append(req)
        return AlertResult(alert_id="a1", sent=self._sent, channel="stub")

    async def get_alert_history(self, *a, **kw):
        return []

    def health_status(self):
        return {"status": "ok", "queued_alerts": 0}


def _make_runner(
    channel,
    fcm_token: str | None = "fcm-token-parent-1",
):
    flagged = InMemoryFlaggedEventStore()
    digest_store = InMemoryDigestStore()

    async def _parent_for_child(child_id):
        return "parent-1"

    async def _fcm_token_for_parent(pid):
        return fcm_token

    async def _active_child_ids(since):
        return []

    runner = ManualDigestRunner(
        flagged=flagged,
        digest_store=digest_store,
        channel=channel,
        parent_for_child_fn=_parent_for_child,
        fcm_token_for_parent_fn=_fcm_token_for_parent,
        active_child_ids_fn=_active_child_ids,
        max_entries=50,
    )
    return runner, digest_store


@pytest.mark.asyncio
async def test_deliver_calls_channel_once():
    """deliver calls the NotificationChannel exactly once."""
    channel = _FakeChannel(sent=True)
    runner, _ = _make_runner(channel)
    digest = _make_digest()

    sent = await runner.deliver(digest)

    assert sent is True
    assert len(channel.calls) == 1


@pytest.mark.asyncio
async def test_deliver_saves_digest_to_store():
    """deliver always saves the digest to DigestStore (even if send fails)."""
    channel = _FakeChannel(sent=False)
    runner, digest_store = _make_runner(channel)
    digest = _make_digest()

    await runner.deliver(digest)

    saved = await digest_store.get(digest.child_id, digest.date)
    assert saved is not None
    assert saved.total_flagged == digest.total_flagged


@pytest.mark.asyncio
async def test_deliver_returns_false_when_not_sent():
    """deliver returns False when the channel did not send."""
    channel = _FakeChannel(sent=False)
    runner, _ = _make_runner(channel)
    digest = _make_digest()

    result = await runner.deliver(digest)

    assert result is False


@pytest.mark.asyncio
async def test_deliver_message_id_format():
    """AlertRequest.message_id is 'digest:{child_id}:{date}' (idempotency key)."""
    channel = _FakeChannel(sent=True)
    runner, _ = _make_runner(channel)
    digest = _make_digest(child_id="child-X", date="2023-11-15")

    await runner.deliver(digest)

    req = channel.calls[0]
    assert req.message_id == "digest:child-X:2023-11-15"


@pytest.mark.asyncio
async def test_deliver_no_fcm_token_uses_empty_string():
    """When FCM token is None, AlertRequest.parent_fcm_token is empty string."""
    channel = _FakeChannel(sent=True)
    runner, _ = _make_runner(channel, fcm_token=None)
    digest = _make_digest()

    await runner.deliver(digest)

    req = channel.calls[0]
    assert req.parent_fcm_token == ""


@pytest.mark.asyncio
async def test_deliver_label_is_highest_severity():
    """AlertRequest.label/severity correspond to the most severe entry."""
    channel = _FakeChannel(sent=True)
    runner, _ = _make_runner(channel)

    # Digest with "critical" hate entry.
    digest = ChildDigest(
        child_id="child-1",
        parent_id="parent-1",
        date="2023-11-14",
        generated_at=_NOW,
        total_flagged=2,
        review_needed=0,
        by_severity={"critical": 1, "low": 1},
        by_label={"hate": 1, "abusive": 1},
        entries=[
            DigestEntry(
                flag_id="f-crit",
                app_package="com.whatsapp",
                direction="inbound",
                label="hate",  # type: ignore[arg-type]
                severity="critical",  # type: ignore[arg-type]
                quote="",
                status="alerted",  # type: ignore[arg-type]
                created_at=_NOW - 100,
            ),
            DigestEntry(
                flag_id="f-low",
                app_package="com.whatsapp",
                direction="inbound",
                label="abusive",  # type: ignore[arg-type]
                severity="low",  # type: ignore[arg-type]
                quote="",
                status="alerted",  # type: ignore[arg-type]
                created_at=_NOW - 200,
            ),
        ],
    )
    await runner.deliver(digest)

    req = channel.calls[0]
    assert req.label == "hate"
    assert req.severity == "critical"
