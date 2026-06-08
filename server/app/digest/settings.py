"""DigestSettings — pydantic-settings for the Digest module.

All env vars are prefixed ``DIGEST_``.  Defaults are chosen so the module
works out of the box in development (manual runner, digest at 08:00 local).

Reference: linked-yawning-sifakis.md §S3 "Daily digest + push".
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class DigestSettings(BaseSettings):
    """Environment-driven configuration for the Digest module."""

    model_config = SettingsConfigDict(
        env_prefix="DIGEST_",
        case_sensitive=False,
        extra="ignore",
    )

    # "asyncio" (production in-process cron) | "manual" (tests + external cron)
    backend: str = "manual"

    # Hour of day (server-local time, 0–23) when the daily digest fires.
    hour: int = 8

    # Digest module enabled flag.
    enabled: bool = True

    # When True (default), a critical/high severity alerted event triggers an
    # immediate single-event push bypassing the daily digest cadence.
    critical_immediate: bool = True

    # Maximum number of DigestEntry items in a single ChildDigest.
    max_entries: int = 50

    # SQLite path for the digest store (used by SqliteDigestStore).
    db_path: str = "server/data/digest.db"

    # SQLite busy timeout (ms).
    busy_timeout_ms: int = 5000

    # Allow POST /internal/digest/run to trigger a manual run in prod.
    # Default True for MVP demo; set False to lock down in production.
    allow_manual_trigger: bool = True
