"""test_digest_build.py — Unit tests for ManualDigestRunner.build_digest.

Covers:
  1. Correct total_flagged / review_needed counts from seeded events.
  2. by_severity and by_label aggregation.
  3. Events outside the window are excluded (strict [day_start, day_end) filter).
  4. Entries are capped at max_entries (most-severe-first sort).
  5. Empty window → zero totals.
  6. review_needed count includes only events with status="review_needed".

Run from repo root (not server/):
    .\\server\\.venv\\Scripts\\python.exe -m pytest server/tests/digest/test_digest_build.py -q
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest
import pytest_asyncio

# Ensure server/ is on sys.path.
_SERVER_DIR = str(Path(__file__).resolve().parents[2])
if _SERVER_DIR not in sys.path:
    sys.path.insert(0, _SERVER_DIR)

from app.digest.in_memory_store import InMemoryDigestStore
from app.digest.manual_runner import ManualDigestRunner
from app.flagged.in_memory_adapter import InMemoryFlaggedEventStore
from app.flagged.protocol import FlaggedEvent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = 1_700_000_000.0          # fixed "now" for all tests
_DAY_START = _NOW - 86400.0     # midnight-ish 24h before
_DAY_END = _NOW


def _evt(
    flag_id: str,
    child_id: str = "child-1",
    created_at: float = _NOW - 3600,
    label: str = "abusive",
    severity: str = "medium",
    status: str = "alerted",
    direction: str = "inbound",
) -> FlaggedEvent:
    return FlaggedEvent(
        flag_id=flag_id,
        child_id=child_id,
        created_at=created_at,
        app_package="com.whatsapp",
        direction=direction,
        label=label,  # type: ignore[arg-type]
        severity=severity,  # type: ignore[arg-type]
        quote="שלום",
        explanation="זוהתה הודעה פוגענית.",
        source="frontline_direct",
        trace_id="trace-" + flag_id,
        status=status,  # type: ignore[arg-type]
    )


async def _make_runner(flagged_store, parent_id="parent-1") -> ManualDigestRunner:
    """Build a ManualDigestRunner with stub callbacks."""
    digest_store = InMemoryDigestStore()
    notifier_calls: list = []

    class _FakeChannel:
        async def send_alert(self, req):
            notifier_calls.append(req)
            from app.schemas import AlertResult
            from datetime import datetime
            return AlertResult(alert_id="a1", sent=True, channel="stub")

        async def get_alert_history(self, *a, **kw):
            return []

        def health_status(self):
            return {"status": "ok", "queued_alerts": 0}

    async def _parent_for_child(child_id):
        return parent_id

    async def _fcm_token_for_parent(pid):
        return "fake-fcm-token"

    async def _active_child_ids(since):
        return await flagged_store.child_ids_with_events_since(since)

    return ManualDigestRunner(
        flagged=flagged_store,
        digest_store=digest_store,
        channel=_FakeChannel(),
        parent_for_child_fn=_parent_for_child,
        fcm_token_for_parent_fn=_fcm_token_for_parent,
        active_child_ids_fn=_active_child_ids,
        max_entries=50,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_digest_correct_totals():
    """build_digest returns correct total_flagged and review_needed."""
    flagged = InMemoryFlaggedEventStore()
    await flagged.record(_evt("f1", status="alerted", severity="high"))
    await flagged.record(_evt("f2", status="review_needed", severity="medium"))
    await flagged.record(_evt("f3", status="review_needed", severity="low"))

    runner = await _make_runner(flagged)
    digest = await runner.build_digest(
        "child-1", "parent-1", day_start=_DAY_START, day_end=_DAY_END
    )

    assert digest.total_flagged == 3
    assert digest.review_needed == 2
    assert digest.child_id == "child-1"
    assert digest.parent_id == "parent-1"


@pytest.mark.asyncio
async def test_build_digest_by_severity_and_label():
    """by_severity and by_label aggregation is correct."""
    flagged = InMemoryFlaggedEventStore()
    await flagged.record(_evt("f1", label="abusive", severity="high"))
    await flagged.record(_evt("f2", label="hate", severity="high"))
    await flagged.record(_evt("f3", label="abusive", severity="low"))

    runner = await _make_runner(flagged)
    digest = await runner.build_digest(
        "child-1", "parent-1", day_start=_DAY_START, day_end=_DAY_END
    )

    assert digest.by_severity == {"high": 2, "low": 1}
    assert digest.by_label == {"abusive": 2, "hate": 1}


@pytest.mark.asyncio
async def test_build_digest_excludes_events_outside_window():
    """Events created_at < day_start or >= day_end are excluded."""
    flagged = InMemoryFlaggedEventStore()
    # In-window event.
    await flagged.record(_evt("in-window", created_at=_NOW - 1000))
    # Before window (created_at < day_start).
    await flagged.record(_evt("before-window", created_at=_DAY_START - 1))
    # At or after day_end — excluded (strictly < day_end).
    await flagged.record(_evt("at-day-end", created_at=_DAY_END))
    await flagged.record(_evt("after-day-end", created_at=_DAY_END + 100))

    runner = await _make_runner(flagged)
    digest = await runner.build_digest(
        "child-1", "parent-1", day_start=_DAY_START, day_end=_DAY_END
    )

    assert digest.total_flagged == 1
    assert len(digest.entries) == 1
    assert digest.entries[0].flag_id == "in-window"


@pytest.mark.asyncio
async def test_build_digest_entries_capped_and_sorted_most_severe_first():
    """Entries are capped at max_entries and sorted most-severe-first."""
    flagged = InMemoryFlaggedEventStore()
    # 5 events: 2 critical, 1 high, 2 low
    for i in range(2):
        await flagged.record(_evt(f"crit-{i}", severity="critical", created_at=_NOW - 100 * (i + 1)))
    await flagged.record(_evt("high-0", severity="high", created_at=_NOW - 500))
    for i in range(2):
        await flagged.record(_evt(f"low-{i}", severity="low", created_at=_NOW - 600 * (i + 1)))

    # Cap at 3 entries to test truncation.
    runner = await _make_runner(flagged)
    runner._max_entries = 3

    digest = await runner.build_digest(
        "child-1", "parent-1", day_start=_DAY_START, day_end=_DAY_END
    )

    assert digest.total_flagged == 5
    assert len(digest.entries) == 3
    # All returned entries should be the highest-severity ones.
    severities = [e.severity for e in digest.entries]
    assert severities[0] == "critical"
    assert severities[1] == "critical"
    assert severities[2] == "high"


@pytest.mark.asyncio
async def test_build_digest_empty_window():
    """No events in window → zero totals, empty entries."""
    flagged = InMemoryFlaggedEventStore()
    # Event from yesterday (before window).
    await flagged.record(_evt("old", created_at=_DAY_START - 3600))

    runner = await _make_runner(flagged)
    digest = await runner.build_digest(
        "child-1", "parent-1", day_start=_DAY_START, day_end=_DAY_END
    )

    assert digest.total_flagged == 0
    assert digest.review_needed == 0
    assert digest.entries == []


@pytest.mark.asyncio
async def test_build_digest_review_needed_count():
    """Only events with status='review_needed' count toward review_needed."""
    flagged = InMemoryFlaggedEventStore()
    await flagged.record(_evt("a1", status="alerted"))
    await flagged.record(_evt("a2", status="acknowledged"))
    await flagged.record(_evt("a3", status="review_needed"))
    await flagged.record(_evt("a4", status="labeled"))

    runner = await _make_runner(flagged)
    digest = await runner.build_digest(
        "child-1", "parent-1", day_start=_DAY_START, day_end=_DAY_END
    )

    # include_acked=True so all 4 events are counted.
    assert digest.total_flagged == 4
    assert digest.review_needed == 1
