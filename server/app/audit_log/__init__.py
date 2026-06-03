"""Audit Log module — SQLite-backed persistent audit + conversation history.

Public surface (port-only):

    from server.app.audit_log import AuditStore, ConversationTurn, AuditRow

See docs/design/audit_log/design.md.
"""

from __future__ import annotations

from .protocol import AuditRow, AuditStore, ConversationTurn

__all__ = ["AuditStore", "AuditRow", "ConversationTurn"]
