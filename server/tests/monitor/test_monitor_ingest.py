"""Tests for MonitorIngest and the POST /v1/monitor/events endpoint.

Uses stub collaborators so the tests are fast, offline, and deterministic.

Batch scenarios tested:
  1. Offensive event → ack "processed", flagged=True, status="alerted".
  2. Benign event    → ack "processed", flagged=False.
  3. Duplicate of #1 → ack "deduped" (dedup kicks in).
  4. Borderline / violence event → ack "processed", flagged=True, status="review_needed".
  5. Error event (pipeline raises) → ack "error" without failing the batch.

Also covers the FastAPI TestClient integration route
(POST /v1/monitor/events → MonitorBatchResponse).

Run from repo root:
    python -m pytest server/tests/monitor/test_monitor_ingest.py -q
"""

from __future__ import annotations

import sys
import time
import uuid
from pathlib import Path

import pytest
import pytest_asyncio

_SERVER_DIR = str(Path(__file__).resolve().parents[2])
if _SERVER_DIR not in sys.path:
    sys.path.insert(0, _SERVER_DIR)

from app.dedup import InMemoryTtlDedupStore
from app.flagged import FlaggedEvent, InMemoryFlaggedEventStore
from app.monitor.ingest import MonitorIngest
from app.schemas import (
    ClassificationResult,
    MonitorBatchRequest,
    MonitorEvent,
    TriageDecision,
)
from app.alerts.severity import derive_severity


# ---------------------------------------------------------------------------
# Stub collaborators
# ---------------------------------------------------------------------------


def _make_result(
    label: str = "non_offensive",
    confidence: float = 0.95,
    is_offensive: bool = False,
    error: bool = False,
) -> ClassificationResult:
    return ClassificationResult(
        label=label,  # type: ignore[arg-type]
        confidence=confidence,
        is_offensive=is_offensive,
        model_version="stub-test",
        latency_ms=1.0,
        is_borderline=False,
        raw_confidence=confidence,
        error=error,
    )


# Canned classifier results for each scenario.
_OFFENSIVE_RESULT = _make_result("abusive", 0.97, True)
_BENIGN_RESULT = _make_result("non_offensive", 0.95, False)
_BORDERLINE_RESULT = _make_result("violence", 0.97, True)  # always_escalate
_ERROR_RESULT = _make_result("non_offensive", 0.5, False, error=True)

# Corresponding triage decisions.
_OFFENSIVE_DECISION = TriageDecision.ALERT_DIRECT
_BENIGN_DECISION = TriageDecision.SILENT
_BORDERLINE_DECISION = TriageDecision.ESCALATE_TO_CA
_ERROR_DECISION = TriageDecision.REVIEW_NEEDED


class _StubPipeline:
    """Fake _run_pipeline: returns preset (result, decision) per call index."""

    def __init__(self, responses: list[tuple]) -> None:
        # responses: list of (ClassificationResult, TriageDecision) or Exception
        self._responses = responses
        self._call_index = 0

    async def __call__(self, request, text, *, trace_id, child_id, message_id, input_type, **kwargs):
        resp = self._responses[self._call_index % len(self._responses)]
        self._call_index += 1
        if isinstance(resp, Exception):
            raise resp
        return resp


class _FakeRequest:
    """Minimal FastAPI-like Request stub accepted by MonitorIngest."""

    def __init__(self, dedup, flagged) -> None:
        class _State:
            audit: dict = {}

        class _App:
            state: _State

        self.state = _State()
        self.app = _App()
        self.app.state = _State()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(
    client_msg_id: str = "msg-001",
    text: str = "שלום עולם",
    text_hash: str | None = None,
    app_package: str = "com.whatsapp",
    direction: str = "inbound",
) -> MonitorEvent:
    return MonitorEvent(
        client_msg_id=client_msg_id,
        app_package=app_package,
        text=text,
        text_hash=text_hash or f"hash-{client_msg_id}",
        captured_at=time.time(),
        direction=direction,
    )


def _make_batch(child_id: str, events: list[MonitorEvent]) -> MonitorBatchRequest:
    return MonitorBatchRequest(
        session_id="session-001",
        child_id=child_id,
        events=events,
    )


# ---------------------------------------------------------------------------
# Core ingest batch tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_offensive_flagged_as_alerted():
    """Offensive event (ALERT_DIRECT) → ack status=processed, flagged=True, flag in store."""
    dedup = InMemoryTtlDedupStore()
    flagged_store = InMemoryFlaggedEventStore()
    pipeline = _StubPipeline([(_OFFENSIVE_RESULT, _OFFENSIVE_DECISION)])

    ingest = MonitorIngest(
        pipeline_fn=pipeline,
        dedup=dedup,
        flagged=flagged_store,
        derive_severity=derive_severity,
    )

    child_id = "child-test-001"
    event = _make_event("msg-001", "אתה טמבל")
    batch = _make_batch(child_id, [event])
    request = _FakeRequest(dedup, flagged_store)

    response = await ingest.ingest_batch(request, batch, trace_id="trace-test-001")

    assert response.accepted == 1
    assert response.deduped == 0
    assert response.flagged == 1
    assert len(response.acks) == 1

    ack = response.acks[0]
    assert ack.client_msg_id == "msg-001"
    assert ack.status == "processed"
    assert ack.flagged is True
    assert ack.flag_id is not None

    # FlaggedEventStore must have one record.
    events = await flagged_store.list_for_child(child_id, include_acked=True)
    assert len(events) == 1
    assert events[0].status == "alerted"
    assert events[0].label == "abusive"


@pytest.mark.asyncio
async def test_batch_benign_not_flagged():
    """Benign event (SILENT) → ack processed, not flagged, nothing in store."""
    dedup = InMemoryTtlDedupStore()
    flagged_store = InMemoryFlaggedEventStore()
    pipeline = _StubPipeline([(_BENIGN_RESULT, _BENIGN_DECISION)])

    ingest = MonitorIngest(
        pipeline_fn=pipeline,
        dedup=dedup,
        flagged=flagged_store,
        derive_severity=derive_severity,
    )

    child_id = "child-test-002"
    event = _make_event("msg-002", "שלום עולם")
    batch = _make_batch(child_id, [event])
    request = _FakeRequest(dedup, flagged_store)

    response = await ingest.ingest_batch(request, batch, trace_id="trace-test-002")

    assert response.accepted == 1
    assert response.flagged == 0
    ack = response.acks[0]
    assert ack.status == "processed"
    assert ack.flagged is False
    assert ack.flag_id is None

    events = await flagged_store.list_for_child(child_id)
    assert len(events) == 0


@pytest.mark.asyncio
async def test_batch_duplicate_is_deduped():
    """Sending the same (child_id, text_hash) twice → second is deduped."""
    dedup = InMemoryTtlDedupStore()
    flagged_store = InMemoryFlaggedEventStore()
    # Pipeline only called for first event; second is deduped before pipeline.
    pipeline = _StubPipeline([(_OFFENSIVE_RESULT, _OFFENSIVE_DECISION)])

    ingest = MonitorIngest(
        pipeline_fn=pipeline,
        dedup=dedup,
        flagged=flagged_store,
        derive_severity=derive_severity,
    )

    child_id = "child-test-003"
    same_hash = "same-hash-xyz"
    event1 = _make_event("msg-003a", "הודעה פוגענית", text_hash=same_hash)
    event2 = _make_event("msg-003b", "הודעה פוגענית", text_hash=same_hash)
    batch = _make_batch(child_id, [event1, event2])
    request = _FakeRequest(dedup, flagged_store)

    response = await ingest.ingest_batch(request, batch, trace_id="trace-test-003")

    assert response.accepted == 1   # only event1 processed
    assert response.deduped == 1    # event2 deduped
    assert response.flagged == 1

    acks = {a.client_msg_id: a for a in response.acks}
    assert acks["msg-003a"].status == "processed"
    assert acks["msg-003b"].status == "deduped"

    # Exactly one entry in the flagged store.
    events = await flagged_store.list_for_child(child_id)
    assert len(events) == 1


@pytest.mark.asyncio
async def test_batch_borderline_flagged_as_review_needed():
    """Borderline / ESCALATE_TO_CA → status=review_needed."""
    dedup = InMemoryTtlDedupStore()
    flagged_store = InMemoryFlaggedEventStore()
    pipeline = _StubPipeline([(_BORDERLINE_RESULT, _BORDERLINE_DECISION)])

    ingest = MonitorIngest(
        pipeline_fn=pipeline,
        dedup=dedup,
        flagged=flagged_store,
        derive_severity=derive_severity,
    )

    child_id = "child-test-004"
    event = _make_event("msg-004", "אשבור לך את הראש")
    batch = _make_batch(child_id, [event])
    request = _FakeRequest(dedup, flagged_store)

    response = await ingest.ingest_batch(request, batch, trace_id="trace-test-004")

    assert response.flagged == 1
    ack = response.acks[0]
    assert ack.flagged is True
    assert ack.status == "processed"

    events = await flagged_store.list_for_child(child_id)
    assert len(events) == 1
    assert events[0].status == "review_needed"


@pytest.mark.asyncio
async def test_batch_error_event_acks_error_without_failing_batch():
    """A pipeline that raises should ack 'error' and not abort the rest of the batch."""
    dedup = InMemoryTtlDedupStore()
    flagged_store = InMemoryFlaggedEventStore()

    class _ErrorPipeline:
        async def __call__(self, request, text, *, trace_id, child_id, message_id, input_type, **kwargs):
            raise RuntimeError("simulated pipeline failure")

    ingest = MonitorIngest(
        pipeline_fn=_ErrorPipeline(),
        dedup=dedup,
        flagged=flagged_store,
        derive_severity=derive_severity,
    )

    child_id = "child-test-005"
    event = _make_event("msg-005", "כלשהו")
    batch = _make_batch(child_id, [event])
    request = _FakeRequest(dedup, flagged_store)

    # Must not raise.
    response = await ingest.ingest_batch(request, batch, trace_id="trace-test-005")

    # The event errored but the batch completed.
    assert len(response.acks) == 1
    assert response.acks[0].status == "error"
    # accepted/flagged are 0; deduped is 0.
    assert response.accepted == 0
    assert response.flagged == 0


@pytest.mark.asyncio
async def test_mixed_batch_four_events():
    """Full mixed batch: offensive + benign + duplicate + borderline."""
    dedup = InMemoryTtlDedupStore()
    flagged_store = InMemoryFlaggedEventStore()

    # Responses for the 3 pipeline calls (duplicate is deduped — not called).
    pipeline = _StubPipeline([
        (_OFFENSIVE_RESULT, _OFFENSIVE_DECISION),    # event 1: offensive
        (_BENIGN_RESULT, _BENIGN_DECISION),          # event 2: benign
        # event 3: duplicate of event 1 — pipeline NOT called
        (_BORDERLINE_RESULT, _BORDERLINE_DECISION),  # event 4: borderline
    ])

    ingest = MonitorIngest(
        pipeline_fn=pipeline,
        dedup=dedup,
        flagged=flagged_store,
        derive_severity=derive_severity,
    )

    child_id = "child-mixed"
    shared_hash = "hash-offensive"

    events = [
        _make_event("msg-A", "הודעה פוגענית", text_hash=shared_hash),
        _make_event("msg-B", "שלום חבר"),
        _make_event("msg-C", "הודעה פוגענית", text_hash=shared_hash),   # duplicate of A
        _make_event("msg-D", "אשבור לך את הראש"),
    ]
    batch = _make_batch(child_id, events)
    request = _FakeRequest(dedup, flagged_store)

    response = await ingest.ingest_batch(request, batch, trace_id="trace-mixed")

    assert response.accepted == 3   # A, B, D
    assert response.deduped == 1    # C
    assert response.flagged == 2    # A (alerted) + D (review_needed)

    acks = {a.client_msg_id: a for a in response.acks}
    assert acks["msg-A"].status == "processed" and acks["msg-A"].flagged
    assert acks["msg-B"].status == "processed" and not acks["msg-B"].flagged
    assert acks["msg-C"].status == "deduped"
    assert acks["msg-D"].status == "processed" and acks["msg-D"].flagged

    flagged_events = await flagged_store.list_for_child(child_id, include_acked=True)
    assert len(flagged_events) == 2
    statuses = {e.status for e in flagged_events}
    assert statuses == {"alerted", "review_needed"}


# ---------------------------------------------------------------------------
# FastAPI TestClient integration test
# ---------------------------------------------------------------------------


def test_monitor_endpoint_via_testclient(monkeypatch, tmp_path):
    """POST /v1/monitor/events via FastAPI TestClient → 202 + correct counts.

    Uses the real lifespan (InMemoryFlaggedEventStore + InMemoryTtlDedupStore)
    and overrides app.state.classifier with a stub after startup.

    S2 auth change: this test uses a real InMemoryIdentityStore seeded with a
    valid child token.  The monitor endpoint now enforces auth when an identity
    store is present.  We go through the full pairing flow in the test so the
    device token is valid.  Alternatively, to keep a test auth-free, clear
    app.state.identity = None after startup — but the pairing flow is the
    more realistic path and validates the wiring end-to-end.
    """
    import asyncio
    from fastapi.testclient import TestClient
    from app.main import app
    from app.identity import InMemoryIdentityStore
    from app.schemas import ClassificationResult

    class _FixedClassifier:
        model_version = "stub-test"
        backend_name = "stub-test"

        async def classify(self, text: str) -> ClassificationResult:
            return _OFFENSIVE_RESULT

        async def health(self):
            from app.schemas import HealthState
            return (HealthState.OK, "stub")

    monkeypatch.setenv("AUDIT_DB_PATH", str(tmp_path / "test_audit.db"))
    monkeypatch.setenv("CONTEXT_AGENT_ENABLED", "false")
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "99999")
    monkeypatch.setenv("IDENTITY_BACKEND", "memory")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    # Build an InMemoryIdentityStore and seed it with a valid pairing.
    identity_store = InMemoryIdentityStore()

    async def _setup_identity():
        parent_id, _ = await identity_store.register_parent()
        child = await identity_store.issue_child(parent_id, "Test Child")
        pc = await identity_store.create_pairing_code(parent_id, child.child_id)
        ctx = await identity_store.redeem_pairing_code(pc.code, "fp-test")
        return child.child_id, ctx.device_token

    loop = asyncio.new_event_loop()
    try:
        child_id, device_token = loop.run_until_complete(_setup_identity())
    finally:
        loop.close()

    trace_id = f"trace-endpoint-{uuid.uuid4().hex[:8]}"

    with TestClient(app, raise_server_exceptions=True) as client:
        app.state.classifier = _FixedClassifier()
        app.state.context_agent = None
        # Inject the pre-seeded identity store (overrides the one built by lifespan()).
        app.state.identity = identity_store

        payload = {
            "session_id": "session-01",
            "child_id": child_id,
            "events": [
                {
                    "client_msg_id": "msg-e-001",
                    "app_package": "com.whatsapp",
                    "text": "אתה טמבל",
                    "text_hash": "hash-e-001",
                    "captured_at": time.time(),
                    "direction": "inbound",
                }
            ],
        }
        resp = client.post(
            "/v1/monitor/events",
            json=payload,
            headers={
                "X-Trace-Id": trace_id,
                "Authorization": f"Bearer {device_token}",
            },
        )

    assert resp.status_code == 202, f"Expected 202, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert body["accepted"] == 1
    assert body["deduped"] == 0
    assert body["flagged"] == 1
    assert len(body["acks"]) == 1
    assert body["acks"][0]["status"] == "processed"
    assert body["acks"][0]["flagged"] is True


def test_monitor_endpoint_empty_child_id_returns_400(monkeypatch, tmp_path):
    """child_id with only whitespace should return HTTP 400.

    S2 note: auth is disabled for this test (app.state.identity = None) so we
    can isolate the validation check.  The auth-enforcing path is tested
    separately in server/tests/identity/test_auth_middleware.py.
    """
    from fastapi.testclient import TestClient
    from app.main import app

    monkeypatch.setenv("AUDIT_DB_PATH", str(tmp_path / "test_audit.db"))
    monkeypatch.setenv("CONTEXT_AGENT_ENABLED", "false")
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "99999")
    monkeypatch.setenv("IDENTITY_BACKEND", "memory")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with TestClient(app, raise_server_exceptions=True) as client:
        # Disable auth so we can reach the child_id validation.
        app.state.identity = None

        payload = {
            "session_id": "s",
            "child_id": "   ",
            "events": [
                {
                    "client_msg_id": "m",
                    "app_package": "com.test",
                    "text": "שלום",
                    "text_hash": "h",
                    "captured_at": time.time(),
                }
            ],
        }
        resp = client.post("/v1/monitor/events", json=payload)

    assert resp.status_code == 400
