"""SqliteFlaggedEventStore — durable FlaggedEventStore adapter.

One ``flagged_events`` table. Connection model mirrors ``SqliteAuditStore``:
one shared write connection, WAL mode, asyncio.Lock for multi-statement writes.

This adapter is implemented in S1 so the S4 "durable" swap is a one-line
change in ``main.py`` lifespan() (``FLAGGED_BACKEND=sqlite``).

Lifecycle contract for the composition root::

    store = SqliteFlaggedEventStore(db_path=settings.flagged_db_path)
    await store.initialize()   # creates table if needed
    app.state.flagged = store
    # ... yield ...
    await store.close()
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import replace

import aiosqlite
import structlog

from ..schemas import HealthState
from .protocol import FlaggedEvent

logger = structlog.get_logger("shomer.flagged")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS flagged_events (
    flag_id          TEXT    PRIMARY KEY,
    child_id         TEXT    NOT NULL,
    created_at       REAL    NOT NULL,
    app_package      TEXT    NOT NULL,
    direction        TEXT    NOT NULL,
    label            TEXT    NOT NULL,
    severity         TEXT    NOT NULL,
    quote            TEXT    NOT NULL,
    explanation      TEXT    NOT NULL,
    source           TEXT    NOT NULL,
    trace_id         TEXT    NOT NULL,
    status           TEXT    NOT NULL DEFAULT 'alerted',
    parent_label     TEXT,
    parent_severity  TEXT,
    acknowledged_at  REAL
);
CREATE INDEX IF NOT EXISTS idx_flagged_child_created
    ON flagged_events(child_id, created_at DESC);
"""


class SqliteFlaggedEventStore:
    """SQLite-backed FlaggedEventStore (durable, S4 default)."""

    def __init__(
        self,
        db_path: str = "server/data/flagged.db",
        busy_timeout_ms: int = 5000,
    ) -> None:
        self._db_path = db_path
        self._busy_timeout_ms = busy_timeout_ms
        self._conn: aiosqlite.Connection | None = None
        self._write_lock = asyncio.Lock()

    async def initialize(self) -> None:
        """Open the connection, set PRAGMAs, create the table."""
        os.makedirs(os.path.dirname(self._db_path) or ".", exist_ok=True)
        self._conn = await aiosqlite.connect(self._db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute(f"PRAGMA busy_timeout={self._busy_timeout_ms}")
        await self._conn.execute("PRAGMA synchronous=NORMAL")
        await self._conn.executescript(_SCHEMA)
        await self._conn.commit()
        logger.info("flagged_store.initialized", db_path=self._db_path)

    async def close(self) -> None:
        """Checkpoint WAL and close the connection."""
        if self._conn:
            await self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            await self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # FlaggedEventStore Protocol
    # ------------------------------------------------------------------

    async def record(self, event: FlaggedEvent) -> None:
        """Insert the event; idempotent on flag_id (INSERT OR IGNORE)."""
        assert self._conn is not None, "Call initialize() first"
        async with self._write_lock:
            await self._conn.execute(
                """
                INSERT OR IGNORE INTO flagged_events
                    (flag_id, child_id, created_at, app_package, direction,
                     label, severity, quote, explanation, source, trace_id,
                     status, parent_label, parent_severity, acknowledged_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    event.flag_id,
                    event.child_id,
                    event.created_at,
                    event.app_package,
                    event.direction,
                    event.label,
                    event.severity,
                    event.quote,
                    event.explanation,
                    event.source,
                    event.trace_id,
                    event.status,
                    event.parent_label,
                    event.parent_severity,
                    event.acknowledged_at,
                ),
            )
            await self._conn.commit()

    async def list_for_child(
        self,
        child_id: str,
        *,
        since: float | None = None,
        limit: int = 50,
        include_acked: bool = False,
    ) -> list[FlaggedEvent]:
        assert self._conn is not None, "Call initialize() first"
        where = "child_id = ?"
        params: list = [child_id]
        if since is not None:
            where += " AND created_at >= ?"
            params.append(since)
        if not include_acked:
            where += " AND status NOT IN ('acknowledged','labeled')"
        params.append(limit)

        async with self._conn.execute(
            f"SELECT * FROM flagged_events WHERE {where} ORDER BY created_at DESC LIMIT ?",
            params,
        ) as cur:
            rows = await cur.fetchall()
        return [_row_to_event(dict(r)) for r in rows]

    async def get(self, flag_id: str) -> FlaggedEvent | None:
        assert self._conn is not None, "Call initialize() first"
        async with self._conn.execute(
            "SELECT * FROM flagged_events WHERE flag_id = ?", (flag_id,)
        ) as cur:
            row = await cur.fetchone()
        return _row_to_event(dict(row)) if row else None

    async def acknowledge(self, flag_id: str, parent_id: str) -> bool:  # noqa: ARG002
        assert self._conn is not None, "Call initialize() first"
        async with self._write_lock:
            cursor = await self._conn.execute(
                """
                UPDATE flagged_events
                   SET status = 'acknowledged', acknowledged_at = ?
                 WHERE flag_id = ?
                """,
                (time.time(), flag_id),
            )
            await self._conn.commit()
            return cursor.rowcount > 0

    async def set_parent_label(
        self, flag_id: str, label: str, severity: str | None
    ) -> bool:
        assert self._conn is not None, "Call initialize() first"
        async with self._write_lock:
            cursor = await self._conn.execute(
                """
                UPDATE flagged_events
                   SET status = 'labeled', parent_label = ?, parent_severity = ?
                 WHERE flag_id = ?
                """,
                (label, severity, flag_id),
            )
            await self._conn.commit()
            return cursor.rowcount > 0

    async def set_parent_severity(self, flag_id: str, severity: str) -> bool:
        """Set parent_severity; transitions status to 'labeled'."""
        assert self._conn is not None, "Call initialize() first"
        async with self._write_lock:
            cursor = await self._conn.execute(
                """
                UPDATE flagged_events
                   SET status = 'labeled', parent_severity = ?
                 WHERE flag_id = ?
                """,
                (severity, flag_id),
            )
            await self._conn.commit()
            return cursor.rowcount > 0

    async def child_ids_with_events_since(self, since: float) -> list[str]:
        """Return distinct child_ids with events created_at >= since."""
        assert self._conn is not None, "Call initialize() first"
        async with self._conn.execute(
            "SELECT DISTINCT child_id FROM flagged_events WHERE created_at >= ?",
            (since,),
        ) as cur:
            rows = await cur.fetchall()
        return [row[0] for row in rows]

    async def health(self) -> tuple[HealthState, str]:
        if self._conn is None:
            return (HealthState.DOWN, "not initialized")
        try:
            async with self._conn.execute(
                "SELECT COUNT(*) FROM flagged_events"
            ) as cur:
                row = await cur.fetchone()
            total = row[0] if row else 0
            return (HealthState.OK, f"sqlite; {total} flagged events at {self._db_path}")
        except Exception as exc:  # noqa: BLE001
            return (HealthState.DEGRADED, f"sqlite error: {exc}")


# ---------------------------------------------------------------------------
# Row → dataclass conversion
# ---------------------------------------------------------------------------


def _row_to_event(row: dict) -> FlaggedEvent:
    return FlaggedEvent(
        flag_id=row["flag_id"],
        child_id=row["child_id"],
        created_at=row["created_at"],
        app_package=row["app_package"],
        direction=row["direction"],
        label=row["label"],  # type: ignore[arg-type]
        severity=row["severity"],  # type: ignore[arg-type]
        quote=row["quote"],
        explanation=row["explanation"],
        source=row["source"],  # type: ignore[arg-type]
        trace_id=row["trace_id"],
        status=row["status"],  # type: ignore[arg-type]
        parent_label=row.get("parent_label"),
        parent_severity=row.get("parent_severity"),
        acknowledged_at=row.get("acknowledged_at"),
    )
