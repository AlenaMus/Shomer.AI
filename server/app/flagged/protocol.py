"""Public port for the Flagged Event module.

The FlaggedEventStore holds the parent-readable curated history of events that
the pipeline determined were offensive (ALERT_DIRECT) or borderline
(ESCALATE_TO_CA / REVIEW_NEEDED).  It is separate from the AuditStore: the
AuditStore is an internal audit trail for all events; the FlaggedEventStore is
the parent-facing surface for flagged and borderline events only.

``FlaggedEvent`` is defined here (not in schemas.py) following the same
convention as ``ConversationTurn`` in ``audit_log/protocol.py``.

Concrete adapters:
    ``InMemoryFlaggedEventStore`` — dict keyed by flag_id; fast, non-durable.
        Default for S1. Suitable for development and tests.
    ``SqliteFlaggedEventStore``   — one ``flagged_events`` table; durable.
        S1 implements it so the S4 swap to durable storage is a one-line change.
    ``PostgresFlaggedEventStore`` — (future) for production scale.

Reference: linked-yawning-sifakis.md §S1 "Ingest MVP".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ..schemas import AlertSource, Category, FlaggedStatus, HealthState, Severity


# ---------------------------------------------------------------------------
# Value type: FlaggedEvent
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FlaggedEvent:
    """One parent-visible flagged / borderline event.

    ``flag_id`` is the idempotency key: ``sha256(f"{child_id}:{client_msg_id}")[:16]``.
    ``quote`` is truncated to ≤200 chars server-side before storage.
    ``explanation`` is a one-sentence Hebrew rationale for the parent.
    ``status`` follows the ``FlaggedStatus`` lifecycle:
        "alerted"       → pipeline sent an immediate alert (ALERT_DIRECT)
        "review_needed" → borderline case waiting for parent verdict
        "acknowledged"  → parent dismissed without labelling
        "labeled"       → parent assigned a verdict (feeds training data)
    """

    flag_id: str              # sha256(child_id:client_msg_id)[:16]
    child_id: str
    created_at: float         # epoch seconds (server clock)
    app_package: str          # source app, e.g. "com.whatsapp"
    direction: str            # "inbound" | "outbound"
    label: Category
    severity: Severity
    quote: str                # ≤200 chars, already truncated
    explanation: str          # parent-facing Hebrew sentence
    source: AlertSource
    trace_id: str
    status: FlaggedStatus
    parent_label: str | None = None        # parent verdict label (S4)
    parent_severity: str | None = None     # parent severity override (S4)
    acknowledged_at: float | None = None   # epoch seconds when parent acked


# ---------------------------------------------------------------------------
# The Port
# ---------------------------------------------------------------------------


@runtime_checkable
class FlaggedEventStore(Protocol):
    """Port — store and query parent-visible flagged / borderline events."""

    async def record(self, event: FlaggedEvent) -> None:
        """Persist a FlaggedEvent (idempotent on ``flag_id``).

        If an event with the same ``flag_id`` already exists, this is a no-op
        (first write wins — prevents double-recording on pipeline retry).
        """
        ...

    async def list_for_child(
        self,
        child_id: str,
        *,
        since: float | None = None,
        limit: int = 50,
        include_acked: bool = False,
    ) -> list[FlaggedEvent]:
        """Return flagged events for a child, newest-first.

        Parameters
        ----------
        child_id:
            Opaque child identifier.
        since:
            If given, only return events with ``created_at >= since`` (epoch s).
        limit:
            Maximum number of events to return.
        include_acked:
            When False (default), exclude events with status "acknowledged" or
            "labeled" — only show pending items to the parent dashboard.
            When True, return all events (for export / training data).
        """
        ...

    async def get(self, flag_id: str) -> FlaggedEvent | None:
        """Return the event for ``flag_id``, or None if not found."""
        ...

    async def acknowledge(self, flag_id: str, parent_id: str) -> bool:
        """Mark a flagged event as acknowledged by the parent.

        Returns True if the event was found and updated; False if not found.
        ``parent_id`` is logged for audit but not stored in S1 (IdentityStore
        not yet wired); store it when S2 adds IdentityStore.
        """
        ...

    async def set_parent_label(
        self, flag_id: str, label: str, severity: str | None
    ) -> bool:
        """Record the parent's human verdict on a flagged event.

        Returns True if updated, False if not found.
        The ``label`` is stored in ``parent_label`` and feeds the DictaBERT
        training pipeline (labeled examples from the borderline slice).
        ``severity`` is the parent's perceived severity override; None means
        "keep the system-derived severity".
        """
        ...

    async def set_parent_severity(self, flag_id: str, severity: str) -> bool:
        """Record the parent's severity override on a flagged event.

        Returns True if updated, False if not found.
        Sets ``parent_severity`` and transitions status to ``labeled`` so the
        event is trackable as human-reviewed.  Does not change ``parent_label``.
        """
        ...

    async def child_ids_with_events_since(self, since: float) -> list[str]:
        """Return distinct child_ids with at least one event created_at >= since.

        Used by DigestScheduler (S3) to discover which children need a digest.
        Returns an empty list if no events match.
        """
        ...

    async def health(self) -> tuple[HealthState, str]:
        """Return (HealthState, detail_string) for the /health rollup."""
        ...
