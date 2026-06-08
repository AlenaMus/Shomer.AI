"""NullDedupStore — no-op dedup adapter for load tests and diagnostics.

``seen()`` always returns False (nothing is ever "seen"), and ``mark()`` is a
no-op.  Use this adapter when you want to measure ingest throughput without
dedup overhead, or in integration tests where you explicitly do NOT want
dedup to interfere.

This satisfies the ≥2-adapter rule for the DedupStore port (InMemory + Null).
Redis (S6) will be the third adapter for multi-process deployments.
"""

from __future__ import annotations

from ..schemas import HealthState


class NullDedupStore:
    """DedupStore that never suppresses anything.

    Use for load tests (``DEDUP_BACKEND=null``) or integration test scenarios
    where dedup should be transparent.
    """

    async def seen(self, child_id: str, text_hash: str) -> bool:  # noqa: ARG002
        """Always returns False — every event is treated as new."""
        return False

    async def mark(self, child_id: str, text_hash: str, ttl_s: int = 3600) -> None:  # noqa: ARG002
        """No-op — nothing is recorded."""

    async def health(self) -> tuple[HealthState, str]:
        return (HealthState.OK, "null dedup store — no suppression active")
