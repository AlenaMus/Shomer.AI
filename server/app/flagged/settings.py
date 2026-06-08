"""Configuration for the Flagged Event module (env prefix ``FLAGGED_``).

Use ``FlaggedSettings()`` to load from environment.  Tests can override via
keyword arguments, e.g. ``FlaggedSettings(backend='memory')``.
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class FlaggedSettings(BaseSettings):
    """Settings for the flagged module (env prefix ``FLAGGED_``)."""

    model_config = SettingsConfigDict(
        env_prefix="FLAGGED_",
        extra="ignore",
        case_sensitive=False,
    )

    backend: str = Field(
        default="sqlite",
        description=(
            "FlaggedEventStore adapter to use. "
            "'sqlite' → SqliteFlaggedEventStore (durable, S4 default). "
            "'memory' → InMemoryFlaggedEventStore (tests, no I/O)."
        ),
    )
    db_path: str = Field(
        default="server/data/flagged.db",
        description=(
            "Filesystem path to the SQLite flagged-events DB. "
            "Mirrors the audit DB path convention (AUDIT_DB_PATH)."
        ),
    )
    busy_timeout_ms: int = Field(
        default=5000,
        description="SQLite busy_timeout — how long a write waits on a locked DB.",
    )
