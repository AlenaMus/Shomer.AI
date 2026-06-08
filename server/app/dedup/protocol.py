"""Public port for the Dedup module.

The DedupStore suppresses re-scroll / redraw storms on the monitor ingest
path. Each (child_id, text_hash) pair is "seen" for a configurable TTL; the
MonitorIngest orchestrator skips events whose (child_id, text_hash) is already
marked.

Concrete adapters:
    ``InMemoryTtlDedupStore`` — per-child dict of hash→expiry, evicts on access.
        Default for S1. Suitable for a single-process server.
    ``NullDedupStore``         — seen() always False, mark() no-op. Use for load
        tests where dedup should not interfere with throughput measurement.
    ``RedisDedupStore``        — (S6) Redis SETEX-based dedup for multi-process /
        multi-host deployments. Not implemented in S1; add when Redis is in the
        stack.

Reference: linked-yawning-sifakis.md §S1 "Ingest MVP".
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..schemas import HealthState


@runtime_checkable
class DedupStore(Protocol):
    """Port — check and mark (child_id, text_hash) pairs as seen.

    All methods are async so the Redis adapter (S6) can be a drop-in.
    """

    async def seen(self, child_id: str, text_hash: str) -> bool:
        """Return True if this (child_id, text_hash) pair was marked recently."""
        ...

    async def mark(self, child_id: str, text_hash: str, ttl_s: int = 3600) -> None:
        """Record the pair as seen for ``ttl_s`` seconds.

        Calling ``mark`` on an already-seen pair resets the TTL (idempotent
        with refresh semantics, which is the safe default for anti-storm use).
        """
        ...

    async def health(self) -> tuple[HealthState, str]:
        """Return (HealthState, detail_string) for the /health rollup."""
        ...
