"""ManualDigestRunner — deterministic DigestScheduler adapter.

No background loop. ``run_once`` and ``deliver`` are callable on demand.
Used for:
  - Tests (inject ``now`` → fully deterministic, no sleeping).
  - ``POST /internal/digest/run`` (force-trigger for demo/test).
  - External-cron story (``ExternalCronDigestRunner`` sub-story deferred to S6).

The aggregation and delivery logic lives HERE so both adapters (Manual and
AsyncioCron) share the same implementation via composition: the AsyncioCron
adapter wraps a ManualDigestRunner internally.

Reference: linked-yawning-sifakis.md §S3.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Awaitable, Callable

import structlog

from ..alerts.protocol import NotificationChannel
from ..flagged.protocol import FlaggedEventStore
from ..schemas import AlertRequest, Category, HealthState, Severity
from .protocol import ChildDigest, DigestEntry, DigestStore

log = structlog.get_logger("shomer.digest.manual")

# Callback type: (child_id) -> parent_id | None
ParentForChildFn = Callable[[str], Awaitable[str | None]]
# Callback type: (parent_id) -> fcm_token | None
FcmTokenForParentFn = Callable[[str], Awaitable[str | None]]
# Callback type: (parent_id) -> list[child_id]  (all children under parent)
ChildIdsFn = Callable[[str], Awaitable[list[str]]]
# The function that returns all distinct child_ids with events since a timestamp
ActiveChildIdsFn = Callable[[float], Awaitable[list[str]]]

_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def _severity_key(entry: DigestEntry) -> int:
    return _SEVERITY_ORDER.get(entry.severity, 99)


class ManualDigestRunner:
    """Deterministic DigestScheduler adapter — no background loop.

    Parameters
    ----------
    flagged:
        ``FlaggedEventStore`` — the source of events to aggregate.
    digest_store:
        ``DigestStore`` — where built digests are persisted.
    channel:
        ``NotificationChannel`` — used to deliver push notifications.
    parent_for_child_fn:
        Async callable ``(child_id) -> parent_id | None``.  Injected from
        ``identity.parent_for_child`` via the composition root — keeps this
        class import-free of the identity concrete adapter.
    fcm_token_for_parent_fn:
        Async callable ``(parent_id) -> fcm_token | None``.  Injected from
        ``identity.fcm_token_for_parent``.
    active_child_ids_fn:
        Async callable ``(since: float) -> list[child_id]``.  Returns all
        child_ids with flagged events created at >= since.  Injected from
        ``flagged.child_ids_with_events_since``.
    max_entries:
        Maximum DigestEntry items per digest (default 50).
    """

    def __init__(
        self,
        flagged: FlaggedEventStore,
        digest_store: DigestStore,
        channel: NotificationChannel,
        parent_for_child_fn: ParentForChildFn,
        fcm_token_for_parent_fn: FcmTokenForParentFn,
        active_child_ids_fn: ActiveChildIdsFn,
        max_entries: int = 50,
    ) -> None:
        self._flagged = flagged
        self._digest_store = digest_store
        self._channel = channel
        self._parent_for_child = parent_for_child_fn
        self._fcm_token_for_parent = fcm_token_for_parent_fn
        self._active_child_ids = active_child_ids_fn
        self._max_entries = max_entries

    # ------------------------------------------------------------------
    # DigestScheduler Protocol
    # ------------------------------------------------------------------

    async def build_digest(
        self,
        child_id: str,
        parent_id: str,
        *,
        day_start: float,
        day_end: float,
    ) -> ChildDigest:
        """Build a digest for one child over [day_start, day_end).

        Pulls all flagged events (include_acked=True so the parent sees the
        full day picture, not just pending items).  Events outside the window
        are excluded.  Entries are capped at ``max_entries``, most-severe-first.
        """
        events = await self._flagged.list_for_child(
            child_id,
            since=day_start,
            include_acked=True,
            limit=5000,  # large enough to capture the full day before capping
        )
        # Filter strictly to the window [day_start, day_end).
        events = [e for e in events if e.created_at < day_end]

        # Aggregate.
        total = len(events)
        review_needed = sum(1 for e in events if e.status == "review_needed")

        by_severity: dict[str, int] = {}
        by_label: dict[str, int] = {}
        for e in events:
            by_severity[e.severity] = by_severity.get(e.severity, 0) + 1
            by_label[e.label] = by_label.get(e.label, 0) + 1

        # Build DigestEntry list, sort most-severe-first, cap.
        entries = [
            DigestEntry(
                flag_id=e.flag_id,
                app_package=e.app_package,
                direction=e.direction,
                label=e.label,
                severity=e.severity,
                quote=e.quote,
                status=e.status,
                created_at=e.created_at,
            )
            for e in events
        ]
        entries.sort(key=_severity_key)
        entries = entries[: self._max_entries]

        date_str = _epoch_to_date(day_start)

        return ChildDigest(
            child_id=child_id,
            parent_id=parent_id,
            date=date_str,
            generated_at=day_end,  # use day_end as "generated_at" (injected)
            total_flagged=total,
            review_needed=review_needed,
            by_severity=by_severity,
            by_label=by_label,
            entries=entries,
        )

    async def run_once(self, *, now: float) -> list[ChildDigest]:
        """Build + deliver one digest per child with flagged activity today.

        ``now`` is epoch seconds (injected — never reads wall-clock).
        Computes day_start (midnight of the local date for ``now``) and
        day_end=now.  Returns all digests built (one per active child).
        """
        day_start = _midnight_before(now)
        day_end = now

        # Discover all children with events in the window.
        child_ids = await self._active_child_ids(day_start)

        digests: list[ChildDigest] = []
        for child_id in child_ids:
            parent_id = await self._parent_for_child(child_id)
            if parent_id is None:
                log.warning(
                    "digest.run_once.no_parent",
                    child_id=child_id,
                )
                continue
            try:
                digest = await self.build_digest(
                    child_id,
                    parent_id,
                    day_start=day_start,
                    day_end=day_end,
                )
            except Exception as exc:  # noqa: BLE001 — best-effort per child
                log.error(
                    "digest.run_once.build_failed",
                    child_id=child_id,
                    error=str(exc),
                )
                continue

            # Skip children with no events in the window (shouldn't happen
            # given the active_child_ids filter, but be defensive).
            if digest.total_flagged == 0:
                continue

            await self.deliver(digest)
            digests.append(digest)

        log.info(
            "digest.run_once.complete",
            now=now,
            day_start=day_start,
            children_processed=len(digests),
        )
        return digests

    async def deliver(self, digest: ChildDigest) -> bool:
        """Resolve parent FCM token → send push → save digest to store.

        Reuses ``NotificationChannel.send_alert`` with a digest-shaped
        ``AlertRequest``:
          - ``message_id`` = ``"digest:{child_id}:{date}"`` (idempotency key)
          - ``label`` = highest-severity label in the digest (or "non_offensive"
            if digest is empty, which shouldn't normally happen)
          - ``severity`` = max severity in the digest
          - ``explanation`` = Hebrew one-liner summary
          - ``quote`` = "" (digest push has no single quote)
          - ``source`` = "frontline_direct" (closest semantically; digest is an
            aggregation of frontline classifications)

        Always saves the digest to the store regardless of delivery success.
        Returns True if the push was sent (channel returned sent=True).
        """
        # Resolve FCM token.
        fcm_token = await self._fcm_token_for_parent(digest.parent_id)

        # Build the AlertRequest.
        label, severity = _max_severity_label(digest)
        explanation = _build_summary_hebrew(digest)
        message_id = f"digest:{digest.child_id}:{digest.date}"

        alert_req = AlertRequest(
            child_id=digest.child_id,
            message_id=message_id,
            label=label,
            severity=severity,
            explanation=explanation[:280],
            quote="",
            source="frontline_direct",
            trace_id=message_id,
            parent_fcm_token=fcm_token or "",
        )

        sent = False
        try:
            result = await self._channel.send_alert(alert_req)
            sent = result.sent
            log.info(
                "digest.delivered",
                child_id=digest.child_id,
                date=digest.date,
                sent=result.sent,
                channel=result.channel,
                total_flagged=digest.total_flagged,
            )
        except Exception as exc:  # noqa: BLE001 — best-effort delivery
            log.error(
                "digest.deliver_failed",
                child_id=digest.child_id,
                date=digest.date,
                error=str(exc),
            )

        # Always save the digest even if delivery failed (it's still available
        # for GET /v1/parent/digests/{date}).
        try:
            await self._digest_store.save(digest)
        except Exception as exc:  # noqa: BLE001 — best-effort persistence
            log.error(
                "digest.save_failed",
                child_id=digest.child_id,
                date=digest.date,
                error=str(exc),
            )

        return sent

    async def health(self) -> tuple[HealthState, str]:
        return (HealthState.OK, "ManualDigestRunner: no background task")


# ---------------------------------------------------------------------------
# Helpers — pure, no side-effects
# ---------------------------------------------------------------------------


def _midnight_before(now: float) -> float:
    """Return epoch seconds for midnight (local time) of the day containing now."""
    import time as _time

    lt = _time.localtime(now)
    # mktime of the same day at 00:00:00
    return _time.mktime(
        _time.struct_time(
            (lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, lt.tm_wday, lt.tm_yday, lt.tm_isdst)
        )
    )


def _epoch_to_date(epoch: float) -> str:
    """Return 'YYYY-MM-DD' for the server-local date of ``epoch``."""
    import time as _time

    lt = _time.localtime(epoch)
    return f"{lt.tm_year:04d}-{lt.tm_mon:02d}-{lt.tm_mday:02d}"


def _max_severity_label(digest: ChildDigest) -> tuple[Category, Severity]:
    """Return the (label, severity) of the most severe entry in the digest.

    Falls back to ("non_offensive", "low") for empty digests.
    """
    if not digest.entries:
        return ("non_offensive", "low")  # type: ignore[return-value]
    best = min(digest.entries, key=_severity_key)
    return best.label, best.severity


def _build_summary_hebrew(digest: ChildDigest) -> str:
    """Build a Hebrew one-liner summary string for the FCM notification body."""
    total = digest.total_flagged
    review = digest.review_needed
    if review > 0:
        return f"{total} התראות חדשות, {review} ממתינות לבדיקה"
    return f"{total} התראות חדשות היום"
