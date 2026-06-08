"""Public ports for the Digest module (S3 — Daily digest + FCM push).

Reference: linked-yawning-sifakis.md §S3.

The DigestScheduler aggregates each child's day of flagged + borderline events
into ONE digest and delivers it (FCM push) to the parent, once per day.

The DigestStore persists built digests so ``GET /v1/parent/digests/{date}``
can read them on demand.

Design invariant:
  - ``now``, ``day_start``, and ``day_end`` are ALWAYS injected (never read
    from wall-clock inside aggregation/delivery logic) so tests are fully
    deterministic.
  - The ``AsyncioCronDigestScheduler`` is the ONLY place real time/sleep lives.
  - At least TWO adapters exist for each Protocol: one real (Asyncio/Sqlite)
    and one deterministic (Manual/InMemory) for tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from ..schemas import AlertSource, Category, FlaggedStatus, HealthState, Severity


# ---------------------------------------------------------------------------
# Value types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DigestEntry:
    """One flagged event summarised for inclusion in a ChildDigest.

    ``quote`` is already capped at <=200 chars by FlaggedEventStore.
    """

    flag_id: str
    app_package: str
    direction: str            # "inbound" | "outbound"
    label: Category
    severity: Severity
    quote: str                # already <=200
    status: FlaggedStatus
    created_at: float         # epoch seconds


@dataclass(frozen=True)
class ChildDigest:
    """Aggregated daily digest for one child.

    Persisted by DigestStore and returned by ``GET /v1/parent/digests/{date}``.
    ``date`` is the server-local date the digest covers (``"YYYY-MM-DD"``).
    ``entries`` are capped (``DIGEST_MAX_ENTRIES``, default 50) and sorted
    most-severe-first.
    """

    child_id: str
    parent_id: str
    date: str                          # "YYYY-MM-DD" (server-local date)
    generated_at: float                # epoch seconds when the digest was built
    total_flagged: int                 # total events in the window (incl. capped)
    review_needed: int                 # count with status "review_needed"
    by_severity: dict[str, int]        # {"low": N, "medium": N, ...}
    by_label: dict[str, int]           # {"abusive": N, "hate": N, ...}
    entries: list[DigestEntry]         # capped, most-severe-first


# ---------------------------------------------------------------------------
# DigestScheduler Port
# ---------------------------------------------------------------------------


@runtime_checkable
class DigestScheduler(Protocol):
    """Port: aggregate flagged events → build digest → deliver via push channel.

    Concrete adapters:
      - ``AsyncioCronDigestScheduler`` — background asyncio task, real time/sleep.
      - ``ManualDigestRunner`` — no background loop; run_once/deliver callable on
        demand (tests + ``POST /internal/digest/run``).
    """

    async def build_digest(
        self,
        child_id: str,
        parent_id: str,
        *,
        day_start: float,
        day_end: float,
    ) -> ChildDigest:
        """Build (but do NOT deliver) a digest for one child over [day_start, day_end).

        Pulls ``flagged.list_for_child(child_id, since=day_start, include_acked=True)``,
        filters to ``created_at < day_end``, aggregates.  Does NOT call wall-clock time.
        """
        ...

    async def run_once(self, *, now: float) -> list[ChildDigest]:
        """Build + deliver ONE digest per child with flagged activity since midnight.

        ``now`` is epoch seconds (injected so tests are deterministic).
        Returns the list of digests built (one per active child).
        """
        ...

    async def deliver(self, digest: ChildDigest) -> bool:
        """Resolve parent FCM token → send via NotificationChannel → save to store.

        Returns True if the push was sent (sent=True from the channel), else False.
        Never raises.
        """
        ...

    async def health(self) -> tuple[HealthState, str]:
        """Return (HealthState, detail_string) for the /health rollup."""
        ...


# ---------------------------------------------------------------------------
# DigestStore Port
# ---------------------------------------------------------------------------


@runtime_checkable
class DigestStore(Protocol):
    """Port: persist and query built digests.

    Concrete adapters:
      - ``SqliteDigestStore`` — one ``digests`` table (persistent).
      - ``InMemoryDigestStore`` — dict (tests, no I/O).
    """

    async def save(self, digest: ChildDigest) -> None:
        """Persist a digest (idempotent on child_id + date — last write wins)."""
        ...

    async def get(self, child_id: str, date: str) -> ChildDigest | None:
        """Return the digest for (child_id, date), or None if not built yet."""
        ...

    async def list_for_child(
        self,
        child_id: str,
        limit: int = 30,
    ) -> list[ChildDigest]:
        """Return recent digests for a child, newest-first."""
        ...

    async def health(self) -> tuple[HealthState, str]:
        """Return (HealthState, detail_string) for the /health rollup."""
        ...
