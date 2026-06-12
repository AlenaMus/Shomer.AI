"""SqliteIdentityStore — persistent IdentityStore adapter.

Four tables: ``parents``, ``children``, ``pairing_codes``, ``device_tokens``.

Connection model mirrors ``SqliteAuditStore``:
  - One shared write connection, WAL mode, asyncio.Lock for atomic writes.
  - ``busy_timeout_ms`` guards against write contention.

Lifecycle contract for the composition root::

    store = SqliteIdentityStore(db_path=settings.db_path)
    await store.initialize()   # opens conn, sets PRAGMAs, creates tables
    app.state.identity = store
    # ... yield ...
    await store.close()
"""

from __future__ import annotations

import asyncio
import os
import secrets
import time
import uuid
from dataclasses import replace

import aiosqlite
import structlog

from ..schemas import HealthState
from .protocol import ChildRecord, DeviceContext, PairingCode, ParentAuth
from .passwords import hash_password, verify_password

log = structlog.get_logger("shomer.identity.sqlite")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS parents (
    parent_id        TEXT PRIMARY KEY,
    display_name     TEXT NOT NULL DEFAULT '',
    created_at       REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS parent_tokens (
    token            TEXT PRIMARY KEY,
    parent_id        TEXT NOT NULL REFERENCES parents(parent_id)
);

CREATE TABLE IF NOT EXISTS children (
    child_id         TEXT PRIMARY KEY,
    parent_id        TEXT NOT NULL REFERENCES parents(parent_id),
    display_name     TEXT NOT NULL DEFAULT '',
    created_at       REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_children_parent
    ON children(parent_id);

CREATE TABLE IF NOT EXISTS pairing_codes (
    code             TEXT PRIMARY KEY,
    parent_id        TEXT NOT NULL,
    child_id         TEXT NOT NULL,
    expires_at       REAL NOT NULL,
    redeemed         INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_pairing_codes_child
    ON pairing_codes(parent_id, child_id);

CREATE TABLE IF NOT EXISTS device_tokens (
    token            TEXT PRIMARY KEY,
    child_id         TEXT NOT NULL,
    parent_id        TEXT NOT NULL,
    role             TEXT NOT NULL DEFAULT 'child',
    created_at       REAL NOT NULL,
    expires_at       REAL,
    fcm_token        TEXT
);
CREATE INDEX IF NOT EXISTS idx_device_tokens_child
    ON device_tokens(child_id);
"""

# Idempotent migration: add fcm_token if the table was created by an older schema.
_MIGRATE_FCM_TOKEN = """
ALTER TABLE device_tokens ADD COLUMN fcm_token TEXT;
"""

# Idempotent migrations: add username/password_hash to parents table (old column
# kept for existing DBs — SQLite can't drop columns; harmless unused).
_MIGRATE_USERNAME = """
ALTER TABLE parents ADD COLUMN username TEXT;
"""
_MIGRATE_PASSWORD_HASH = """
ALTER TABLE parents ADD COLUMN password_hash TEXT;
"""
_MIGRATE_USERNAME_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_parents_username
    ON parents(username) WHERE username IS NOT NULL;
"""

# Idempotent migration: add email column (replaces username as the login identifier).
_MIGRATE_EMAIL = """
ALTER TABLE parents ADD COLUMN email TEXT;
"""
_MIGRATE_EMAIL_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_parents_email
    ON parents(email) WHERE email IS NOT NULL;
"""


def _row_to_child(row) -> ChildRecord:
    return ChildRecord(
        child_id=row["child_id"],
        parent_id=row["parent_id"],
        display_name=row["display_name"],
        created_at=row["created_at"],
    )


def _row_to_pairing(row) -> PairingCode:
    return PairingCode(
        code=row["code"],
        parent_id=row["parent_id"],
        child_id=row["child_id"],
        expires_at=row["expires_at"],
        redeemed=bool(row["redeemed"]),
    )


class SqliteIdentityStore:
    """SQLite-backed IdentityStore (production default)."""

    def __init__(
        self,
        db_path: str = "server/data/identity.db",
        busy_timeout_ms: int = 5000,
        device_token_ttl_days: int = 365,
        pairing_code_ttl_s: int = 600,
    ) -> None:
        self._db_path = db_path
        self._busy_timeout_ms = busy_timeout_ms
        self._device_token_ttl_days = device_token_ttl_days
        self._pairing_code_ttl_s = pairing_code_ttl_s
        self._conn: aiosqlite.Connection | None = None
        self._write_lock = asyncio.Lock()

    async def initialize(self) -> None:
        """Open connection, set PRAGMAs, create tables.

        Also applies an idempotent migration to add ``fcm_token`` to
        ``device_tokens`` if the column does not yet exist (handles existing
        databases created before S3).
        """
        os.makedirs(os.path.dirname(os.path.abspath(self._db_path)), exist_ok=True)
        self._conn = await aiosqlite.connect(self._db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute(f"PRAGMA busy_timeout={self._busy_timeout_ms}")
        await self._conn.execute("PRAGMA synchronous=NORMAL")
        await self._conn.executescript(_SCHEMA)
        await self._conn.commit()

        # Idempotent migration: add fcm_token column if missing.
        try:
            await self._conn.execute(_MIGRATE_FCM_TOKEN)
            await self._conn.commit()
        except Exception:  # noqa: BLE001 — column already exists → ignore
            pass

        # Idempotent migrations: username + password_hash + unique index (old schema).
        for _sql in (_MIGRATE_USERNAME, _MIGRATE_PASSWORD_HASH):
            try:
                await self._conn.execute(_sql)
                await self._conn.commit()
            except Exception:  # noqa: BLE001 — column already exists → ignore
                pass
        try:
            await self._conn.execute(_MIGRATE_USERNAME_INDEX)
            await self._conn.commit()
        except Exception:  # noqa: BLE001 — index already exists → ignore
            pass

        # Idempotent migration: add email column + partial unique index.
        # DBs that already have username stay valid — username column is left
        # in place (SQLite cannot drop columns) but is no longer used.
        try:
            await self._conn.execute(_MIGRATE_EMAIL)
            await self._conn.commit()
        except Exception:  # noqa: BLE001 — column already exists → ignore
            pass
        try:
            await self._conn.execute(_MIGRATE_EMAIL_INDEX)
            await self._conn.commit()
        except Exception:  # noqa: BLE001 — index already exists → ignore
            pass

        log.info("identity_store.initialized", db_path=self._db_path)

    async def close(self) -> None:
        if self._conn:
            await self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            await self._conn.close()
            self._conn = None
            log.info("identity_store.closed", db_path=self._db_path)

    def _conn_or_raise(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("SqliteIdentityStore not initialized; call await initialize()")
        return self._conn

    # --- Parent ------------------------------------------------------------------

    async def register_parent(
        self,
        display_name: str = "",
        email: str | None = None,
        password: str | None = None,
    ) -> tuple[str, str]:
        parent_id = str(uuid.uuid4())
        token = secrets.token_urlsafe(32)
        # Normalise email to lowercase before storage for case-insensitive lookup.
        normalised_email = email.strip().lower() if email else None
        password_hash: str | None = hash_password(password) if password else None
        conn = self._conn_or_raise()
        async with self._write_lock:
            try:
                await conn.execute(
                    "INSERT INTO parents(parent_id, display_name, created_at, email, password_hash) VALUES(?,?,?,?,?)",
                    (parent_id, display_name, time.time(), normalised_email, password_hash),
                )
            except Exception as exc:
                # SQLite UNIQUE constraint violation on email — rollback + re-raise.
                if "UNIQUE" in str(exc).upper():
                    try:
                        await conn.rollback()
                    except Exception:  # noqa: BLE001
                        pass
                    raise ValueError("email_taken") from exc
                raise
            await conn.execute(
                "INSERT INTO parent_tokens(token, parent_id) VALUES(?,?)",
                (token, parent_id),
            )
            await conn.commit()
        log.info(
            "identity.parent_registered",
            parent_id=parent_id,
            token_prefix=token[:8],
            has_email=normalised_email is not None,
        )
        return parent_id, token

    async def authenticate_parent_credentials(
        self, email: str, password: str
    ) -> "ParentAuth | None":
        """Validate email + password; return ParentAuth or None."""
        normalised_email = email.strip().lower() if email else ""
        conn = self._conn_or_raise()
        async with conn.execute(
            "SELECT parent_id, display_name, email, password_hash FROM parents WHERE email=?",
            (normalised_email,),
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        stored_hash = row["password_hash"]
        if not stored_hash or not verify_password(password, stored_hash):
            return None
        # Fetch the existing parent token (most recently issued one).
        async with conn.execute(
            "SELECT token FROM parent_tokens WHERE parent_id=? LIMIT 1",
            (row["parent_id"],),
        ) as cur:
            token_row = await cur.fetchone()
        if not token_row:
            return None
        return ParentAuth(
            parent_id=row["parent_id"],
            parent_token=token_row["token"],
            display_name=row["display_name"],
            email=row["email"],
        )

    async def authenticate_parent(self, token: str) -> DeviceContext | None:
        conn = self._conn_or_raise()
        async with conn.execute(
            "SELECT parent_id FROM parent_tokens WHERE token=?", (token,)
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        return DeviceContext(
            device_token=token,
            child_id="",
            parent_id=row["parent_id"],
            role="parent",
        )

    # --- Child -------------------------------------------------------------------

    async def issue_child(self, parent_id: str, display_name: str) -> ChildRecord:
        child_id = str(uuid.uuid4())
        now = time.time()
        conn = self._conn_or_raise()
        async with self._write_lock:
            await conn.execute(
                "INSERT INTO children(child_id, parent_id, display_name, created_at) VALUES(?,?,?,?)",
                (child_id, parent_id, display_name, now),
            )
            await conn.commit()
        record = ChildRecord(
            child_id=child_id,
            parent_id=parent_id,
            display_name=display_name,
            created_at=now,
        )
        log.info("identity.child_issued", child_id=child_id, parent_id=parent_id)
        return record

    async def list_children(self, parent_id: str) -> list[ChildRecord]:
        conn = self._conn_or_raise()
        async with conn.execute(
            "SELECT child_id, parent_id, display_name, created_at FROM children WHERE parent_id=? ORDER BY created_at",
            (parent_id,),
        ) as cur:
            rows = await cur.fetchall()
        return [_row_to_child(r) for r in rows]

    # --- Pairing -----------------------------------------------------------------

    async def create_pairing_code(self, parent_id: str, child_id: str) -> PairingCode:
        conn = self._conn_or_raise()
        # Invalidate old unredeemed codes for this (parent, child) pair.
        raw = secrets.randbelow(1_000_000)
        code_str = f"{raw:06d}"
        expires_at = time.time() + self._pairing_code_ttl_s
        async with self._write_lock:
            await conn.execute(
                "DELETE FROM pairing_codes WHERE parent_id=? AND child_id=? AND redeemed=0",
                (parent_id, child_id),
            )
            await conn.execute(
                "INSERT INTO pairing_codes(code, parent_id, child_id, expires_at, redeemed) VALUES(?,?,?,?,0)",
                (code_str, parent_id, child_id, expires_at),
            )
            await conn.commit()
        pc = PairingCode(
            code=code_str,
            parent_id=parent_id,
            child_id=child_id,
            expires_at=expires_at,
        )
        log.info(
            "identity.pairing_code_created",
            child_id=child_id,
            parent_id=parent_id,
            expires_at=expires_at,
        )
        return pc

    async def redeem_pairing_code(
        self,
        code: str,
        device_fingerprint: str,
    ) -> DeviceContext | None:
        conn = self._conn_or_raise()
        # Fetch the code record.
        async with conn.execute(
            "SELECT code, parent_id, child_id, expires_at, redeemed FROM pairing_codes WHERE code=?",
            (code,),
        ) as cur:
            row = await cur.fetchone()

        if not row:
            log.warning("identity.redeem_failed", reason="not_found", code_prefix=code[:4])
            return None
        pc = _row_to_pairing(row)
        if pc.redeemed:
            log.warning("identity.redeem_failed", reason="already_redeemed", code_prefix=code[:4])
            return None
        if time.time() > pc.expires_at:
            log.warning("identity.redeem_failed", reason="expired", code_prefix=code[:4])
            return None

        # Mint device token.
        token = secrets.token_urlsafe(32)
        now = time.time()
        expires_at: float | None = None
        if self._device_token_ttl_days > 0:
            expires_at = now + self._device_token_ttl_days * 86400

        async with self._write_lock:
            await conn.execute(
                "UPDATE pairing_codes SET redeemed=1 WHERE code=?",
                (code,),
            )
            await conn.execute(
                "INSERT INTO device_tokens(token, child_id, parent_id, role, created_at, expires_at) VALUES(?,?,?,?,?,?)",
                (token, pc.child_id, pc.parent_id, "child", now, expires_at),
            )
            await conn.commit()

        ctx = DeviceContext(
            device_token=token,
            child_id=pc.child_id,
            parent_id=pc.parent_id,
            role="child",
        )
        log.info(
            "identity.pairing_redeemed",
            child_id=pc.child_id,
            token_prefix=token[:8],
        )
        return ctx

    # --- Device token ------------------------------------------------------------

    async def authenticate_device(self, token: str) -> DeviceContext | None:
        conn = self._conn_or_raise()
        async with conn.execute(
            "SELECT token, child_id, parent_id, role, expires_at FROM device_tokens WHERE token=?",
            (token,),
        ) as cur:
            row = await cur.fetchone()
        if not row:
            return None
        expires_at = row["expires_at"]
        if expires_at is not None and time.time() > expires_at:
            log.warning("identity.device_token_expired", child_id=row["child_id"])
            return None
        return DeviceContext(
            device_token=row["token"],
            child_id=row["child_id"],
            parent_id=row["parent_id"],
            role=row["role"],
        )

    # --- Cross-module helpers ----------------------------------------------------

    async def parent_for_child(self, child_id: str) -> str | None:
        conn = self._conn_or_raise()
        async with conn.execute(
            "SELECT parent_id FROM children WHERE child_id=?",
            (child_id,),
        ) as cur:
            row = await cur.fetchone()
        return row["parent_id"] if row else None

    async def get_parent_email(self, parent_id: str) -> str | None:
        """Return the stored email for a parent, or None."""
        conn = self._conn_or_raise()
        async with conn.execute(
            "SELECT email FROM parents WHERE parent_id=?",
            (parent_id,),
        ) as cur:
            row = await cur.fetchone()
        return row["email"] if row else None

    # --- FCM token (S3) ----------------------------------------------------------

    async def set_fcm_token(self, device_token: str, fcm_token: str) -> bool:
        """Store or update the FCM push token for a device_token row.

        Returns True if the device_token exists and was updated; False if not found.
        """
        conn = self._conn_or_raise()
        async with self._write_lock:
            cursor = await conn.execute(
                "UPDATE device_tokens SET fcm_token=? WHERE token=?",
                (fcm_token, device_token),
            )
            await conn.commit()
        updated = cursor.rowcount > 0
        if updated:
            log.info(
                "identity.fcm_token_set",
                token_prefix=device_token[:8],
            )
        else:
            log.warning(
                "identity.fcm_token_set_unknown_device",
                token_prefix=device_token[:8],
            )
        return updated

    async def fcm_token_for_parent(self, parent_id: str) -> str | None:
        """Return the most-recently-created FCM token for a parent-role device.

        Scans device_tokens where role='parent' and parent_id matches, ordered
        by created_at DESC, returns the first non-null fcm_token found.
        """
        conn = self._conn_or_raise()
        async with conn.execute(
            """
            SELECT fcm_token FROM device_tokens
            WHERE parent_id=? AND role='parent' AND fcm_token IS NOT NULL
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (parent_id,),
        ) as cur:
            row = await cur.fetchone()
        return row["fcm_token"] if row else None

    # --- Health ------------------------------------------------------------------

    async def health(self) -> tuple[HealthState, str]:
        try:
            conn = self._conn_or_raise()
            async with conn.execute("SELECT COUNT(*) AS n FROM children") as cur:
                row = await cur.fetchone()
            n = row["n"] if row else 0
            return (HealthState.OK, f"sqlite: {n} children")
        except Exception as exc:
            log.error("identity_store.health_failed", error=str(exc))
            return (HealthState.DOWN, f"sqlite health check failed: {exc}")
