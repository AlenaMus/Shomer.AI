"""Flagged Event module — parent-readable curated history of offensive/borderline events.

Public surface:

  * Port + value types (import everywhere except the composition root)::

        from server.app.flagged import FlaggedEventStore, FlaggedEvent

  * Concrete adapters + settings (import ONLY in server/app/main.py lifespan())::

        from server.app.flagged import (
            InMemoryFlaggedEventStore, SqliteFlaggedEventStore, FlaggedSettings,
        )

The FlaggedEventStore is separate from the AuditStore:
  - AuditStore: internal audit trail for ALL events (every classify call).
  - FlaggedEventStore: parent-facing surface for FLAGGED + BORDERLINE events only.

Reference: linked-yawning-sifakis.md §S1 "Ingest MVP".
"""

from __future__ import annotations

# Port + value types — downstream code imports these.
from .protocol import FlaggedEvent, FlaggedEventStore

# Concrete adapters + settings — composition root only.
from .in_memory_adapter import InMemoryFlaggedEventStore
from .settings import FlaggedSettings
from .sqlite_adapter import SqliteFlaggedEventStore

# Router registration — called from main.py.
from .router import register_parent_review

__all__ = [
    # Port + value types
    "FlaggedEventStore",
    "FlaggedEvent",
    # Concrete adapters + settings (composition root only)
    "InMemoryFlaggedEventStore",
    "SqliteFlaggedEventStore",
    "FlaggedSettings",
    # Router
    "register_parent_review",
]
