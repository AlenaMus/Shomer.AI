"""SqliteAuditStore — the real persistent AuditStore adapter.

Reference: docs/design/audit_log/design.md §3, §5 (schema), §9 (WAL/config).

This adapter implements the ``AuditStore`` Protocol (server/app/audit_log/protocol.py)
exactly, against SQLite via ``aiosqlite``. It is a drop-in replacement for the
``InMemoryAuditStore`` stop-gap — same method signatures and semantics.

Connection model
----------------
* One **shared write connection** is opened in :meth:`initialize` and reused for
  all recording / annotation / retention writes. ``aiosqlite`` runs each
  connection on its own background thread and queues operations, so concurrent
  ``await`` calls against the shared connection are serialised safely. An
  ``asyncio.Lock`` additionally wraps multi-statement write transactions
  (e.g. ``set_gold_label``) to keep them atomic against interleaving.
* :meth:`query_for_evaluation` opens its **own short-lived read connection** so a
  long streaming scan never blocks writes. WAL mode (set on the shared
  connection) lets readers and the writer proceed concurrently.

Lifecycle contract for the composition root (Phase B, server/app/main.py)
-------------------------------------------------------------------------
The composition root constructs and initialises the store in ``lifespan()``
startup, and closes it on shutdown::

    from app.audit_log import SqliteAuditStore, AuditSettings

    settings = AuditSettings()                 # reads AUDIT_* env vars
    store = SqliteAuditStore(
        db_path=settings.db_path,
        conversation_window=settings.conversation_window,
        busy_timeout_ms=settings.busy_timeout_ms,
    )
    await store.initialize()                    # opens conn, sets PRAGMAs, creates tables
    app.state.audit = store                     # downstream depends on AuditStore Protocol
    try:
        yield
    finally:
        await store.close()                     # checkpoints WAL + closes connection

The :class:`RetentionSweeper` (retention.py) is launched separately as a
background task by the composition root — this module never starts it.
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any, AsyncIterator

import aiosqlite
import structlog

from ..schemas import (
    ClassificationResult,
    ContextDecision,
    HealthState,
    TriageDecision,
)
from .protocol import AuditRow, ConversationTurn

logger = structlog.get_logger("shomer.audit")


# Time-stamped tables swept by retention. ``created_at`` is an epoch float on
# every one of these, so the retention DELETE is uniform.
_TIMESTAMPED_TABLES: tuple[str, ...] = (
    "classifications",
    "agent_traces",
    "alerts",
    "conversations",
)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS classifications (
    classification_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id                 TEXT    NOT NULL,
    created_at               REAL    NOT NULL,
    input_text               TEXT,
    classifier_label         TEXT    NOT NULL,
    classifier_confidence    REAL    NOT NULL,
    is_offensive             INTEGER NOT NULL,
    classifier_model_version TEXT,
    triage_decision          TEXT    NOT NULL,
    context_agent_enabled    INTEGER NOT NULL DEFAULT 0,
    frontline_only_decision  TEXT,
    child_id                 TEXT,
    message_id               TEXT,
    input_type               TEXT    NOT NULL DEFAULT 'text',
    ocr_extracted_text       TEXT,
    image_hash               TEXT,
    gold_label               TEXT,
    alert_id                 TEXT
);
CREATE INDEX IF NOT EXISTS idx_cls_created_at ON classifications(created_at);
CREATE INDEX IF NOT EXISTS idx_cls_trace      ON classifications(trace_id);
CREATE INDEX IF NOT EXISTS idx_cls_child_ts   ON classifications(child_id, created_at);
CREATE INDEX IF NOT EXISTS idx_cls_gold       ON classifications(gold_label);
CREATE INDEX IF NOT EXISTS idx_cls_ab_filter  ON classifications(context_agent_enabled, created_at);

CREATE TABLE IF NOT EXISTS agent_traces (
    agent_trace_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    classification_id  INTEGER NOT NULL,
    trace_id           TEXT    NOT NULL,
    agent_input_json   TEXT    NOT NULL,
    tools_called_json  TEXT    NOT NULL DEFAULT '[]',
    is_real_threat     INTEGER NOT NULL,
    severity           TEXT,
    explanation        TEXT    NOT NULL DEFAULT '',
    review_flag        INTEGER NOT NULL DEFAULT 0,
    model_used         TEXT,
    tokens_input       INTEGER NOT NULL DEFAULT 0,
    tokens_output      INTEGER NOT NULL DEFAULT 0,
    cost_usd           REAL    NOT NULL DEFAULT 0.0,
    reasoning_trace    TEXT    NOT NULL DEFAULT '',
    latency_ms         REAL    NOT NULL DEFAULT 0.0,
    created_at         REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_at_classification ON agent_traces(classification_id);
CREATE INDEX IF NOT EXISTS idx_at_trace          ON agent_traces(trace_id);
CREATE INDEX IF NOT EXISTS idx_at_created_at     ON agent_traces(created_at);

CREATE TABLE IF NOT EXISTS alerts (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_id           TEXT    NOT NULL UNIQUE,
    trace_id           TEXT    NOT NULL,
    child_id           TEXT    NOT NULL,
    label              TEXT    NOT NULL,
    severity           TEXT    NOT NULL,
    quote_snippet      TEXT    NOT NULL DEFAULT '',
    explanation        TEXT    NOT NULL DEFAULT '',
    fcm_status         TEXT    NOT NULL DEFAULT 'queued',
    fcm_response_json  TEXT,
    created_at         REAL    NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_alerts_id      ON alerts(alert_id);
CREATE INDEX IF NOT EXISTS idx_alerts_child_ts       ON alerts(child_id, created_at);
CREATE INDEX IF NOT EXISTS idx_alerts_created_at     ON alerts(created_at);

CREATE TABLE IF NOT EXISTS conversations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    child_id    TEXT    NOT NULL,
    turn_index  INTEGER NOT NULL,
    role        TEXT    NOT NULL,
    text        TEXT    NOT NULL,
    created_at  REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_conv_child_turn ON conversations(child_id, turn_index);
CREATE INDEX IF NOT EXISTS idx_conv_created_at ON conversations(created_at);

CREATE TABLE IF NOT EXISTS gold_set_metadata (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    classification_id INTEGER NOT NULL,
    label           TEXT    NOT NULL,
    annotator_id    TEXT    NOT NULL,
    notes           TEXT,
    annotated_at    REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_gold_cls ON gold_set_metadata(classification_id);
"""


class SqliteAuditStore:
    """Persistent ``AuditStore`` adapter backed by SQLite (``aiosqlite``)."""

    def __init__(
        self,
        db_path: str = "server/data/audit.db",
        *,
        conversation_window: int = 5,
        busy_timeout_ms: int = 5000,
    ) -> None:
        self._db_path = db_path
        self._conversation_window = conversation_window
        self._busy_timeout_ms = busy_timeout_ms
        self._conn: aiosqlite.Connection | None = None
        # Guards multi-statement write transactions against interleaving.
        self._write_lock = asyncio.Lock()

    # --- Lifecycle -----------------------------------------------------------

    async def initialize(self) -> None:
        """Open the shared connection, set PRAGMAs, create tables IF NOT EXISTS.

        Idempotent: calling it twice is a no-op after the first open.
        """
        if self._conn is not None:
            return

        # Ensure the parent directory exists (lazy creation; never commits a DB).
        parent = os.path.dirname(os.path.abspath(self._db_path))
        if parent:
            os.makedirs(parent, exist_ok=True)

        conn = await aiosqlite.connect(self._db_path)
        await conn.execute("PRAGMA journal_mode=WAL;")
        await conn.execute("PRAGMA synchronous=NORMAL;")
        await conn.execute(f"PRAGMA busy_timeout={int(self._busy_timeout_ms)};")
        await conn.executescript(_SCHEMA)
        await conn.commit()
        self._conn = conn
        logger.info("audit_store_initialized", db_path=self._db_path)

    async def close(self) -> None:
        """Checkpoint the WAL and close the shared connection."""
        if self._conn is None:
            return
        try:
            await self._conn.execute("PRAGMA wal_checkpoint(FULL);")
        except Exception:  # pragma: no cover - best-effort checkpoint
            logger.warning("audit_store_checkpoint_failed", db_path=self._db_path)
        await self._conn.close()
        self._conn = None
        logger.info("audit_store_closed", db_path=self._db_path)

    def _require_conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError(
                "SqliteAuditStore used before initialize(); call await store.initialize() first."
            )
        return self._conn

    # --- Recording side ------------------------------------------------------

    async def record_classification(
        self,
        trace_id: str,
        request_text: str,
        classifier_result: ClassificationResult,
        triage_decision: TriageDecision,
        context_agent_enabled: bool,
        frontline_only_decision: str | None = None,
        child_id: str | None = None,
        message_id: str | None = None,
        input_type: str = "text",
        ocr_extracted_text: str | None = None,
        image_hash: str | None = None,
    ) -> int:
        conn = self._require_conn()
        cur = await conn.execute(
            """
            INSERT INTO classifications (
                trace_id, created_at, input_text,
                classifier_label, classifier_confidence, is_offensive,
                classifier_model_version, triage_decision,
                context_agent_enabled, frontline_only_decision,
                child_id, message_id, input_type,
                ocr_extracted_text, image_hash, gold_label, alert_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
            """,
            (
                trace_id,
                time.time(),
                request_text,
                classifier_result.label,
                float(classifier_result.confidence),
                1 if classifier_result.is_offensive else 0,
                classifier_result.model_version,
                _enum_value(triage_decision),
                1 if context_agent_enabled else 0,
                frontline_only_decision,
                child_id,
                message_id,
                input_type,
                ocr_extracted_text,
                image_hash,
            ),
        )
        await conn.commit()
        cid = int(cur.lastrowid)
        logger.info(
            "record_classification",
            trace_id=trace_id,
            classification_id=cid,
            classifier_label=classifier_result.label,
            triage_decision=_enum_value(triage_decision),
        )
        return cid

    async def record_agent_trace(
        self,
        classification_id: int,
        trace_id: str,
        agent_input: dict[str, Any],
        decision: ContextDecision,
        tools_called: list[dict[str, Any]],
    ) -> int:
        import json

        conn = self._require_conn()
        cur = await conn.execute(
            """
            INSERT INTO agent_traces (
                classification_id, trace_id, agent_input_json, tools_called_json,
                is_real_threat, severity, explanation, review_flag, model_used,
                tokens_input, tokens_output, cost_usd, reasoning_trace,
                latency_ms, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                classification_id,
                trace_id,
                json.dumps(agent_input, ensure_ascii=False),
                json.dumps(tools_called, ensure_ascii=False),
                1 if decision.is_real_threat else 0,
                decision.severity,
                decision.explanation,
                1 if decision.review_flag else 0,
                decision.model_used,
                int(decision.tokens_input),
                int(decision.tokens_output),
                float(decision.cost_usd),
                decision.reasoning_trace,
                float(decision.latency_ms),
                time.time(),
            ),
        )
        await conn.commit()
        tid = int(cur.lastrowid)
        logger.info(
            "record_agent_trace",
            trace_id=trace_id,
            agent_trace_id=tid,
            classification_id=classification_id,
        )
        return tid

    async def record_alert(
        self,
        alert_id: str,
        trace_id: str,
        child_id: str,
        label: str,
        severity: str,
        quote_snippet: str,
        explanation: str,
        fcm_status: str = "queued",
        fcm_response_json: str | None = None,
    ) -> None:
        conn = self._require_conn()
        # Idempotent on alert_id: a duplicate send is silently ignored.
        await conn.execute(
            """
            INSERT OR IGNORE INTO alerts (
                alert_id, trace_id, child_id, label, severity,
                quote_snippet, explanation, fcm_status, fcm_response_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                alert_id,
                trace_id,
                child_id,
                label,
                severity,
                quote_snippet,
                explanation,
                fcm_status,
                fcm_response_json,
                time.time(),
            ),
        )
        await conn.commit()
        logger.info(
            "record_alert",
            trace_id=trace_id,
            alert_id=alert_id,
            fcm_status=fcm_status,
        )

    async def record_conversation_turn(
        self,
        child_id: str,
        turn_index: int,
        role: str,
        text: str,
    ) -> None:
        conn = self._require_conn()
        await conn.execute(
            """
            INSERT INTO conversations (child_id, turn_index, role, text, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (child_id, int(turn_index), role, text, time.time()),
        )
        await conn.commit()
        logger.info(
            "record_conversation_turn",
            child_id=child_id,
            turn_index=turn_index,
        )

    # --- Read side -----------------------------------------------------------

    async def read_conversation_history(
        self,
        child_id: str,
        last_n_turns: int = 5,
    ) -> list[ConversationTurn]:
        """Return the most-recent ``last_n_turns`` turns, in ascending turn order.

        Selects the newest N rows by ``(turn_index, id)`` DESC, then reverses so
        the caller sees them oldest-first (matching InMemoryAuditStore semantics).
        """
        conn = self._require_conn()
        cur = await conn.execute(
            """
            SELECT child_id, turn_index, role, text, created_at
            FROM conversations
            WHERE child_id = ?
            ORDER BY turn_index DESC, id DESC
            LIMIT ?
            """,
            (child_id, int(last_n_turns)),
        )
        rows = await cur.fetchall()
        await cur.close()
        # rows are newest-first; reverse to ascending turn order.
        turns = [
            ConversationTurn(
                child_id=row[0],
                turn_index=int(row[1]),
                role=row[2],
                text=row[3],
                timestamp=float(row[4]),
            )
            for row in reversed(rows)
        ]
        return turns

    def query_for_evaluation(
        self,
        date_range: tuple[float, float],
        filters: dict[str, Any] | None = None,
    ) -> AsyncIterator[AuditRow]:
        """Stream matching ``AuditRow`` records for the Meeting-8 ΔFPR harness.

        Synchronous method returning an async iterator (matches the Protocol).
        Opens its **own** read connection so a long scan never blocks writes,
        and streams rows one at a time rather than loading them all into memory.

        Supported ``filters`` keys:
          * ``context_agent_enabled``: bool — restrict to that A/B arm.
          * ``gold_labeled_only``: bool — only rows with a non-null gold_label.
        """
        filters = filters or {}
        t0, t1 = date_range
        db_path = self._db_path
        busy_timeout_ms = self._busy_timeout_ms

        where = ["created_at BETWEEN ? AND ?"]
        params: list[Any] = [t0, t1]

        if "context_agent_enabled" in filters and filters["context_agent_enabled"] is not None:
            where.append("context_agent_enabled = ?")
            params.append(1 if filters["context_agent_enabled"] else 0)

        if filters.get("gold_labeled_only"):
            where.append("gold_label IS NOT NULL")

        sql = (
            "SELECT classification_id, trace_id, created_at, classifier_label, "
            "classifier_confidence, is_offensive, triage_decision, "
            "context_agent_enabled, frontline_only_decision, gold_label, "
            "alert_id, input_text, child_id "
            "FROM classifications "
            f"WHERE {' AND '.join(where)} "
            "ORDER BY created_at ASC, classification_id ASC"
        )

        async def _iter() -> AsyncIterator[AuditRow]:
            conn = await aiosqlite.connect(db_path)
            try:
                await conn.execute(f"PRAGMA busy_timeout={int(busy_timeout_ms)};")
                async with conn.execute(sql, params) as cursor:
                    async for row in cursor:
                        yield AuditRow(
                            classification_id=int(row[0]),
                            trace_id=row[1],
                            created_at=float(row[2]),
                            classifier_label=row[3],
                            classifier_confidence=float(row[4]),
                            is_offensive=bool(row[5]),
                            triage_decision=TriageDecision(row[6]),
                            context_agent_enabled=bool(row[7]),
                            frontline_only_decision=row[8],
                            gold_label=row[9],
                            alert_id=row[10],
                            input_text=row[11],
                            child_id=row[12],
                        )
            finally:
                await conn.close()

        return _iter()

    # --- Annotation side -----------------------------------------------------

    async def set_gold_label(
        self,
        classification_id: int,
        label: str,
        annotator_id: str,
        notes: str | None = None,
    ) -> None:
        """Record a gold annotation and update the denormalised column.

        Writes a row into ``gold_set_metadata`` (the annotation audit trail) AND
        updates ``classifications.gold_label`` so ``query_for_evaluation`` and the
        ``gold_labeled_only`` filter reflect it without a join.
        """
        conn = self._require_conn()
        async with self._write_lock:
            await conn.execute(
                """
                INSERT INTO gold_set_metadata
                    (classification_id, label, annotator_id, notes, annotated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (int(classification_id), label, annotator_id, notes, time.time()),
            )
            await conn.execute(
                "UPDATE classifications SET gold_label = ? WHERE classification_id = ?",
                (label, int(classification_id)),
            )
            await conn.commit()
        logger.info(
            "gold_label_set",
            classification_id=classification_id,
            label=label,
            annotator_id=annotator_id,
        )

    # --- Retention -----------------------------------------------------------

    async def cleanup_expired(self, retention_days: int = 7) -> int:
        """Delete rows older than the cutoff across every time-stamped table.

        Returns the total number of rows deleted across all four tables.
        Robust to transient errors: logs and re-raises only for the caller's
        ``RetentionSweeper`` to absorb (it never crashes its loop).
        """
        conn = self._require_conn()
        cutoff = time.time() - retention_days * 86400
        total = 0
        async with self._write_lock:
            for table in _TIMESTAMPED_TABLES:
                cur = await conn.execute(
                    f"DELETE FROM {table} WHERE created_at < ?", (cutoff,)
                )
                total += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
                await cur.close()
            await conn.commit()
        logger.info(
            "audit_retention_sweep_complete",
            rows_deleted=total,
            retention_days=retention_days,
        )
        return total

    # --- Health --------------------------------------------------------------

    async def health(self) -> tuple[HealthState, str]:
        """OK when the DB is reachable + writable; DOWN otherwise."""
        if self._conn is None:
            return (HealthState.DOWN, "not initialized")
        try:
            cur = await self._conn.execute("SELECT COUNT(*) FROM classifications")
            row = await cur.fetchone()
            await cur.close()
            count = int(row[0]) if row else 0
            return (HealthState.OK, f"sqlite at {self._db_path}; {count} classifications")
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("audit_health_check_failed", error=str(exc))
            return (HealthState.DOWN, f"sqlite error: {exc}")


def _enum_value(value: Any) -> str:
    """Return ``.value`` for a TriageDecision enum, or str() for a plain string."""
    return value.value if hasattr(value, "value") else str(value)
