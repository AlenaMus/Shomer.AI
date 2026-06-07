"""RetentionSweeper — background retention loop for the Audit Log module.

Reference: docs/design/audit_log/design.md §3 (RetentionSweeper), §4.2.

This helper periodically calls ``AuditStore.cleanup_expired(retention_days)`` to
delete rows older than the retention window (PRD §9 privacy NFR, default 7 days).

The composition root (server/app/main.py ``lifespan()``) owns the task lifecycle::

    sweeper = RetentionSweeper(store, retention_days=settings.retention_days)
    task = asyncio.create_task(sweeper.run())     # launched by the composition root
    ...
    sweeper.stop()                                 # request graceful stop
    await task                                     # await on shutdown

This module NEVER launches the loop itself and starts no task at import time.
A sweep error is logged and swallowed so the loop keeps running — the next
interval retries.
"""

from __future__ import annotations

import asyncio

import structlog

from .protocol import AuditStore

logger = structlog.get_logger("shomer.audit")


class RetentionSweeper:
    """Async loop that prunes expired audit rows on a fixed interval."""

    def __init__(
        self,
        store: AuditStore,
        *,
        retention_days: int = 7,
        interval_s: float = 3600.0,
    ) -> None:
        self._store = store
        self._retention_days = retention_days
        self._interval_s = interval_s
        self._stop_event = asyncio.Event()

    def stop(self) -> None:
        """Request the loop to exit before the next interval elapses."""
        self._stop_event.set()

    async def run(self) -> None:
        """Run the sweep loop until :meth:`stop` is called.

        Sweeps once immediately on start, then every ``interval_s`` seconds.
        Any exception inside a sweep is logged and absorbed so the loop survives.
        """
        logger.info(
            "retention_sweeper_started",
            retention_days=self._retention_days,
            interval_s=self._interval_s,
        )
        while not self._stop_event.is_set():
            await self.sweep_once()
            try:
                # Wake early if stop() is called; otherwise sleep the interval.
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=self._interval_s
                )
            except asyncio.TimeoutError:
                pass  # interval elapsed → next sweep
        logger.info("retention_sweeper_stopped")

    async def sweep_once(self) -> int:
        """Run a single sweep; return rows deleted (0 on error). Never raises."""
        try:
            deleted = await self._store.cleanup_expired(self._retention_days)
            return deleted
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("retention_sweep_failed", error=str(exc))
            return 0
