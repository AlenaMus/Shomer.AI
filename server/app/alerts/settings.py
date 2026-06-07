"""Configuration for the Alerts module.

Reference: docs/design/alerts/design.md §6 (Config table).

All settings have an ``ALERTS_`` env-prefix EXCEPT ``FCM_SERVICE_ACCOUNT_PATH``
which uses the ``FCM_`` prefix because it is a Firebase credential, not an
alerts-behaviour knob.  This matches the LLD §6 config table.

Usage in tests:
    AlertSettings(rate_limit_max_alerts=1, rate_limit_window_seconds=60)
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class AlertSettings(BaseSettings):
    """Settings consumed by LogNotifier, FcmNotifier, and rate limiters.

    Pydantic-settings reads these from environment variables (``ALERTS_``
    prefix) or from a ``.env`` file in the working directory.
    """

    model_config = SettingsConfigDict(
        env_prefix="ALERTS_",
        env_file=".env",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    # --- Channel selection (string, not enum — keeps settings import cheap) ---
    channel: str = "log"
    """Which channel adapter to wire: ``"log"`` | ``"fcm"`` | ``"stub"``."""

    # --- Rate limiter ---
    rate_limit_max_alerts: int = 3
    """Maximum alerts allowed within the sliding window, per key (child_id)."""

    rate_limit_window_seconds: int = 60
    """Sliding window duration in seconds for the per-key rate limiter."""

    # --- Retry ---
    max_retry_attempts: int = 3
    """Number of send attempts before declaring failure and queuing."""

    retry_base_seconds: float = 1.0
    """Exponential-backoff base: delays are 1 s, 2 s, 4 s, … (base * 2^n)."""

    # --- Local retry queue ---
    queue_max_size: int = 100
    """Capacity of the in-process LocalRetryQueue (oldest dropped when full)."""

    # --- FcmNotifier (backlog M6-ALERTS-FCM) ----------------------------------
    # NOTE: FCM_SERVICE_ACCOUNT_PATH does NOT share the ALERTS_ prefix because
    # it is a Firebase-level credential, not an alerts-behaviour setting.
    # pydantic-settings ignores env vars with non-matching prefixes by default.
    # FcmNotifier reads FCM_SERVICE_ACCOUNT_PATH via a separate bare read.
    fcm_channel_id: str = "shomer_alerts"
    """Android notification channel ID — shown in system settings."""
