"""SqliteDigestStore — durable DigestStore adapter.

One ``digests`` table stores serialised ``ChildDigest`` values as JSON.
Connection model mirrors ``SqliteAuditStore``:
  - One shared write connection, WAL mode, asyncio.Lock for writes.
  - ``busy_timeout_ms`` guards against write contention.

Lifecycle contract for the composition root::

    store = SqliteDigestStore(db_path=settings.db_path)
    await store.initialize()
    app.state.digest_store = store
    # ... yield ...
    await store.close()

Reference: linked-yawning-sifakis.md §S3 "Persist digests".
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import asdict

import aiosqlite
import structlog

from ..schemas import HealthState
from .protocol import ChildDigest, DigestEntry

log = structlog.get_logger("shomer.digest.sqlite")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS digests (
    child_id     TEXT NOT NULL,
    date         TEXT NOT NULL,
    parent_id    TEXT NOT NULL,
    generated_at REAL NOT NULL,
    payload      TEXT NOT NULL,  -- full ChildDigest as JSON
    PRIMARY KEY (child_id, date)
);
CREATE INDEX IF NOT EXISTS idx_digests_child_date
    ON digests(child_id, date DESC);
"""


def _digest_to_json(digest: ChildDigest) -> str:
    """Serialise ChildDigest to JSON.  DigestEntry.label is a str Literal."""
    d = {
        "child_id": digest.child_id,
        "parent_id": digest.parent_id,
        "date": digest.date,
        "generated_at": digest.generated_at,
        "total_flagged": digest.total_flagged,
        "review_needed": digest.review_needed,
        "by_severity": digest.by_severity,
        "by_label": digest.by_label,
        "entries": [
            {
                "flag_id": e.flag_id,
                "app_package": e.app_package,
                "direction": e.direction,
                "label": e.label,
                "severity": e.severity,
                "quote": e.quote,
                "status": e.status,
                "created_at": e.created_at,
            }
            for e in digest.entries
        ],
    }
    return json.dumps(d, ensure_ascii=False)


def _json_to_digest(payload: str) -> ChildDigest:
    """Deserialise a ChildDigest from JSON."""
    d = json.loads(payload)
    entries = [
        DigestEntry(
            flag_id=e["flag_id"],
            app_package=e["app_package"],
            direction=e["direction"],
            label=e["label"],
            severity=e["severity"],
            quote=e["quote"],
            status=e["status"],
            created_at=e["created_at"],
        )
        for e in d.get("entries", [])
    ]
    return ChildDigest(
        child_id=d["child_id"],
        parent_id=d["parent_id"],
        date=d["date"],
        generated_at=d["generated_at"],
        total_flagged=d["total_flagged"],
        review_needed=d["review_needed"],
        by_severity=d["by_severity"],
        by_label=d["by_label"],
        entries=entries,
    )


class SqliteDigestStore:
    """SQLite-backed DigestStore (production default)."""

    def __init__(
        self,
        db_path: str = "server/data/digest.db",
        busy_timeout_ms: int = 5000,
    ) -> None:
        self._db_path = db_path
        self._busy_timeout_ms = busy_timeout_ms
        self._conn: aiosqlite.Connection | None = None
        self._write_lock = asyncio.Lock()

    async def initialize(self) -> None:
        """Open connection, set PRAGMAs, create tables."""
        os.makedirs(os.path.dirname(os.path.abspath(self._db_path)), exist_ok=True)
        self._conn = await aiosqlite.connect(self._db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute(f"PRAGMA busy_timeout={self._busy_timeout_ms}")
        await self._conn.execute("PRAGMA synchronous=NORMAL")
        await self._conn.executescript(_SCHEMA)
        await self._conn.commit()
        log.info("digest_store.initialized", db_path=self._db_path)

    async def close(self) -> None:
        if self._conn:
            await self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            await self._conn.close()
            self._conn = None
            log.info("digest_store.closed")

    def _conn_or_raise(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("SqliteDigestStore not initialized; call await initialize()")
        return self._conn

    async def save(self, digest: ChildDigest) -> None:
        """Persist digest; INSERT OR REPLACE (last write wins on primary key)."""
        conn = self._conn_or_raise()
        payload = _digest_to_json(digest)
        async with self._write_lock:
            await conn.execute(
                """
                INSERT OR REPLACE INTO digests(child_id, date, parent_id, generated_at, payload)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    digest.child_id,
                    digest.date,
                    digest.parent_id,
                    digest.generated_at,
                    payload,
                ),
            )
            await conn.commit()
        log.debug(
            "digest_store.saved",
            child_id=digest.child_id,
            date=digest.date,
            total=digest.total_flagged,
        )

    async def get(self, child_id: str, date: str) -> ChildDigest | None:
        conn = self._conn_or_raise()
        async with conn.execute(
            "SELECT payload FROM digests WHERE child_id=? AND date=?",
            (child_id, date),
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        return _json_to_digest(row["payload"])

    async def list_for_child(
        self,
        child_id: str,
        limit: int = 30,
    ) -> list[ChildDigest]:
        conn = self._conn_or_raise()
        async with conn.execute(
            "SELECT payload FROM digests WHERE child_id=? ORDER BY date DESC LIMIT ?",
            (child_id, limit),
        ) as cur:
            rows = await cur.fetchall()
        return [_json_to_digest(row["payload"]) for row in rows]

    async def health(self) -> tuple[HealthState, str]:
        try:
            conn = self._conn_or_raise()
            async with conn.execute("SELECT COUNT(*) AS n FROM digests") as cur:
                row = await cur.fetchone()
            n = row["n"] if row else 0
            return (HealthState.OK, f"sqlite: {n} digests stored")
        except Exception as exc:
            log.error("digest_store.health_failed", error=str(exc))
            return (HealthState.DOWN, f"sqlite health check failed: {exc}")
