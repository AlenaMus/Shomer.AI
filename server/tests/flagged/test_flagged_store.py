"""Tests for the FlaggedEventStore port and adapters.

Parametrized over both InMemoryFlaggedEventStore and SqliteFlaggedEventStore
to prove they are drop-in swappable per the ≥2-adapter contract.

Covers:
  - record idempotency (first write wins)
  - list ordering (newest-first) + filters (since, include_acked, limit)
  - get
  - acknowledge
  - set_parent_label
  - health

Run from repo root:
    python -m pytest server/tests/flagged/test_flagged_store.py -q
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest
import pytest_asyncio

_SERVER_DIR = str(Path(__file__).resolve().parents[2])
if _SERVER_DIR not in sys.path:
    sys.path.insert(0, _SERVER_DIR)

from app.flagged import FlaggedEvent, FlaggedEventStore, InMemoryFlaggedEventStore
from app.flagged.sqlite_adapter import SqliteFlaggedEventStore
from app.schemas import HealthState


# ---------------------------------------------------------------------------
# Fixture: parametrized store
# ---------------------------------------------------------------------------


def _make_event(
    flag_id: str = "flag-001",
    child_id: str = "child-1",
    status: str = "alerted",
    created_at: float | None = None,
    label: str = "abusive",
) -> FlaggedEvent:
    return FlaggedEvent(
        flag_id=flag_id,
        child_id=child_id,
        created_at=created_at or time.time(),
        app_package="com.whatsapp",
        direction="inbound",
        label=label,  # type: ignore[arg-type]
        severity="medium",  # type: ignore[arg-type]
        quote="הודעה פוגענית לדוגמה",
        explanation="זוהתה הודעה פוגענית מסוג abusive.",
        source="frontline_direct",  # type: ignore[arg-type]
        trace_id="trace-001",
        status=status,  # type: ignore[arg-type]
    )


@pytest_asyncio.fixture(params=["memory", "sqlite"])
async def store(request, tmp_path) -> FlaggedEventStore:
    """Yield a FlaggedEventStore implementation (parametrized)."""
    if request.param == "sqlite":
        db_path = str(tmp_path / "flagged_test.db")
        s = SqliteFlaggedEventStore(db_path=db_path)
        await s.initialize()
        yield s
        await s.close()
    else:
        yield InMemoryFlaggedEventStore()


# ---------------------------------------------------------------------------
# Tests (shared semantics — run against both adapters)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_and_get(store):
    evt = _make_event("f-001")
    await store.record(evt)
    retrieved = await store.get("f-001")
    assert retrieved is not None
    assert retrieved.flag_id == "f-001"
    assert retrieved.child_id == "child-1"
    assert retrieved.label == "abusive"


@pytest.mark.asyncio
async def test_record_idempotent(store):
    """Second record() with same flag_id is a no-op (first write wins)."""
    evt1 = _make_event("f-002", label="abusive")
    evt2 = FlaggedEvent(
        **{**evt1.__dict__, "label": "hate"}  # type: ignore[arg-type]
    )
    await store.record(evt1)
    await store.record(evt2)  # must be ignored

    retrieved = await store.get("f-002")
    assert retrieved is not None
    assert retrieved.label == "abusive"  # first write preserved


@pytest.mark.asyncio
async def test_get_returns_none_for_unknown(store):
    result = await store.get("nonexistent-flag-id")
    assert result is None


@pytest.mark.asyncio
async def test_list_for_child_newest_first(store):
    """Events returned newest-first (descending created_at)."""
    now = time.time()
    await store.record(_make_event("f-101", created_at=now - 200, status="alerted"))
    await store.record(_make_event("f-102", created_at=now - 100, status="alerted"))
    await store.record(_make_event("f-103", created_at=now, status="alerted"))

    events = await store.list_for_child("child-1")
    assert [e.flag_id for e in events] == ["f-103", "f-102", "f-101"]


@pytest.mark.asyncio
async def test_list_filter_since(store):
    now = time.time()
    await store.record(_make_event("f-201", created_at=now - 1000, status="alerted"))
    await store.record(_make_event("f-202", created_at=now, status="alerted"))

    events = await store.list_for_child("child-1", since=now - 500)
    assert len(events) == 1
    assert events[0].flag_id == "f-202"


@pytest.mark.asyncio
async def test_list_excludes_acked_by_default(store):
    now = time.time()
    await store.record(_make_event("f-301", status="alerted"))
    await store.record(_make_event("f-302", status="acknowledged"))

    events = await store.list_for_child("child-1")
    flag_ids = {e.flag_id for e in events}
    assert "f-301" in flag_ids
    assert "f-302" not in flag_ids


@pytest.mark.asyncio
async def test_list_includes_acked_when_requested(store):
    await store.record(_make_event("f-401", status="alerted"))
    await store.record(_make_event("f-402", status="acknowledged"))

    events = await store.list_for_child("child-1", include_acked=True)
    flag_ids = {e.flag_id for e in events}
    assert "f-401" in flag_ids
    assert "f-402" in flag_ids


@pytest.mark.asyncio
async def test_list_limit(store):
    now = time.time()
    for i in range(5):
        await store.record(_make_event(f"f-lim-{i}", created_at=now + i, status="alerted"))

    events = await store.list_for_child("child-1", limit=3)
    assert len(events) == 3


@pytest.mark.asyncio
async def test_list_child_isolation(store):
    """list_for_child only returns events for that specific child."""
    await store.record(_make_event("f-501", child_id="child-A"))
    await store.record(_make_event("f-502", child_id="child-B"))

    events_a = await store.list_for_child("child-A")
    events_b = await store.list_for_child("child-B")

    assert all(e.child_id == "child-A" for e in events_a)
    assert all(e.child_id == "child-B" for e in events_b)


@pytest.mark.asyncio
async def test_acknowledge(store):
    await store.record(_make_event("f-601", status="alerted"))

    result = await store.acknowledge("f-601", parent_id="parent-1")
    assert result is True

    updated = await store.get("f-601")
    assert updated.status == "acknowledged"
    assert updated.acknowledged_at is not None


@pytest.mark.asyncio
async def test_acknowledge_not_found(store):
    result = await store.acknowledge("nonexistent", parent_id="parent-1")
    assert result is False


@pytest.mark.asyncio
async def test_set_parent_label(store):
    await store.record(_make_event("f-701", status="review_needed"))

    result = await store.set_parent_label("f-701", label="hate", severity="high")
    assert result is True

    updated = await store.get("f-701")
    assert updated.status == "labeled"
    assert updated.parent_label == "hate"
    assert updated.parent_severity == "high"


@pytest.mark.asyncio
async def test_set_parent_label_not_found(store):
    result = await store.set_parent_label("nonexistent", label="hate", severity=None)
    assert result is False


@pytest.mark.asyncio
async def test_health_returns_ok(store):
    await store.record(_make_event("f-801"))
    state, detail = await store.health()
    assert state == HealthState.OK


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


def test_inmemory_is_flagged_event_store():
    s = InMemoryFlaggedEventStore()
    assert isinstance(s, FlaggedEventStore)


def test_sqlite_is_flagged_event_store(tmp_path):
    db = str(tmp_path / "conform.db")
    s = SqliteFlaggedEventStore(db_path=db)
    assert isinstance(s, FlaggedEventStore)
