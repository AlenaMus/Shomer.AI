"""In-memory AuditStore — stop-gap before SqliteAuditStore lands.

This adapter satisfies the ``AuditStore`` Protocol with pure process memory.
It is **NOT** for production — data is lost on restart, and there is no
disk-backed retention.

Use case: local dev + smoke tests + composition-root default so the rest of
the pipeline (Context Agent's ``read_history`` tool, server's
``record_classification`` call after every ``/classify``) has SOMETHING to
talk to. Once ``AUDIT-SCHEMA-01`` ships ``SqliteAuditStore``, swap is one
line in ``main.py`` lifespan().
"""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Any, AsyncIterator

from ..schemas import (
    ClassificationResult,
    ContextDecision,
    HealthState,
    TriageDecision,
)
from .protocol import AuditRow, ConversationTurn


class InMemoryAuditStore:
    """In-process implementation of the AuditStore Protocol."""

    def __init__(self) -> None:
        self._classifications: list[dict[str, Any]] = []
        self._agent_traces: list[dict[str, Any]] = []
        self._alerts: dict[str, dict[str, Any]] = {}  # idempotent on alert_id
        self._conversations: dict[str, list[ConversationTurn]] = defaultdict(list)
        self._gold_labels: dict[int, dict[str, Any]] = {}
        self._next_id = 1

    def _alloc_id(self) -> int:
        nid = self._next_id
        self._next_id += 1
        return nid

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
        cid = self._alloc_id()
        self._classifications.append({
            "id": cid,
            "trace_id": trace_id,
            "created_at": time.time(),
            "input_text": request_text,
            "label": classifier_result.label,
            "confidence": classifier_result.confidence,
            "is_offensive": classifier_result.is_offensive,
            "triage": triage_decision,
            "context_agent_enabled": context_agent_enabled,
            "frontline_only_decision": frontline_only_decision,
            "child_id": child_id,
            "message_id": message_id,
            "input_type": input_type,
            "ocr_extracted_text": ocr_extracted_text,
            "image_hash": image_hash,
            "alert_id": None,
        })
        return cid

    async def record_agent_trace(
        self,
        classification_id: int,
        trace_id: str,
        agent_input: dict[str, Any],
        decision: ContextDecision,
        tools_called: list[dict[str, Any]],
    ) -> int:
        tid = self._alloc_id()
        self._agent_traces.append({
            "id": tid,
            "classification_id": classification_id,
            "trace_id": trace_id,
            "agent_input": agent_input,
            "decision": decision,
            "tools_called": tools_called,
            "created_at": time.time(),
        })
        return tid

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
        if alert_id in self._alerts:
            return  # idempotent
        self._alerts[alert_id] = {
            "alert_id": alert_id,
            "trace_id": trace_id,
            "child_id": child_id,
            "label": label,
            "severity": severity,
            "quote_snippet": quote_snippet,
            "explanation": explanation,
            "fcm_status": fcm_status,
            "fcm_response_json": fcm_response_json,
            "created_at": time.time(),
        }

    async def record_conversation_turn(
        self, child_id: str, turn_index: int, role: str, text: str
    ) -> None:
        self._conversations[child_id].append(
            ConversationTurn(
                child_id=child_id,
                turn_index=turn_index,
                role=role,
                text=text,
                timestamp=time.time(),
            )
        )

    async def read_conversation_history(
        self, child_id: str, last_n_turns: int = 5
    ) -> list[ConversationTurn]:
        turns = self._conversations.get(child_id, [])
        return list(turns[-last_n_turns:])

    def query_for_evaluation(
        self,
        date_range: tuple[float, float],
        filters: dict[str, Any] | None = None,
    ) -> AsyncIterator[AuditRow]:
        async def _iter() -> AsyncIterator[AuditRow]:
            t0, t1 = date_range
            for row in self._classifications:
                if not (t0 <= row["created_at"] <= t1):
                    continue
                yield AuditRow(
                    classification_id=row["id"],
                    trace_id=row["trace_id"],
                    created_at=row["created_at"],
                    classifier_label=row["label"],
                    classifier_confidence=row["confidence"],
                    is_offensive=row["is_offensive"],
                    triage_decision=row["triage"],
                    context_agent_enabled=row["context_agent_enabled"],
                    frontline_only_decision=row["frontline_only_decision"],
                    gold_label=self._gold_labels.get(row["id"], {}).get("label"),
                    alert_id=row["alert_id"],
                    input_text=row["input_text"],
                    child_id=row["child_id"],
                )

        return _iter()

    async def set_gold_label(
        self,
        classification_id: int,
        label: str,
        annotator_id: str,
        notes: str | None = None,
    ) -> None:
        self._gold_labels[classification_id] = {
            "label": label,
            "annotator_id": annotator_id,
            "notes": notes,
            "annotated_at": time.time(),
        }

    async def cleanup_expired(self, retention_days: int = 7) -> int:
        cutoff = time.time() - retention_days * 86400
        before = len(self._classifications)
        self._classifications = [r for r in self._classifications if r["created_at"] >= cutoff]
        self._agent_traces = [t for t in self._agent_traces if t["created_at"] >= cutoff]
        self._alerts = {k: v for k, v in self._alerts.items() if v["created_at"] >= cutoff}
        for child_id in list(self._conversations.keys()):
            self._conversations[child_id] = [
                t for t in self._conversations[child_id] if t.timestamp >= cutoff
            ]
        return before - len(self._classifications)

    async def health(self) -> tuple[HealthState, str]:
        return (
            HealthState.OK,
            f"in-memory; {len(self._classifications)} classifications, "
            f"{len(self._conversations)} children",
        )
