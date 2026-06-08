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
    """Which channel adapter to wire: ``"log"`` | ``"ntfy"`` | ``"fcm"`` | ``"stub"``."""

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

    # --- NtfyNotifier (free push via ntfy.sh — no account, no Firebase) -------
    # ntfy publishes a notification to a topic; the parent installs the free
    # ntfy app and subscribes to the topic to receive proactive pushes.
    ntfy_server: str = "https://ntfy.sh"
    """Base URL of the ntfy server (public ntfy.sh or a self-hosted instance)."""

    ntfy_topic: str = ""
    """ntfy topic to publish to. Empty → NtfyNotifier reports 'not configured'."""

    ntfy_token: str = ""
    """Optional Bearer token for protected/self-hosted topics (access control)."""

    ntfy_click_url: str = ""
    """Optional URL opened when the push is tapped (e.g. the parent dashboard)."""

    ntfy_timeout_s: float = 10.0
    """Per-request HTTP timeout for publishing to ntfy."""

    # --- FcmNotifier (M6-ALERTS-FCM) ------------------------------------------
    # NOTE: FCM_SERVICE_ACCOUNT_PATH does NOT share the ALERTS_ prefix because
    # it is a Firebase-level credential, not an alerts-behaviour setting.
    # pydantic-settings ignores env vars with non-matching prefixes by default.
    # FcmNotifier reads FCM_SERVICE_ACCOUNT_PATH via a separate bare read.
    fcm_channel_id: str = "shomer_alerts"
    """Android notification channel ID — shown in system settings."""
