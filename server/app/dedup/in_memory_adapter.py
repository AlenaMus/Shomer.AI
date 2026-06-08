"""InMemoryTtlDedupStore — in-process TTL-based dedup adapter.

Each child_id gets its own dict mapping ``text_hash`` → ``expiry_epoch``
(a ``time.monotonic()`` value).  Expiry is checked lazily on access.

Memory is bounded by ``max_per_child``: when a child's bucket exceeds the
cap, the oldest-expiry entries are evicted first (LRU-by-TTL approximation).
At MVP scale (≤100 children, ≤5000 entries each) this is fine without Redis.

This adapter mirrors the structure of ``InMemoryAlertRateLimiter`` in
``server/app/alerts/rate_limiter.py``.
"""

from __future__ import annotations

import time
from threading import Lock

from ..schemas import HealthState


class InMemoryTtlDedupStore:
    """InMemory DedupStore with per-child TTL buckets.

    Parameters
    ----------
    max_per_child:
        Maximum number of hash entries kept per child_id before the oldest
        (smallest expiry) entries are evicted.  Default: 5000.
    """

    def __init__(self, max_per_child: int = 5000) -> None:
        self._max_per_child = max_per_child
        # child_id -> {text_hash: expiry_monotonic}
        self._buckets: dict[str, dict[str, float]] = {}
        self._lock = Lock()
        self._total_marks = 0
        self._total_hits = 0

    # ------------------------------------------------------------------
    # DedupStore Protocol
    # ------------------------------------------------------------------

    async def seen(self, child_id: str, text_hash: str) -> bool:
        """Return True if (child_id, text_hash) is currently marked (not expired)."""
        now = time.monotonic()
        with self._lock:
            bucket = self._buckets.get(child_id)
            if bucket is None:
                return False
            expiry = bucket.get(text_hash)
            if expiry is None:
                return False
            if now > expiry:
                # Lazy eviction of this single expired entry.
                del bucket[text_hash]
                return False
            self._total_hits += 1
            return True

    async def mark(self, child_id: str, text_hash: str, ttl_s: int = 3600) -> None:
        """Record (child_id, text_hash) as seen for ``ttl_s`` seconds.

        If the child's bucket is at capacity, the entry with the smallest expiry
        is evicted first to make room.
        """
        expiry = time.monotonic() + ttl_s
        with self._lock:
            bucket = self._buckets.setdefault(child_id, {})
            # Enforce per-child cap — evict smallest-expiry entry.
            if len(bucket) >= self._max_per_child and text_hash not in bucket:
                oldest_key = min(bucket, key=lambda k: bucket[k])
                del bucket[oldest_key]
            bucket[text_hash] = expiry
            self._total_marks += 1

    async def health(self) -> tuple[HealthState, str]:
        with self._lock:
            child_count = len(self._buckets)
            total_entries = sum(len(b) for b in self._buckets.values())
        return (
            HealthState.OK,
            f"in-memory; {child_count} children, {total_entries} entries, "
            f"{self._total_marks} marks, {self._total_hits} hits",
        )
