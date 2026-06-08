"""Configuration for the Dedup module (env prefix ``DEDUP_``).

Use ``DedupSettings()`` to load from environment.  Tests can override via
keyword arguments, e.g. ``DedupSettings(dedup_ttl_s=60)``.
"""

from __future__ import annotations

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class DedupSettings(BaseSettings):
    """Settings for the dedup module (env prefix ``DEDUP_``)."""

    model_config = SettingsConfigDict(
        env_prefix="DEDUP_",
        extra="ignore",
        case_sensitive=False,
    )

    backend: str = Field(
        default="memory",
        description=(
            "Dedup adapter to use. "
            "'memory' → InMemoryTtlDedupStore (default, single-process). "
            "'null'   → NullDedupStore (load tests / diagnostics). "
            "'redis'  → RedisDedupStore (S6, multi-process scale-up, not in S1)."
        ),
    )
    ttl_s: int = Field(
        default=3600,
        description="How long a (child_id, text_hash) pair is suppressed (seconds).",
    )
    max_per_child: int = Field(
        default=5000,
        description=(
            "Maximum number of hash entries kept per child_id in the in-memory "
            "adapter before eviction of the oldest entry."
        ),
    )

    @field_validator("ttl_s", "max_per_child")
    @classmethod
    def _positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError(f"value must be positive, got {v}")
        return v
