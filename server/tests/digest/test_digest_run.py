"""test_digest_run.py — Tests for ManualDigestRunner.run_once.

Covers:
  1. Multiple children → exactly ONE digest per child with activity.
  2. deterministic with injected ``now`` (no wall-clock).
  3. Each digest is delivered exactly once.
  4. Each digest is saved to the DigestStore.
  5. A child with NO events in the window is skipped.
  6. A child with no parent mapping is skipped (logged, not crashed).

Run from repo root:
    .\\server\\.venv\\Scripts\\python.exe -m pytest server/tests/digest/test_digest_run.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SERVER_DIR = str(Path(__file__).resolve().parents[2])
if _SERVER_DIR not in sys.path:
    sys.path.insert(0, _SERVER_DIR)

from app.digest.in_memory_store import InMemoryDigestStore
from app.digest.manual_runner import ManualDigestRunner, _midnight_before
from app.flagged.in_memory_adapter import InMemoryFlaggedEventStore
from app.flagged.protocol import FlaggedEvent
from app.schemas import AlertResult

_NOW = 1_700_000_100.0
_DAY_START = _midnight_before(_NOW)
# Use a created_at that is AFTER _DAY_START (within today's window).
# _DAY_START for _NOW=1_700_000_100.0 is 1699999200.0 (server local midnight).
# So any created_at > 1699999200.0 and < _NOW is in-window.
_IN_WINDOW_TS = _DAY_START + 600  # 10 minutes after midnight — well within window


def _evt(flag_id: str, child_id: str, created_at: float = None) -> FlaggedEvent:
    return FlaggedEvent(
        flag_id=flag_id,
        child_id=child_id,
        created_at=created_at if created_at is not None else _IN_WINDOW_TS,
        app_package="com.whatsapp",
        direction="inbound",
        label="abusive",  # type: ignore[arg-type]
        severity="medium",  # type: ignore[arg-type]
        quote="שלום",
        explanation="הודעה פוגענית.",
        source="frontline_direct",
        trace_id="trace-" + flag_id,
        status="alerted",  # type: ignore[arg-type]
    )


class _FakeChannel:
    def __init__(self):
        self.calls: list = []

    async def send_alert(self, req):
        self.calls.append(req)
        return AlertResult(alert_id="a1", sent=True, channel="stub")

    async def get_alert_history(self, *a, **kw):
        return []

    def health_status(self):
        return {"status": "ok", "queued_alerts": 0}


def _make_runner(
    flagged_store,
    digest_store,
    channel,
    parent_map: dict,  # child_id → parent_id
) -> ManualDigestRunner:
    async def _parent_for_child(child_id):
        return parent_map.get(child_id)

    async def _fcm_token_for_parent(pid):
        return "fcm-token-" + pid

    async def _active_child_ids(since):
        return await flagged_store.child_ids_with_events_since(since)

    return ManualDigestRunner(
        flagged=flagged_store,
        digest_store=digest_store,
        channel=channel,
        parent_for_child_fn=_parent_for_child,
        fcm_token_for_parent_fn=_fcm_token_for_parent,
        active_child_ids_fn=_active_child_ids,
        max_entries=50,
    )


@pytest.mark.asyncio
async def test_run_once_one_digest_per_child():
    """run_once builds exactly one digest per child with activity."""
    flagged = InMemoryFlaggedEventStore()
    digest_store = InMemoryDigestStore()
    channel = _FakeChannel()

    await flagged.record(_evt("f1", "child-A"))
    await flagged.record(_evt("f2", "child-A"))
    await flagged.record(_evt("f3", "child-B"))

    runner = _make_runner(
        flagged, digest_store, channel, {"child-A": "parent-1", "child-B": "parent-2"}
    )
    digests = await runner.run_once(now=_NOW)

    assert len(digests) == 2
    child_ids = {d.child_id for d in digests}
    assert child_ids == {"child-A", "child-B"}


@pytest.mark.asyncio
async def test_run_once_digest_saved():
    """Digests are saved to DigestStore after run_once."""
    flagged = InMemoryFlaggedEventStore()
    digest_store = InMemoryDigestStore()
    channel = _FakeChannel()

    await flagged.record(_evt("f1", "child-A"))

    runner = _make_runner(flagged, digest_store, channel, {"child-A": "parent-1"})
    digests = await runner.run_once(now=_NOW)

    assert len(digests) == 1
    from app.digest.manual_runner import _epoch_to_date

    date_str = _epoch_to_date(_DAY_START)
    saved = await digest_store.get("child-A", date_str)
    assert saved is not None
    assert saved.total_flagged == 1


@pytest.mark.asyncio
async def test_run_once_delivered_once_per_child():
    """Each child gets exactly one push notification from run_once."""
    flagged = InMemoryFlaggedEventStore()
    digest_store = InMemoryDigestStore()
    channel = _FakeChannel()

    await flagged.record(_evt("f1", "child-A"))
    await flagged.record(_evt("f2", "child-A"))

    runner = _make_runner(flagged, digest_store, channel, {"child-A": "parent-1"})
    await runner.run_once(now=_NOW)

    assert len(channel.calls) == 1


@pytest.mark.asyncio
async def test_run_once_child_without_events_skipped():
    """A child with no events in the window is not included in run_once output."""
    flagged = InMemoryFlaggedEventStore()
    digest_store = InMemoryDigestStore()
    channel = _FakeChannel()

    # Event well BEFORE _DAY_START (yesterday) — outside today's window.
    await flagged.record(_evt("old", "child-A", created_at=_DAY_START - 3600))

    runner = _make_runner(flagged, digest_store, channel, {"child-A": "parent-1"})
    digests = await runner.run_once(now=_NOW)

    assert digests == []
    assert channel.calls == []


@pytest.mark.asyncio
async def test_run_once_child_without_parent_skipped():
    """A child with no parent mapping is skipped gracefully (no crash)."""
    flagged = InMemoryFlaggedEventStore()
    digest_store = InMemoryDigestStore()
    channel = _FakeChannel()

    await flagged.record(_evt("f1", "orphan-child"))

    # parent_map has no entry for "orphan-child"
    runner = _make_runner(flagged, digest_store, channel, {})
    digests = await runner.run_once(now=_NOW)

    assert digests == []
    assert channel.calls == []


@pytest.mark.asyncio
async def test_run_once_deterministic_with_injected_now():
    """run_once is deterministic when called twice with the same now."""
    flagged = InMemoryFlaggedEventStore()
    digest_store = InMemoryDigestStore()
    channel = _FakeChannel()

    await flagged.record(_evt("f1", "child-A"))

    runner = _make_runner(flagged, digest_store, channel, {"child-A": "parent-1"})

    digests1 = await runner.run_once(now=_NOW)
    digests2 = await runner.run_once(now=_NOW)

    # Both runs produce a digest with the same total.
    assert digests1[0].total_flagged == digests2[0].total_flagged
    # The second run overwrites the stored digest (INSERT OR REPLACE).
    from app.digest.manual_runner import _epoch_to_date

    saved = await digest_store.get("child-A", _epoch_to_date(_midnight_before(_NOW)))
    assert saved is not None
