"""Audit Log module — SQLite-backed persistent audit + conversation history.

Public surface:

  * Port + value types (import these everywhere except the composition root)::

        from server.app.audit_log import AuditStore, ConversationTurn, AuditRow

  * Concrete adapters + helpers (import ONLY in server/app/main.py lifespan())::

        from server.app.audit_log import (
            SqliteAuditStore, InMemoryAuditStore, AuditSettings, RetentionSweeper,
        )

See docs/design/audit_log/design.md.
"""

from __future__ import annotations

from .in_memory_adapter import InMemoryAuditStore
from .protocol import AuditRow, AuditStore, ConversationTurn
from .retention import RetentionSweeper
from .settings import AuditSettings
from .sqlite_adapter import SqliteAuditStore

__all__ = [
    # Port + value types
    "AuditStore",
    "AuditRow",
    "ConversationTurn",
    # Concrete adapters + composition-root helpers
    "SqliteAuditStore",
    "InMemoryAuditStore",
    "AuditSettings",
    "RetentionSweeper",
]
