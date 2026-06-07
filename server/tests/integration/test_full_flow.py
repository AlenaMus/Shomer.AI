"""Deterministic integration tests for the full Shomer.AI classification pipeline.

Uses FastAPI's TestClient so the real lifespan() composition root runs, wiring
the real SqliteAuditStore (pointed at a tmp DB), real ThresholdTriageEngine, and
real StubNotifier / stub classifier.  Every test sends an X-Trace-Id header for
deterministic DB row lookup.

Test coverage:
  1. SILENT                  — non-offensive, high confidence
  2. ALERT_DIRECT            — offensive, high confidence → StubNotifier receives alert
  3. ESCALATE_TO_CA          — borderline (prob_offensive in borderline zone)
  4. REVIEW_NEEDED           — classifier error flag
  5. Conversation persistence — two calls with the same child_id → two turns
  6. pornographic override   — always_alert regardless of confidence
  7. violence + CA enabled   — always_escalate_to_ca override

NOTE — WIRING BUG FOUND (do not fix here, per spec):
  ``main.py._run_pipeline`` calls ``context_agent.evaluate()`` and uses the
  returned ``ContextDecision``, but NEVER calls
  ``audit_store.record_agent_trace()``.  Therefore the ``agent_traces`` table
  is always empty after a CA evaluation.  Tests that touch the ESCALATE_TO_CA
  branch assert on the classification row (which IS written) and explicitly
  document this gap.  See the inline comment in test_escalate_to_ca.
"""

from __future__ import annotations

import os
import sqlite3
import sys
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

# Ensure server/ is on sys.path so ``app`` is importable (mirrors conftest.py).
_SERVER_DIR = str(Path(__file__).resolve().parents[2])
if _SERVER_DIR not in sys.path:
    sys.path.insert(0, _SERVER_DIR)

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.schemas import ClassificationResult, TriageDecision  # noqa: E402
from app.alerts import StubNotifier  # noqa: E402


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _make_result(
    label: str = "non_offensive",
    confidence: float = 0.95,
    is_offensive: bool = False,
    error: bool = False,
) -> ClassificationResult:
    """Build a ClassificationResult for stub injection."""
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


class _StubClassifier:
    """Minimal TextClassifier stub: always returns a preset ClassificationResult."""

    def __init__(self, result: ClassificationResult) -> None:
        self._result = result
        self.model_version = "stub-test"
        self.backend_name = "stub-test"

    async def classify(self, text: str) -> ClassificationResult:  # noqa: ARG002
        return self._result

    async def health(self):
        from app.schemas import HealthState
        return (HealthState.OK, "stub")


def _query(db_path: str, sql: str, params: tuple = ()) -> list[dict]:
    """Run a read-only SELECT against the temp DB; return list-of-dicts."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Shared fixture: real lifespan with a temp DB + StubNotifier
# --------------------------------------------------------------------------- #


@pytest.fixture
def tmp_db(tmp_path) -> str:
    """Return path to a temporary audit DB file (does not create it)."""
    return str(tmp_path / "test_audit.db")


@pytest.fixture
def full_client(tmp_db, monkeypatch):
    """
    A TestClient that uses the real lifespan() composition root but with:
      - AUDIT_DB_PATH pointing to a temp SQLite file
      - CONTEXT_AGENT_ENABLED=true (so the CA is constructed — uses MockLlmClient
        because no API keys are set in the test environment)
      - All LLM-key env vars cleared so MockLlmClient is always selected
      - Rate limits disabled on the Gatekeeper

    After ``lifespan()`` runs, yields (client, db_path, stub_notifier).
    The stub_notifier is swapped in AFTER startup so it captures every
    send_alert() call made during the test.
    """
    monkeypatch.setenv("AUDIT_DB_PATH", tmp_db)
    monkeypatch.setenv("CONTEXT_AGENT_ENABLED", "true")
    # Clear real API keys so MockLlmClient is always chosen.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    # Disable gatekeeper rate limiting so test requests are never throttled.
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "99999")

    stub_notifier = StubNotifier()

    with TestClient(app, raise_server_exceptions=True) as client:
        # Swap to StubNotifier AFTER lifespan() has constructed everything.
        # This is the documented test seam: app.state.* is reassignable.
        app.state.notifier = stub_notifier
        yield client, tmp_db, stub_notifier


# --------------------------------------------------------------------------- #
# Test 1: SILENT branch
# --------------------------------------------------------------------------- #


def test_silent_branch(full_client):
    """
    Classifier returns non_offensive, conf=0.95 → prob_offensive=0.05 → SILENT.
    No alert dispatched.  classification row persisted with triage_decision=silent.
    """
    client, db_path, notifier = full_client
    trace_id = f"test-silent-{uuid.uuid4().hex[:8]}"

    # Override classifier to return a clean result.
    app.state.classifier = _StubClassifier(_make_result("non_offensive", 0.95, False))

    resp = client.post(
        "/classify",
        json={"text": "שלום עולם מה שלומך"},
        headers={"X-Trace-Id": trace_id},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_offensive"] is False
    assert body["category"] == "non_offensive"

    # No alert should have been dispatched.
    assert len(notifier.requests) == 0

    # DB must have a classification row with triage_decision=silent.
    rows = _query(
        db_path,
        "SELECT triage_decision, classifier_label FROM classifications WHERE trace_id=?",
        (trace_id,),
    )
    assert len(rows) == 1, f"Expected 1 classification row, got {len(rows)}"
    assert rows[0]["triage_decision"] == TriageDecision.SILENT.value
    assert rows[0]["classifier_label"] == "non_offensive"


# --------------------------------------------------------------------------- #
# Test 2: ALERT_DIRECT + StubNotifier captures call + alerts row in DB
# --------------------------------------------------------------------------- #


def test_alert_direct_branch(full_client):
    """
    Classifier returns abusive, conf=0.97 → prob_offensive=0.97 ≥ 0.7 → ALERT_DIRECT.
    StubNotifier receives exactly one send_alert() call.
    Since StubNotifier has no audit_recorder, the alerts table is NOT written
    through the notifier.  However the classification row is written with
    triage_decision=alert_direct.
    """
    client, db_path, notifier = full_client
    trace_id = f"test-alert-{uuid.uuid4().hex[:8]}"
    child_id = f"child-{uuid.uuid4().hex[:8]}"

    app.state.classifier = _StubClassifier(
        _make_result("abusive", 0.97, True)
    )
    # Disable context agent for this test — direct alert path.
    app.state.context_agent = None

    resp = client.post(
        "/classify",
        json={"text": "אתה טמבל מטומטם", "child_id": child_id},
        headers={"X-Trace-Id": trace_id},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_offensive"] is True
    assert body["category"] == "abusive"

    # StubNotifier must have been called exactly once.
    assert len(notifier.requests) == 1, (
        f"Expected 1 alert call, got {len(notifier.requests)}"
    )
    alert_req = notifier.requests[0]
    assert alert_req.label == "abusive"
    assert alert_req.child_id == child_id
    assert alert_req.trace_id == trace_id

    # The result returned by StubNotifier had sent=True.
    assert notifier._history[0].sent is True

    # DB: classification row triage_decision=alert_direct.
    rows = _query(
        db_path,
        "SELECT triage_decision, classifier_label FROM classifications WHERE trace_id=?",
        (trace_id,),
    )
    assert len(rows) == 1
    assert rows[0]["triage_decision"] == TriageDecision.ALERT_DIRECT.value
    assert rows[0]["classifier_label"] == "abusive"


# --------------------------------------------------------------------------- #
# Test 3: ESCALATE_TO_CA branch
# --------------------------------------------------------------------------- #


def test_escalate_to_ca_branch(full_client):
    """
    Classifier returns abusive, is_offensive=True, conf=0.5 →
    prob_offensive=0.5, which is in the borderline zone (0.3, 0.7) and NOT in
    the always_escalate / always_alert label sets for 'abusive'.
    With context_agent_enabled=True (real MockLlmClient) the branch escalates.

    The MockLlmClient returns a deterministic 'not_threat' response, so the
    final triage_decision after CA evaluation = SILENT (CA says safe).

    The CA reasoning trace is persisted via record_agent_trace() in
    _run_pipeline (main.py), so the agent_traces table has a row for this
    escalated request, correlated by trace_id.
    """
    client, db_path, notifier = full_client
    trace_id = f"test-ca-{uuid.uuid4().hex[:8]}"

    # Borderline: is_offensive=True, confidence=0.5 → prob_offensive=0.5
    # The triage engine will route to ESCALATE_TO_CA because 0.3 < 0.5 < 0.7
    # and the label 'abusive' is not in always_escalate or always_alert sets.
    app.state.classifier = _StubClassifier(
        _make_result("abusive", 0.5, True)
    )
    # Ensure CA is active (set in the fixture, using MockLlmClient).
    assert app.state.context_agent is not None, (
        "Expected context_agent to be wired (MockLlmClient). "
        "Check that CONTEXT_AGENT_ENABLED=true in the test fixture."
    )

    resp = client.post(
        "/classify",
        json={"text": "טקסט גבולי לבדיקה"},
        headers={"X-Trace-Id": trace_id},
    )
    assert resp.status_code == 200

    # The classification row must exist.
    cls_rows = _query(
        db_path,
        "SELECT triage_decision, frontline_only_decision FROM classifications WHERE trace_id=?",
        (trace_id,),
    )
    assert len(cls_rows) == 1, (
        f"Expected 1 classification row, got {len(cls_rows)}"
    )
    # The frontline decision was escalate_to_ca (before CA ran).
    assert cls_rows[0]["frontline_only_decision"] == TriageDecision.ESCALATE_TO_CA.value

    # The CA reasoning trace is persisted (record_agent_trace wired in main.py).
    agent_rows = _query(
        db_path,
        "SELECT COUNT(*) as n FROM agent_traces WHERE trace_id=?",
        (trace_id,),
    )
    assert agent_rows[0]["n"] >= 1, (
        "Expected an agent_traces row for the escalated request — "
        "record_agent_trace() should be called in _run_pipeline after CA evaluation."
    )

    # No alert should have fired (MockLlmClient resolves to 'not_threat' → SILENT).
    assert len(notifier.requests) == 0


# --------------------------------------------------------------------------- #
# Test 4: REVIEW_NEEDED branch
# --------------------------------------------------------------------------- #


def test_review_needed_branch(full_client):
    """
    Classifier returns error=True → triage routes to REVIEW_NEEDED.
    No alert dispatched.
    """
    client, db_path, notifier = full_client
    trace_id = f"test-review-{uuid.uuid4().hex[:8]}"

    app.state.classifier = _StubClassifier(
        _make_result("non_offensive", 0.5, False, error=True)
    )

    resp = client.post(
        "/classify",
        json={"text": "שגיאה בסיווג"},
        headers={"X-Trace-Id": trace_id},
    )
    assert resp.status_code == 200

    # No alert fired.
    assert len(notifier.requests) == 0

    rows = _query(
        db_path,
        "SELECT triage_decision FROM classifications WHERE trace_id=?",
        (trace_id,),
    )
    assert len(rows) == 1
    assert rows[0]["triage_decision"] == TriageDecision.REVIEW_NEEDED.value


# --------------------------------------------------------------------------- #
# Test 5: Conversation persistence — two turns for same child_id
# --------------------------------------------------------------------------- #


def test_conversation_persistence(full_client):
    """
    Two /classify calls with the same child_id must persist two conversation
    turns in the conversations table, and read_conversation_history returns them
    in ascending turn_index order.
    """
    client, db_path, notifier = full_client
    child_id = f"conv-child-{uuid.uuid4().hex[:8]}"

    app.state.classifier = _StubClassifier(_make_result("non_offensive", 0.95, False))

    trace1 = f"test-conv-1-{uuid.uuid4().hex[:8]}"
    trace2 = f"test-conv-2-{uuid.uuid4().hex[:8]}"

    resp1 = client.post(
        "/classify",
        json={"text": "הודעה ראשונה", "child_id": child_id},
        headers={"X-Trace-Id": trace1},
    )
    assert resp1.status_code == 200

    resp2 = client.post(
        "/classify",
        json={"text": "הודעה שנייה", "child_id": child_id},
        headers={"X-Trace-Id": trace2},
    )
    assert resp2.status_code == 200

    # Two conversation turns in DB, ordered by turn_index ASC.
    turns = _query(
        db_path,
        """
        SELECT turn_index, text FROM conversations
        WHERE child_id = ?
        ORDER BY turn_index ASC
        """,
        (child_id,),
    )
    assert len(turns) == 2, f"Expected 2 conversation turns, got {len(turns)}"
    assert turns[0]["turn_index"] == 0
    assert turns[1]["turn_index"] == 1
    assert turns[0]["text"] == "הודעה ראשונה"
    assert turns[1]["text"] == "הודעה שנייה"

    # Also verify via the AuditStore Protocol (in-process).
    import asyncio

    loop = asyncio.new_event_loop()
    try:
        history = loop.run_until_complete(
            app.state.audit_store.read_conversation_history(child_id, last_n_turns=10)
        )
    finally:
        loop.close()
    assert len(history) == 2
    assert [t.turn_index for t in history] == [0, 1]


# --------------------------------------------------------------------------- #
# Test 6: pornographic always_alert override
# --------------------------------------------------------------------------- #


def test_pornographic_always_alert(full_client):
    """
    Label 'pornographic' is in always_alert_labels (triage settings default).
    Regardless of confidence or CA state, it must route to ALERT_DIRECT.
    """
    client, db_path, notifier = full_client
    trace_id = f"test-porn-{uuid.uuid4().hex[:8]}"
    child_id = f"child-{uuid.uuid4().hex[:8]}"

    # Low confidence on pornographic — the override still fires.
    app.state.classifier = _StubClassifier(
        _make_result("pornographic", 0.4, True)
    )
    app.state.context_agent = None  # CA disabled — should not matter

    resp = client.post(
        "/classify",
        json={"text": "תשלחי תמונות עירום", "child_id": child_id},
        headers={"X-Trace-Id": trace_id},
    )
    assert resp.status_code == 200

    rows = _query(
        db_path,
        "SELECT triage_decision, frontline_only_decision FROM classifications WHERE trace_id=?",
        (trace_id,),
    )
    assert len(rows) == 1
    assert rows[0]["triage_decision"] == TriageDecision.ALERT_DIRECT.value
    assert rows[0]["frontline_only_decision"] == TriageDecision.ALERT_DIRECT.value

    # Alert must have fired.
    assert len(notifier.requests) == 1
    assert notifier.requests[0].label == "pornographic"


# --------------------------------------------------------------------------- #
# Test 7: violence + CA enabled → always escalate to CA
# --------------------------------------------------------------------------- #


def test_violence_always_escalate(full_client):
    """
    Label 'violence' is in always_escalate_labels (triage settings default).
    With CA enabled the frontline_only_decision == escalate_to_ca regardless of
    confidence.  The CA (MockLlmClient) then resolves it deterministically.
    """
    client, db_path, notifier = full_client
    trace_id = f"test-violence-{uuid.uuid4().hex[:8]}"

    # High confidence violence — still escalates (not ALERT_DIRECT directly).
    app.state.classifier = _StubClassifier(
        _make_result("violence", 0.97, True)
    )
    assert app.state.context_agent is not None, (
        "Expected CA to be enabled for this test."
    )

    resp = client.post(
        "/classify",
        json={"text": "אשבור לך את הראש"},
        headers={"X-Trace-Id": trace_id},
    )
    assert resp.status_code == 200

    rows = _query(
        db_path,
        "SELECT triage_decision, frontline_only_decision FROM classifications WHERE trace_id=?",
        (trace_id,),
    )
    assert len(rows) == 1
    # Frontline said escalate.
    assert rows[0]["frontline_only_decision"] == TriageDecision.ESCALATE_TO_CA.value
