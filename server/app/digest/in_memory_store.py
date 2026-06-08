"""InMemoryDigestStore — fast, non-durable DigestStore adapter.

All data lives in a plain dict keyed by ``(child_id, date)``.  Not persistent
across restarts.  Used in tests and when ``DIGEST_BACKEND=manual`` with no SQLite.

Reference: linked-yawning-sifakis.md §S3 "Persist digests".
"""

from __future__ import annotations

from threading import Lock

import structlog

from ..schemas import HealthState
from .protocol import ChildDigest

log = structlog.get_logger("shomer.digest.memory")


class InMemoryDigestStore:
    """In-memory DigestStore — dict keyed by (child_id, date)."""

    def __init__(self) -> None:
        # (child_id, date) → ChildDigest
        self._store: dict[tuple[str, str], ChildDigest] = {}
        self._lock = Lock()

    async def save(self, digest: ChildDigest) -> None:
        """Persist a digest; last write wins."""
        with self._lock:
            self._store[(digest.child_id, digest.date)] = digest
        log.debug(
            "digest_store.saved",
            child_id=digest.child_id,
            date=digest.date,
            total=digest.total_flagged,
        )

    async def get(self, child_id: str, date: str) -> ChildDigest | None:
        with self._lock:
            return self._store.get((child_id, date))

    async def list_for_child(
        self,
        child_id: str,
        limit: int = 30,
    ) -> list[ChildDigest]:
        with self._lock:
            digests = [d for (cid, _), d in self._store.items() if cid == child_id]
        digests.sort(key=lambda d: d.generated_at, reverse=True)
        return digests[:limit]

    async def health(self) -> tuple[HealthState, str]:
        with self._lock:
            n = len(self._store)
        return (HealthState.OK, f"in_memory: {n} digests stored")
