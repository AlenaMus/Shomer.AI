"""Dedup module — per-(child_id, text_hash) TTL-based dedup for monitor ingest.

Public surface:

  * Port (import everywhere except the composition root)::

        from server.app.dedup import DedupStore

  * Concrete adapters + settings (import ONLY in server/app/main.py lifespan())::

        from server.app.dedup import (
            InMemoryTtlDedupStore, NullDedupStore, DedupSettings,
        )

Scale-up note: ``RedisDedupStore`` (S6) is the scale-up adapter for
multi-process / multi-host deployments. Not implemented in S1; add it here
and wire it in ``main.py`` lifespan() when Redis is in the stack.

Reference: linked-yawning-sifakis.md §S1 "Ingest MVP".
"""

from __future__ import annotations

# Port — everyone imports this.
from .protocol import DedupStore

# Concrete adapters + settings — composition root only.
from .in_memory_adapter import InMemoryTtlDedupStore
from .null_adapter import NullDedupStore
from .settings import DedupSettings

__all__ = [
    # Port
    "DedupStore",
    # Concrete adapters + settings (composition root only)
    "InMemoryTtlDedupStore",
    "NullDedupStore",
    "DedupSettings",
]
