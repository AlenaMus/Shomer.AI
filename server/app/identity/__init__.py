"""Identity module — child/parent identity, pairing, and device-token auth.

Public surface:

  * Port + value types (import everywhere except the composition root)::

        from server.app.identity import IdentityStore, ChildRecord, PairingCode, DeviceContext

  * Concrete adapters + settings (import ONLY in server/app/main.py lifespan())::

        from server.app.identity import (
            SqliteIdentityStore, InMemoryIdentityStore, IdentitySettings,
        )

Reference: linked-yawning-sifakis.md §S2 "Identity & Auth".
"""

from __future__ import annotations

from .protocol import ChildRecord, DeviceContext, IdentityStore, PairingCode, ParentAuth
from .in_memory_adapter import InMemoryIdentityStore
from .router import register_identity
from .settings import IdentitySettings
from .sqlite_adapter import SqliteIdentityStore

__all__ = [
    # Port + value types
    "IdentityStore",
    "ChildRecord",
    "PairingCode",
    "DeviceContext",
    "ParentAuth",
    # Concrete adapters + settings (composition root only)
    "SqliteIdentityStore",
    "InMemoryIdentityStore",
    "IdentitySettings",
    # Router registration helper
    "register_identity",
]
