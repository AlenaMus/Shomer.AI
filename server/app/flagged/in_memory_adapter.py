"""InMemoryFlaggedEventStore — in-process adapter for the FlaggedEventStore port.

All data is stored in a dict keyed by ``flag_id``.  Not durable across restarts.
Default for S1 (``FLAGGED_BACKEND=memory``).

``SqliteFlaggedEventStore`` is the S4 durable drop-in; swap is one line in
``main.py`` lifespan().
"""

from __future__ import annotations

import time
from threading import Lock

from ..schemas import HealthState
from .protocol import FlaggedEvent


class InMemoryFlaggedEventStore:
    """In-memory FlaggedEventStore — dict keyed by flag_id."""

    def __init__(self) -> None:
        self._events: dict[str, FlaggedEvent] = {}
        self._lock = Lock()

    # ------------------------------------------------------------------
    # FlaggedEventStore Protocol
    # ------------------------------------------------------------------

    async def record(self, event: FlaggedEvent) -> None:
        """Persist event; idempotent on flag_id (first write wins)."""
        with self._lock:
            if event.flag_id not in self._events:
                self._events[event.flag_id] = event

    async def list_for_child(
        self,
        child_id: str,
        *,
        since: float | None = None,
        limit: int = 50,
        include_acked: bool = False,
    ) -> list[FlaggedEvent]:
        """Return events for child_id, newest-first."""
        with self._lock:
            events = list(self._events.values())

        filtered = [
            e for e in events
            if e.child_id == child_id
            and (since is None or e.created_at >= since)
            and (include_acked or e.status not in ("acknowledged", "labeled"))
        ]
        # Sort newest-first.
        filtered.sort(key=lambda e: e.created_at, reverse=True)
        return filtered[:limit]

    async def get(self, flag_id: str) -> FlaggedEvent | None:
        with self._lock:
            return self._events.get(flag_id)

    async def acknowledge(self, flag_id: str, parent_id: str) -> bool:  # noqa: ARG002
        """Mark event acknowledged; parent_id is accepted but not stored in S1."""
        with self._lock:
            event = self._events.get(flag_id)
            if event is None:
                return False
            # Replace with updated fields (frozen dataclass — use object replace).
            from dataclasses import replace
            self._events[flag_id] = replace(
                event,
                status="acknowledged",
                acknowledged_at=time.time(),
            )
            return True

    async def set_parent_label(
        self, flag_id: str, label: str, severity: str | None
    ) -> bool:
        with self._lock:
            event = self._events.get(flag_id)
            if event is None:
                return False
            from dataclasses import replace
            self._events[flag_id] = replace(
                event,
                status="labeled",
                parent_label=label,
                parent_severity=severity,
            )
            return True

    async def set_parent_severity(self, flag_id: str, severity: str) -> bool:
        """Set parent_severity; transitions status to 'labeled'."""
        with self._lock:
            event = self._events.get(flag_id)
            if event is None:
                return False
            from dataclasses import replace
            self._events[flag_id] = replace(
                event,
                status="labeled",
                parent_severity=severity,
            )
            return True

    async def child_ids_with_events_since(self, since: float) -> list[str]:
        """Return distinct child_ids with events created_at >= since."""
        with self._lock:
            ids = {
                e.child_id
                for e in self._events.values()
                if e.created_at >= since
            }
        return list(ids)

    async def health(self) -> tuple[HealthState, str]:
        with self._lock:
            total = len(self._events)
            pending = sum(
                1 for e in self._events.values()
                if e.status in ("alerted", "review_needed")
            )
        return (
            HealthState.OK,
            f"in-memory; {total} flagged events, {pending} pending parent review",
        )
