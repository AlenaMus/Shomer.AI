"""Configuration for the Identity module.

All env vars are prefixed with ``IDENTITY_`` so they are namespaced and
obvious in ``server/.env``.

Example overrides in tests::

    from app.identity.settings import IdentitySettings
    settings = IdentitySettings(backend="memory", db_path=":memory:")
"""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class IdentitySettings(BaseSettings):
    """Settings for the identity module (env prefix ``IDENTITY_``)."""

    model_config = SettingsConfigDict(
        env_prefix="IDENTITY_",
        extra="ignore",
        case_sensitive=False,
    )

    backend: str = Field(
        default="sqlite",
        description=(
            "Adapter to use: 'sqlite' (default, persistent) or 'memory' (tests)."
        ),
    )
    db_path: str = Field(
        default="server/data/identity.db",
        description="Filesystem path to the SQLite identity DB.",
    )
    device_token_ttl_days: int = Field(
        default=365,
        description="How many days a device token is valid (0 = no expiry).",
    )
    pairing_code_ttl_s: int = Field(
        default=600,
        description="Pairing OTP lifetime in seconds (default 10 min).",
    )
    busy_timeout_ms: int = Field(
        default=5000,
        description="SQLite busy_timeout for write contention.",
    )
