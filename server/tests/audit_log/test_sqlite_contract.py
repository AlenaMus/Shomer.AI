"""Contract + behavior tests for SqliteAuditStore.

The shared-semantics tests are parametrized over BOTH adapters (SqliteAuditStore
and InMemoryAuditStore) so they are proven drop-in swappable. SQLite-specific
tests (aged-row cleanup via injected created_at, streaming query) target the
real adapter only.

Reference: docs/design/audit_log/design.md §7 (Test Plan).
"""

from __future__ import annotations

import time
from typing import AsyncIterator

import pytest
import pytest_asyncio

from app.audit_log import (
    AuditRow,
    AuditStore,
    ConversationTurn,
    InMemoryAuditStore,
    SqliteAuditStore,
)
from app.schemas import (
    ClassificationResult,
    ContextDecision,
    HealthState,
    TriageDecision,
)


# --------------------------------------------------------------------------- #
# Helpers / factories                                                         #
# --------------------------------------------------------------------------- #


def make_result(
    label: str = "non_offensive",
    confidence: float = 0.95,
    is_offensive: bool = False,
) -> ClassificationResult:
    return ClassificationResult(
        label=label,
        confidence=confidence,
        is_offensive=is_offensive,
        model_version="v1.0-standin",
        latency_ms=12.0,
        is_borderline=False,
        raw_confidence=confidence,
    )


def make_decision(is_real_threat: bool = True) -> ContextDecision:
    return ContextDecision(
        is_real_threat=is_real_threat,
        severity="high" if is_real_threat else "low",
        explanation="הודעה מאיימת" if is_real_threat else "אין סכנה",
        model_used="mock",
        tokens_input=100,
        tokens_output=20,
        cost_usd=0.0001,
        reasoning_trace="trace...",
    )


async def drain(it: AsyncIterator[AuditRow]) -> list[AuditRow]:
    return [row async for row in it]


# Parametrize over both adapters for shared-semantics tests.
@pytest_asyncio.fixture(params=["sqlite", "in_memory"])
async def store(request, tmp_path) -> AsyncIterator[AuditStore]:
    if request.param == "sqlite":
        s = SqliteAuditStore(db_path=str(tmp_path / "audit.db"))
        await s.initialize()
        try:
            yield s
        finally:
            await s.close()
    else:
        yield InMemoryAuditStore()


# --------------------------------------------------------------------------- #
# Protocol conformance                                                        #
# --------------------------------------------------------------------------- #


def test_sqlite_isinstance_auditstore(tmp_path):
    store = SqliteAuditStore(db_path=str(tmp_path / "audit.db"))
    assert isinstance(store, AuditStore)


def test_in_memory_isinstance_auditstore():
    assert isinstance(InMemoryAuditStore(), AuditStore)


# --------------------------------------------------------------------------- #
# Shared semantics (both adapters)                                            #
# --------------------------------------------------------------------------- #


async def test_record_classification_returns_increasing_ids(store: AuditStore):
    id1 = await store.record_classification(
        trace_id="t1",
        request_text="שלום",
        classifier_result=make_result(),
        triage_decision=TriageDecision.SILENT,
        context_agent_enabled=False,
    )
    id2 = await store.record_classification(
        trace_id="t2",
        request_text="עולם",
        classifier_result=make_result(),
        triage_decision=TriageDecision.SILENT,
        context_agent_enabled=False,
    )
    assert isinstance(id1, int) and isinstance(id2, int)
    assert id2 > id1


async def test_conversation_history_roundtrip_order_and_limit(store: AuditStore):
    child = "child-001"
    for i in range(10):
        await store.record_conversation_turn(
            child_id=child, turn_index=i, role="child_outbound", text=f"msg{i}"
        )
    last5 = await store.read_conversation_history(child, last_n_turns=5)
    assert [t.turn_index for t in last5] == [5, 6, 7, 8, 9]
    assert [t.text for t in last5] == [f"msg{i}" for i in range(5, 10)]
    assert all(isinstance(t, ConversationTurn) for t in last5)

    last3 = await store.read_conversation_history(child, last_n_turns=3)
    assert [t.turn_index for t in last3] == [7, 8, 9]

    # Unknown child → empty.
    assert await store.read_conversation_history("nobody") == []


async def test_record_alert_is_idempotent(store: AuditStore):
    for _ in range(3):
        await store.record_alert(
            alert_id="alert-xyz",
            trace_id="t1",
            child_id="child-001",
            label="abusive",
            severity="high",
            quote_snippet="...",
            explanation="explanation",
        )
    # Idempotent: only one row survives. Verify via a downstream effect — set a
    # gold label + query is the cleanest cross-adapter observable, but alerts
    # aren't surfaced there. For SQLite we can count; for in-memory the dict
    # keying guarantees one. Assert no exception + (sqlite) row count == 1.
    if isinstance(store, SqliteAuditStore):
        conn = store._require_conn()  # type: ignore[attr-defined]
        cur = await conn.execute("SELECT COUNT(*) FROM alerts WHERE alert_id=?", ("alert-xyz",))
        row = await cur.fetchone()
        await cur.close()
        assert row[0] == 1


async def test_set_gold_label_reflected_in_query(store: AuditStore):
    cid = await store.record_classification(
        trace_id="t1",
        request_text="טקסט",
        classifier_result=make_result(label="abusive", confidence=0.6, is_offensive=True),
        triage_decision=TriageDecision.ESCALATE_TO_CA,
        context_agent_enabled=True,
        frontline_only_decision="alert_direct",
        child_id="child-001",
    )
    await store.set_gold_label(cid, "abusive", annotator_id="alona-1", notes="clear")

    rows = await drain(store.query_for_evaluation((0.0, time.time() + 60)))
    assert len(rows) == 1
    r = rows[0]
    assert r.classification_id == cid
    assert r.gold_label == "abusive"
    assert r.triage_decision == TriageDecision.ESCALATE_TO_CA
    assert r.context_agent_enabled is True
    assert r.frontline_only_decision == "alert_direct"
    assert r.is_offensive is True
    assert r.child_id == "child-001"


async def test_query_date_range_filters_by_window(store: AuditStore):
    """Shared semantics: only rows inside the date_range are streamed.

    (The optional ``filters`` dict — gold_labeled_only / context_agent_enabled —
    is a SqliteAuditStore extension and is asserted in the SQLite-only section;
    the reference InMemoryAuditStore honours date_range but not the filters.)
    """
    await store.record_classification(
        trace_id="t1", request_text="a", classifier_result=make_result(),
        triage_decision=TriageDecision.SILENT, context_agent_enabled=False,
    )
    now = time.time()
    in_window = await drain(store.query_for_evaluation((now - 60, now + 60)))
    assert [r.trace_id for r in in_window] == ["t1"]
    # Far-past window excludes the just-written row.
    out_window = await drain(store.query_for_evaluation((0.0, 1.0)))
    assert out_window == []


async def test_health_ok(store: AuditStore):
    state, detail = await store.health()
    assert state == HealthState.OK
    assert isinstance(detail, str) and detail


async def test_record_agent_trace_returns_id(store: AuditStore):
    cid = await store.record_classification(
        trace_id="t1", request_text="x", classifier_result=make_result(),
        triage_decision=TriageDecision.ESCALATE_TO_CA, context_agent_enabled=True,
    )
    tid = await store.record_agent_trace(
        classification_id=cid,
        trace_id="t1",
        agent_input={"current_message": "x", "history": []},
        decision=make_decision(),
        tools_called=[{"tool": "read_history"}],
    )
    assert isinstance(tid, int) and tid > 0


# --------------------------------------------------------------------------- #
# SQLite-specific behavior                                                     #
# --------------------------------------------------------------------------- #


async def test_sqlite_query_filters(sqlite_store: SqliteAuditStore):
    cid1 = await sqlite_store.record_classification(
        trace_id="t1", request_text="a", classifier_result=make_result(),
        triage_decision=TriageDecision.SILENT, context_agent_enabled=False,
    )
    await sqlite_store.record_classification(
        trace_id="t2", request_text="b", classifier_result=make_result(),
        triage_decision=TriageDecision.SILENT, context_agent_enabled=True,
    )
    await sqlite_store.set_gold_label(cid1, "non_offensive", annotator_id="alona-1")

    gold_only = await drain(
        sqlite_store.query_for_evaluation((0.0, time.time() + 60), {"gold_labeled_only": True})
    )
    assert [r.classification_id for r in gold_only] == [cid1]

    ca_on = await drain(
        sqlite_store.query_for_evaluation((0.0, time.time() + 60), {"context_agent_enabled": True})
    )
    assert [r.trace_id for r in ca_on] == ["t2"]

    ca_off = await drain(
        sqlite_store.query_for_evaluation((0.0, time.time() + 60), {"context_agent_enabled": False})
    )
    assert [r.trace_id for r in ca_off] == ["t1"]


async def test_cleanup_expired_deletes_aged_rows(sqlite_store: SqliteAuditStore):
    # Fresh row via the normal path.
    fresh_id = await sqlite_store.record_classification(
        trace_id="fresh", request_text="new", classifier_result=make_result(),
        triage_decision=TriageDecision.SILENT, context_agent_enabled=False,
    )
    # Aged row: inject an old created_at directly (8 days ago).
    old_ts = time.time() - 8 * 86400
    conn = sqlite_store._require_conn()  # type: ignore[attr-defined]
    await conn.execute(
        """
        INSERT INTO classifications
            (trace_id, created_at, input_text, classifier_label,
             classifier_confidence, is_offensive, classifier_model_version,
             triage_decision, context_agent_enabled, input_type)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'text')
        """,
        ("aged", old_ts, "old", "non_offensive", 0.9, 0, "v1.0-standin", "silent", 0),
    )
    # Aged conversation turn too.
    await conn.execute(
        "INSERT INTO conversations (child_id, turn_index, role, text, created_at) VALUES (?,?,?,?,?)",
        ("child-001", 0, "child_outbound", "old turn", old_ts),
    )
    await conn.commit()

    deleted = await sqlite_store.cleanup_expired(retention_days=7)
    assert deleted >= 2  # aged classification + aged conversation turn

    remaining = await drain(
        sqlite_store.query_for_evaluation((0.0, time.time() + 60))
    )
    ids = {r.classification_id for r in remaining}
    assert fresh_id in ids
    assert all(r.trace_id != "aged" for r in remaining)


async def test_wal_mode_enabled(sqlite_store: SqliteAuditStore):
    conn = sqlite_store._require_conn()  # type: ignore[attr-defined]
    cur = await conn.execute("PRAGMA journal_mode")
    row = await cur.fetchone()
    await cur.close()
    assert row[0].lower() == "wal"


async def test_health_down_before_initialize(tmp_path):
    store = SqliteAuditStore(db_path=str(tmp_path / "audit.db"))
    state, detail = await store.health()
    assert state == HealthState.DOWN


async def test_query_streams_and_orders_by_created_at(sqlite_store: SqliteAuditStore):
    ids = []
    for i in range(5):
        cid = await sqlite_store.record_classification(
            trace_id=f"t{i}", request_text=f"m{i}", classifier_result=make_result(),
            triage_decision=TriageDecision.SILENT, context_agent_enabled=False,
        )
        ids.append(cid)
    rows = await drain(sqlite_store.query_for_evaluation((0.0, time.time() + 60)))
    assert [r.classification_id for r in rows] == ids  # ascending insert order


async def test_retention_sweeper_sweep_once(sqlite_store: SqliteAuditStore):
    from app.audit_log import RetentionSweeper

    old_ts = time.time() - 8 * 86400
    conn = sqlite_store._require_conn()  # type: ignore[attr-defined]
    await conn.execute(
        """
        INSERT INTO classifications
            (trace_id, created_at, input_text, classifier_label,
             classifier_confidence, is_offensive, classifier_model_version,
             triage_decision, context_agent_enabled, input_type)
        VALUES ('aged', ?, 'old', 'non_offensive', 0.9, 0, 'v1.0-standin', 'silent', 0, 'text')
        """,
        (old_ts,),
    )
    await conn.commit()
    sweeper = RetentionSweeper(sqlite_store, retention_days=7, interval_s=3600.0)
    deleted = await sweeper.sweep_once()
    assert deleted >= 1


async def test_persistence_across_reopen(db_path):
    store = SqliteAuditStore(db_path=db_path)
    await store.initialize()
    cid = await store.record_classification(
        trace_id="t1", request_text="persist", classifier_result=make_result(),
        triage_decision=TriageDecision.SILENT, context_agent_enabled=False,
    )
    await store.close()

    store2 = SqliteAuditStore(db_path=db_path)
    await store2.initialize()
    rows = await drain(store2.query_for_evaluation((0.0, time.time() + 60)))
    await store2.close()
    assert [r.classification_id for r in rows] == [cid]
