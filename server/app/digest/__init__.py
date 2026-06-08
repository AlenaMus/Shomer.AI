"""Digest module — daily digest aggregation and FCM push (S3).

Public surface:

  * Port + value types (import everywhere except the composition root)::

        from server.app.digest import DigestScheduler, DigestStore, ChildDigest, DigestEntry

  * Concrete adapters + settings (import ONLY in server/app/main.py lifespan())::

        from server.app.digest import (
            ManualDigestRunner,
            AsyncioCronDigestScheduler,
            InMemoryDigestStore,
            SqliteDigestStore,
            DigestSettings,
        )

  * Router registration helper::

        from server.app.digest import register_digest

Reference: linked-yawning-sifakis.md §S3 "Daily digest + push".
"""

from __future__ import annotations

from .protocol import ChildDigest, DigestEntry, DigestScheduler, DigestStore
from .in_memory_store import InMemoryDigestStore
from .sqlite_store import SqliteDigestStore
from .manual_runner import ManualDigestRunner
from .asyncio_cron_scheduler import AsyncioCronDigestScheduler
from .settings import DigestSettings
from .router import register_digest

__all__ = [
    # Port + value types
    "DigestScheduler",
    "DigestStore",
    "ChildDigest",
    "DigestEntry",
    # Concrete adapters + settings (composition root only)
    "ManualDigestRunner",
    "AsyncioCronDigestScheduler",
    "InMemoryDigestStore",
    "SqliteDigestStore",
    "DigestSettings",
    # Router registration helper
    "register_digest",
]
