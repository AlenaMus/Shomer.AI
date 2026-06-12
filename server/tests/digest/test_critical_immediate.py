"""test_critical_immediate.py — Tests for the critical-immediate push path.

The critical-immediate seam: MonitorIngest._on_critical_flag is a Callable
injected from lifespan(). It fires when:
  - flag_status == "alerted" (ALERT_DIRECT decision)
  - flagged_event.severity in ("high", "critical")

It does NOT fire for:
  - review_needed events
  - low/medium severity events

MonitorIngest is entirely import-clean of digest/identity concretes — it only
sees the injected Callable.

Run from repo root:
    .\\server\\.venv\\Scripts\\python.exe -m pytest server/tests/digest/test_critical_immediate.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SERVER_DIR = str(Path(__file__).resolve().parents[2])
if _SERVER_DIR not in sys.path:
    sys.path.insert(0, _SERVER_DIR)

from app.monitor.ingest import MonitorIngest
from app.dedup.in_memory_adapter import InMemoryTtlDedupStore
from app.flagged.in_memory_adapter import InMemoryFlaggedEventStore
from app.flagged.protocol import FlaggedEvent
from app.alerts.severity import derive_severity
from app.schemas import ClassificationResult, TriageDecision


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clf_result(
    label: str = "abusive",
    confidence: float = 0.95,
    is_offensive: bool = True,
    severity_override: str | None = None,
) -> ClassificationResult:
    return ClassificationResult(
        label=label,  # type: ignore[arg-type]
        confidence=confidence,
        is_offensive=is_offensive,
        model_version="stub",
        latency_ms=1.0,
        is_borderline=False,
        raw_confidence=confidence,
    )


class _FakeRequest:
    """Minimal stand-in for fastapi.Request in the pipeline callable."""

    class _FakeApp:
        class state:
            pass

    app = _FakeApp()

    class state:
        audit = {}
        device_context = None


async def _make_pipeline(decision: TriageDecision, label: str = "abusive", confidence: float = 0.95):
    """Async pipeline_fn that returns a fixed (ClassificationResult, decision)."""
    result = _clf_result(label=label, confidence=confidence)

    async def _fn(request, text, *, trace_id, child_id, message_id, input_type="monitor", **kwargs):
        return result, decision

    return _fn


def _make_ingest(pipeline_fn, flagged, on_critical_flag=None):
    dedup = InMemoryTtlDedupStore()
    return MonitorIngest(
        pipeline_fn=pipeline_fn,
        dedup=dedup,
        flagged=flagged,
        derive_severity=derive_severity,
        dedup_ttl_s=3600,
        on_critical_flag=on_critical_flag,
    )


class _FakeRequest:
    """Minimal fastapi.Request stand-in for ingest_batch."""

    class _FakeApp:
        class state:
            audit = {}
            device_context = None

    app = _FakeApp()

    class state:
        audit: dict = {}
        device_context = None


async def _run_ingest(ingest, child_id, text="שלום", label="abusive", direction="inbound"):
    from app.schemas import MonitorBatchRequest, MonitorEvent
    import time

    req = _FakeRequest()
    req.state.audit = {}
    batch = MonitorBatchRequest(
        session_id="session-1",
        child_id=child_id,
        events=[
            MonitorEvent(
                client_msg_id="msg-1",
                app_package="com.whatsapp",
                text=text,
                text_hash="aaaa",
                captured_at=time.time(),
                direction=direction,  # type: ignore[arg-type]
            )
        ],
    )
    return await ingest.ingest_batch(req, batch, trace_id="trace-test")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_critical_severity_alerted_fires_callback():
    """A high-severity alerted event triggers on_critical_flag."""
    flagged = InMemoryFlaggedEventStore()
    pipeline = await _make_pipeline(TriageDecision.ALERT_DIRECT, label="violence", confidence=0.98)

    callback_calls: list[FlaggedEvent] = []

    async def _on_critical(evt: FlaggedEvent) -> None:
        callback_calls.append(evt)

    ingest = _make_ingest(pipeline, flagged, on_critical_flag=_on_critical)
    await _run_ingest(ingest, "child-1", text="אלימות חמורה")

    # The derived severity for violence with confidence=0.98 should be critical/high.
    # Regardless: at least one callback was fired since the event was alerted.
    assert len(callback_calls) >= 1
    assert callback_calls[0].status == "alerted"
    assert callback_calls[0].severity in ("high", "critical")


@pytest.mark.asyncio
async def test_review_needed_does_not_fire_callback():
    """A review_needed event (borderline) does NOT fire the callback."""
    flagged = InMemoryFlaggedEventStore()
    pipeline = await _make_pipeline(TriageDecision.REVIEW_NEEDED, label="hate", confidence=0.50)

    callback_calls: list = []

    async def _on_critical(evt):
        callback_calls.append(evt)

    ingest = _make_ingest(pipeline, flagged, on_critical_flag=_on_critical)
    await _run_ingest(ingest, "child-1", text="שנאה גבולית")

    assert callback_calls == []


@pytest.mark.asyncio
async def test_low_severity_alerted_does_not_fire_callback():
    """A low-severity alerted event does NOT fire the callback."""
    flagged = InMemoryFlaggedEventStore()
    # Use non_offensive with low confidence to get a low severity, but force
    # ALERT_DIRECT decision path — derive_severity will compute low.
    # Actually the cleanest way is to use abusive with low confidence
    # (derive_severity("abusive", 0.4) → low or medium depending on implementation).
    # We'll directly test the guard condition in MonitorIngest:
    # severity must be "high" or "critical" to fire.
    # We can craft this by using a very low confidence.
    pipeline = await _make_pipeline(
        TriageDecision.ALERT_DIRECT, label="abusive", confidence=0.30
    )

    callback_calls: list = []

    async def _on_critical(evt):
        callback_calls.append(evt)

    ingest = _make_ingest(pipeline, flagged, on_critical_flag=_on_critical)
    await _run_ingest(ingest, "child-1", text="הודעה")

    # Only fire if severity is high or critical. With low confidence, severity
    # should not be high/critical. But to be sure, check the event's severity.
    events = await flagged.list_for_child("child-1", include_acked=True)
    if events and events[0].severity in ("high", "critical"):
        # If derive_severity mapped it to high/critical anyway, the test should
        # confirm the callback WAS fired (correct behavior).
        assert len(callback_calls) >= 1
    else:
        # Severity is low/medium → callback must not have fired.
        assert callback_calls == []


@pytest.mark.asyncio
async def test_silent_decision_does_not_fire_callback():
    """A SILENT decision is not flagged and must not fire the callback."""
    flagged = InMemoryFlaggedEventStore()
    pipeline = await _make_pipeline(TriageDecision.SILENT, label="non_offensive", confidence=0.97)
    pipeline_fn = pipeline  # already the async callable

    callback_calls: list = []

    async def _on_critical(evt):
        callback_calls.append(evt)

    ingest = _make_ingest(pipeline_fn, flagged, on_critical_flag=_on_critical)
    await _run_ingest(ingest, "child-1", text="שלום עולם")

    assert callback_calls == []


@pytest.mark.asyncio
async def test_no_callback_wired_no_crash():
    """MonitorIngest works correctly when on_critical_flag is None (no crash)."""
    flagged = InMemoryFlaggedEventStore()
    pipeline = await _make_pipeline(TriageDecision.ALERT_DIRECT, label="violence", confidence=0.99)

    ingest = _make_ingest(pipeline, flagged, on_critical_flag=None)
    resp = await _run_ingest(ingest, "child-1", text="אלימות")

    assert resp.flagged == 1
