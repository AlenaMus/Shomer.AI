"""ReadHistoryTool — fetches the last N conversation turns from AuditStore.

Calls ``AuditStore.read_conversation_history()`` which is satisfied by the
``SqliteAuditStore`` in production and by ``FakeAuditStore`` in tests.

No LLM cost. Used deterministically before the main LLM call.

Reference: docs/design/context_agent/design.md §3.3.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ...audit_log.protocol import AuditStore


class ReadHistoryTool:
    """Fetches conversation history from the AuditStore for a child_id."""

    name = "read_history"
    description = "Read the last N conversation turns for this child from the audit store."
    parameters_schema = {
        "type": "object",
        "properties": {
            "child_id": {"type": "string", "description": "Child identifier."},
            "last_n_turns": {
                "type": "integer",
                "default": 5,
                "description": "Maximum number of prior turns to retrieve.",
            },
        },
        "required": ["child_id"],
    }

    def __init__(self, audit_store: "AuditStore") -> None:
        self._store = audit_store

    async def run(self, args: dict[str, Any]) -> dict[str, Any]:
        child_id: str = args["child_id"]
        last_n: int = int(args.get("last_n_turns", 5))
        turns = await self._store.read_conversation_history(
            child_id=child_id,
            last_n_turns=last_n,
        )
        return {
            "tool": self.name,
            "result": {
                "turns": [
                    {
                        "role": t.role,
                        "text": t.text,
                        "turn_index": t.turn_index,
                    }
                    for t in turns
                ],
                "turn_count": len(turns),
            },
        }
