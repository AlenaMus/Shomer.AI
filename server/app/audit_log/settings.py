"""Configuration for the Audit Log module.

Reference: docs/design/audit_log/design.md §6.2, §9.

Unlike the other module settings (which read flat env vars with no prefix),
the audit module uses an ``AUDIT_`` env prefix so every audit knob is namespaced
and obvious in ``server/.env`` (e.g. ``AUDIT_DB_PATH``, ``AUDIT_RETENTION_DAYS``).

Use ``AuditSettings()`` to load from env; tests can pass overrides via keyword
arguments (e.g. ``AuditSettings(db_path="/tmp/test.db")``).
"""

from __future__ import annotations

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AuditSettings(BaseSettings):
    """Settings for the audit_log module (env prefix ``AUDIT_``)."""

    model_config = SettingsConfigDict(
        env_prefix="AUDIT_",
        extra="ignore",
        case_sensitive=False,
    )

    db_path: str = Field(
        default="server/data/audit.db",
        description="Filesystem path to the SQLite audit DB. WAL needs a real file.",
    )
    retention_days: int = Field(
        default=7,
        description="Rows older than this many days are deleted by the sweeper.",
    )
    conversation_window: int = Field(
        default=5,
        description="Default number of recent conversation turns read_history returns.",
    )
    busy_timeout_ms: int = Field(
        default=5000,
        description="SQLite busy_timeout — how long a write waits on a locked DB.",
    )

    @field_validator("retention_days", "conversation_window")
    @classmethod
    def _positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError(f"value must be positive, got {v}")
        return v
