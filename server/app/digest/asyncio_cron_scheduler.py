"""AsyncioCronDigestScheduler — production DigestScheduler adapter.

Owns an asyncio background task that sleeps until the configured daily hour,
calls ``run_once(now=time.time())``, then sleeps ~24h.  Pattern copied exactly
from ``audit_log/retention.py`` (RetentionSweeper):

    scheduler = AsyncioCronDigestScheduler(...)
    task = asyncio.create_task(scheduler.run())   # composition root
    ...
    scheduler.stop()                              # request graceful stop
    await task                                    # await on shutdown

The background task reads the real wall-clock (``time.time()``) and sleeps
(``asyncio.sleep``).  Everything else delegates to the wrapped
``ManualDigestRunner`` which is fully deterministic.

Design constraint: the AsyncioCron scheduler is the ONLY place in the digest
module where real time/sleep lives.  ``ManualDigestRunner.run_once`` takes
``now`` as a parameter and never reads the clock.

Reference: linked-yawning-sifakis.md §S3.
"""

from __future__ import annotations

import asyncio
import time

import structlog

from ..schemas import HealthState
from .manual_runner import ManualDigestRunner
from .protocol import ChildDigest

log = structlog.get_logger("shomer.digest.cron")


class AsyncioCronDigestScheduler:
    """Background asyncio cron task that fires the daily digest.

    Parameters
    ----------
    runner:
        A ``ManualDigestRunner`` instance that owns the aggregation/delivery
        logic.  The cron scheduler wraps it and adds the sleep loop.
    hour:
        Hour of day (0–23, server local time) when the digest fires.
        Default 8 (08:00 local).
    """

    def __init__(
        self,
        runner: ManualDigestRunner,
        hour: int = 8,
    ) -> None:
        self._runner = runner
        self._hour = hour
        self._stop_event = asyncio.Event()
        self._last_run_at: float | None = None

    def stop(self) -> None:
        """Request the loop to exit before the next sleep elapses."""
        self._stop_event.set()

    async def run(self) -> None:
        """Run the digest cron loop until :meth:`stop` is called.

        On startup: sleeps until the next configured hour.  Each fire calls
        ``run_once(now=time.time())`` then sleeps until the same hour the
        next day (approximately 24h).  Any exception inside a tick is logged
        and absorbed so the loop survives.
        """
        log.info(
            "digest_cron_started",
            hour=self._hour,
        )
        while not self._stop_event.is_set():
            delay = self._seconds_until_next_fire()
            log.debug("digest_cron.next_fire_in_s", seconds=delay)
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=delay
                )
                # stop_event fired — exit loop.
                break
            except asyncio.TimeoutError:
                pass  # scheduled time elapsed → fire now

            if self._stop_event.is_set():
                break

            await self._tick()

        log.info("digest_cron_stopped")

    async def _tick(self) -> None:
        """Execute one digest cycle. Errors logged + absorbed."""
        now = time.time()
        try:
            digests = await self._runner.run_once(now=now)
            self._last_run_at = now
            log.info(
                "digest_cron.tick_complete",
                digests_built=len(digests),
                now=now,
            )
        except Exception as exc:  # noqa: BLE001 — keep loop alive
            log.error("digest_cron.tick_failed", error=str(exc))

    def _seconds_until_next_fire(self) -> float:
        """Return seconds until the next configured hour (always > 0)."""
        import time as _time

        now = _time.time()
        lt = _time.localtime(now)
        # Compute the next fire time today.
        fire_today = _time.mktime(
            _time.struct_time(
                (lt.tm_year, lt.tm_mon, lt.tm_mday, self._hour, 0, 0,
                 lt.tm_wday, lt.tm_yday, lt.tm_isdst)
            )
        )
        if fire_today > now:
            return fire_today - now
        # Already past today's hour → schedule for tomorrow.
        return fire_today + 86400 - now

    # ------------------------------------------------------------------
    # DigestScheduler Protocol (delegates to ManualDigestRunner)
    # ------------------------------------------------------------------

    async def build_digest(
        self,
        child_id: str,
        parent_id: str,
        *,
        day_start: float,
        day_end: float,
    ) -> ChildDigest:
        """Delegate to ManualDigestRunner.build_digest."""
        return await self._runner.build_digest(
            child_id, parent_id, day_start=day_start, day_end=day_end
        )

    async def run_once(self, *, now: float) -> list[ChildDigest]:
        """Delegate to ManualDigestRunner.run_once (injects now)."""
        digests = await self._runner.run_once(now=now)
        self._last_run_at = now
        return digests

    async def deliver(self, digest: ChildDigest) -> bool:
        """Delegate to ManualDigestRunner.deliver."""
        return await self._runner.deliver(digest)

    async def health(self) -> tuple[HealthState, str]:
        last = f"{self._last_run_at:.0f}" if self._last_run_at else "never"
        return (
            HealthState.OK,
            f"AsyncioCronDigestScheduler: hour={self._hour}, last_run={last}",
        )
