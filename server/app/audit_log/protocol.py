"""Public port for the Audit Log module.

Reference: docs/design/audit_log/design.md §2, §2.5.

This Protocol is consumed by FOUR other modules:
  - ``context_agent`` — uses ``read_conversation_history()`` for its
    ``read_history`` tool.
  - ``alerts`` — calls ``record_alert()`` after every FCM push.
  - ``server`` — calls ``record_classification()`` on the request path.
  - Meeting-8 evaluation tooling — uses ``query_for_evaluation()`` and
    ``set_gold_label()`` to assemble the ΔFPR analysis.

Concrete adapters: ``SqliteAuditStore`` (default), ``PostgresAuditStore``
(future scale-up), ``InMemoryAuditStore`` (tests), ``NullAuditStore``
(degraded-mode fallback when the DB is unreachable).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, AsyncIterator, Protocol, runtime_checkable

from ..schemas import (
    ClassificationResult,
    ContextDecision,
    HealthState,
    TriageDecision,
)


# ---------------------------------------------------------------------------
# Value types exposed by the Protocol.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConversationTurn:
    """One turn of conversation context — the unit of ``read_history``."""

    child_id: str
    turn_index: int
    role: str          # "child_outbound" | "child_inbound"
    text: str
    timestamp: float   # epoch seconds


@dataclass(frozen=True)
class AuditRow:
    """A row from ``query_for_evaluation()``. Used by the Meeting-8 ΔFPR query."""

    classification_id: int
    trace_id: str
    created_at: float
    classifier_label: str
    classifier_confidence: float
    is_offensive: bool
    triage_decision: TriageDecision
    context_agent_enabled: bool
    frontline_only_decision: str | None
    gold_label: str | None
    alert_id: str | None
    input_text: str
    child_id: str | None


# ---------------------------------------------------------------------------
# The Port.
# ---------------------------------------------------------------------------


@runtime_checkable
class AuditStore(Protocol):
    """Persistent audit + conversation history + Meeting-8 evaluation surface."""

    # --- Recording side ------------------------------------------------------

    async def record_classification(
        self,
        trace_id: str,
        request_text: str,
        classifier_result: ClassificationResult,
        triage_decision: TriageDecision,
        context_agent_enabled: bool,
        frontline_only_decision: str | None = None,
        child_id: str | None = None,
        message_id: str | None = None,
        input_type: str = "text",
        ocr_extracted_text: str | None = None,
        image_hash: str | None = None,
    ) -> int:
        """Insert into the ``classifications`` table; return classification_id."""
        ...

    async def record_agent_trace(
        self,
        classification_id: int,
        trace_id: str,
        agent_input: dict[str, Any],
        decision: ContextDecision,
        tools_called: list[dict[str, Any]],
    ) -> int:
        """Insert into the ``agent_traces`` table; return agent_trace_id."""
        ...

    async def record_alert(
        self,
        alert_id: str,
        trace_id: str,
        child_id: str,
        label: str,
        severity: str,
        quote_snippet: str,
        explanation: str,
        fcm_status: str = "queued",
        fcm_response_json: str | None = None,
    ) -> None:
        """Insert into the ``alerts`` table (idempotent on ``alert_id``)."""
        ...

    async def record_conversation_turn(
        self,
        child_id: str,
        turn_index: int,
        role: str,
        text: str,
    ) -> None: ...

    # --- Read side -----------------------------------------------------------

    async def read_conversation_history(
        self,
        child_id: str,
        last_n_turns: int = 5,
    ) -> list[ConversationTurn]:
        """Used by the Context Agent's ``read_history`` tool."""
        ...

    def query_for_evaluation(
        self,
        date_range: tuple[float, float],
        filters: dict[str, Any] | None = None,
    ) -> AsyncIterator[AuditRow]:
        """Stream rows for the Meeting-8 ΔFPR evaluation harness.

        NOTE: synchronous return type — the AsyncIterator itself is consumed
        with ``async for``. This shape matches sqlite3's cursor model and lets
        callers stream over millions of rows without loading them all.
        """
        ...

    # --- Annotation side -----------------------------------------------------

    async def set_gold_label(
        self,
        classification_id: int,
        label: str,
        annotator_id: str,
        notes: str | None = None,
    ) -> None: ...

    # --- Retention -----------------------------------------------------------

    async def cleanup_expired(self, retention_days: int = 7) -> int:
        """Delete rows older than ``retention_days``; return rows deleted.

        Called by the ``RetentionSweeper`` background task on a schedule
        (default every hour).
        """
        ...

    # --- Health --------------------------------------------------------------

    async def health(self) -> tuple[HealthState, str]: ...
