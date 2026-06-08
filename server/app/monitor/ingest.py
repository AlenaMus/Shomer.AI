"""MonitorIngest — batch ingest orchestrator for the monitor path.

This is an APPLICATION SERVICE (not a swappable port). It lives at
``app.state.monitor`` and is constructed once in ``main.py`` lifespan().

Wiring choice: ``_run_pipeline`` is passed in as a callable (``pipeline_fn``)
from ``lifespan()`` rather than imported from ``main.py`` directly.  This
avoids a circular import (``monitor.ingest`` → ``main`` → ``monitor.router`` →
``monitor.ingest``) and matches the composition-root DI style: the composition
root owns all wiring, and this class receives its collaborators as constructor
arguments.

Per-event flow
--------------
1. If ``DedupStore.seen(child_id, text_hash)`` → ack "deduped", skip.
2. ``DedupStore.mark(child_id, text_hash, ttl)`` — record as seen.
3. Call ``pipeline_fn(request, text, ...)`` → ``(ClassificationResult, TriageDecision)``.
4. If ALERT_DIRECT → build FlaggedEvent(status="alerted").
   If ESCALATE_TO_CA or REVIEW_NEEDED → FlaggedEvent(status="review_needed").
   Else (SILENT) → not flagged.
5. ``FlaggedEventStore.record(event)`` — best-effort.
6. Ack "processed", flagged=True/False.

One bad event acks "error" without failing the whole batch (best-effort).
"""

from __future__ import annotations

import hashlib
import time
from typing import Any, Awaitable, Callable

import structlog

from ..dedup import DedupStore
from ..dedup.settings import DedupSettings
from ..flagged import FlaggedEvent, FlaggedEventStore
from ..schemas import (
    AlertSource,
    Category,
    FlaggedStatus,
    MonitorBatchRequest,
    MonitorBatchResponse,
    MonitorEventAck,
    Severity,
    TriageDecision,
)

log = structlog.get_logger("shomer.monitor.ingest")

# The pipeline callable signature injected from lifespan():
#   async (request, text, *, trace_id, child_id, message_id, input_type) -> (result, decision)
PipelineFn = Callable[..., Awaitable[tuple[Any, TriageDecision]]]
DeriveSeverityFn = Callable[[Category, float], Severity]

# Critical-immediate callback: (flagged_event) -> None.
# Injected from lifespan() so MonitorIngest has no import-time dependency on
# the digest or identity concrete adapters.  The callback is optional — when
# None, critical-immediate push is disabled.
OnCriticalFlagFn = Callable[[FlaggedEvent], Awaitable[None]]


class MonitorIngest:
    """Batch ingest orchestrator — fans events into ``_run_pipeline``.

    Parameters
    ----------
    pipeline_fn:
        The ``_run_pipeline`` callable from ``main.py``, injected by the
        composition root so this class has no import-time dependency on main.
    dedup:
        A ``DedupStore`` Protocol implementation.
    flagged:
        A ``FlaggedEventStore`` Protocol implementation.
    derive_severity:
        The ``derive_severity(label, confidence) -> Severity`` function from
        ``server/app/alerts/severity.py``, injected to avoid re-implementing
        severity logic here.
    dedup_ttl_s:
        TTL for dedup marks (default from ``DedupSettings``).
    """

    def __init__(
        self,
        pipeline_fn: PipelineFn,
        dedup: DedupStore,
        flagged: FlaggedEventStore,
        derive_severity: DeriveSeverityFn,
        dedup_ttl_s: int = 3600,
        on_critical_flag: OnCriticalFlagFn | None = None,
    ) -> None:
        self._pipeline = pipeline_fn
        self._dedup = dedup
        self._flagged = flagged
        self._derive_severity = derive_severity
        self._dedup_ttl_s = dedup_ttl_s
        # Optional callback injected from lifespan() for critical-immediate push
        # (S3).  MonitorIngest has no import-time dependency on digest/identity.
        self._on_critical_flag = on_critical_flag

    async def ingest_batch(
        self,
        request: Any,  # fastapi.Request — typed as Any to keep this import-free
        batch: MonitorBatchRequest,
        *,
        trace_id: str,
    ) -> MonitorBatchResponse:
        """Process a batch of MonitorEvents; return per-event acks + tallies."""
        child_id = batch.child_id
        accepted = 0
        deduped = 0
        flagged_count = 0
        acks: list[MonitorEventAck] = []

        for event in batch.events:
            try:
                ack = await self._process_event(
                    request, child_id, event, trace_id=trace_id
                )
            except Exception as exc:  # noqa: BLE001 — one bad event must not fail batch
                log.warning(
                    "monitor.event_error",
                    client_msg_id=event.client_msg_id,
                    error=str(exc),
                    trace_id=trace_id,
                )
                ack = MonitorEventAck(
                    client_msg_id=event.client_msg_id,
                    status="error",
                    flagged=False,
                )

            acks.append(ack)

            if ack.status == "deduped":
                deduped += 1
            elif ack.status != "error":
                accepted += 1
                if ack.flagged:
                    flagged_count += 1

        log.info(
            "monitor.batch_processed",
            trace_id=trace_id,
            child_id=child_id,
            session_id=batch.session_id,
            total=len(batch.events),
            accepted=accepted,
            deduped=deduped,
            flagged=flagged_count,
        )

        return MonitorBatchResponse(
            accepted=accepted,
            deduped=deduped,
            flagged=flagged_count,
            acks=acks,
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _process_event(
        self,
        request: Any,
        child_id: str,
        event: Any,
        *,
        trace_id: str,
    ) -> MonitorEventAck:
        """Process one MonitorEvent and return its ack."""

        # Step 1 — dedup check.
        if await self._dedup.seen(child_id, event.text_hash):
            log.debug(
                "monitor.deduped",
                client_msg_id=event.client_msg_id,
                child_id=child_id,
                trace_id=trace_id,
            )
            return MonitorEventAck(
                client_msg_id=event.client_msg_id,
                status="deduped",
                flagged=False,
            )

        # Step 2 — mark as seen (reset TTL if already exists).
        await self._dedup.mark(child_id, event.text_hash, self._dedup_ttl_s)

        # Step 3 — run through the existing classify → triage → CA pipeline.
        result, decision = await self._pipeline(
            request,
            event.text,
            trace_id=trace_id,
            child_id=child_id,
            message_id=event.client_msg_id,
            input_type="monitor",
        )

        # Step 4 — decide whether to flag and build the FlaggedEvent.
        flag_id: str | None = None
        flag_status: FlaggedStatus | None = None

        if decision == TriageDecision.ALERT_DIRECT:
            flag_status = "alerted"
        elif decision in (TriageDecision.ESCALATE_TO_CA, TriageDecision.REVIEW_NEEDED):
            flag_status = "review_needed"
        # SILENT — not flagged.

        flagged = flag_status is not None

        if flagged:
            flag_id = _make_flag_id(child_id, event.client_msg_id)
            explanation = _make_explanation(flag_status, result.label)

            # Determine the source based on the triage path.
            source: AlertSource
            if decision == TriageDecision.ALERT_DIRECT:
                source = "frontline_direct"
            else:
                source = "fallback_review"

            flagged_event = FlaggedEvent(
                flag_id=flag_id,
                child_id=child_id,
                created_at=time.time(),
                app_package=event.app_package,
                direction=event.direction,
                label=result.label,
                severity=self._derive_severity(result.label, result.confidence),
                quote=event.text[:200],
                explanation=explanation,
                source=source,
                trace_id=trace_id,
                status=flag_status,
            )

            # Step 5 — record (best-effort; error is logged, not propagated).
            try:
                await self._flagged.record(flagged_event)
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "monitor.flagged_record_failed",
                    flag_id=flag_id,
                    error=str(exc),
                )

            log.info(
                "monitor.flagged",
                trace_id=trace_id,
                flag_id=flag_id,
                child_id=child_id,
                label=result.label,
                decision=decision.value,
                flag_status=flag_status,
            )

            # Step 6 — critical-immediate push (S3).
            # Only for events with status="alerted" (ALERT_DIRECT path) with
            # high/critical severity.  The callback is injected from lifespan()
            # so this class has no import-time dependency on digest/identity.
            if (
                self._on_critical_flag is not None
                and flag_status == "alerted"
                and flagged_event.severity in ("high", "critical")
            ):
                try:
                    await self._on_critical_flag(flagged_event)
                except Exception as exc:  # noqa: BLE001 — best-effort
                    log.warning(
                        "monitor.critical_immediate_failed",
                        flag_id=flag_id,
                        error=str(exc),
                    )

        return MonitorEventAck(
            client_msg_id=event.client_msg_id,
            status="processed",
            flagged=flagged,
            flag_id=flag_id,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_flag_id(child_id: str, client_msg_id: str) -> str:
    """Deterministic idempotency key: sha256(child_id:client_msg_id)[:16]."""
    raw = f"{child_id}:{client_msg_id}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _make_explanation(flag_status: str, label: str) -> str:
    """Return a one-sentence Hebrew explanation for the parent."""
    if flag_status == "alerted":
        return f"זוהתה הודעה פוגענית מסוג {label}."
    # review_needed — borderline case.
    return "הודעה גבולית שממתינה לבדיקת הורה."
