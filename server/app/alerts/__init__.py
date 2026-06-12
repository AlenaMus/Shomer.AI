"""Alerts module — push-notification delivery for Shomer.AI.

Public surface (port-only per docs/design/README.md):

    from server.app.alerts import NotificationChannel   # Protocol
    from server.app.alerts import AlertRateLimiter       # Protocol

Concrete adapters and helpers are re-exported here so the composition root
(``server/app/main.py`` lifespan()) can do a single import:

    from server.app.alerts import LogNotifier, InMemoryAlertRateLimiter, ...

See docs/design/alerts/design.md for the full LLD.

Channel selection (``ALERTS_CHANNEL``, wired in ``main.py`` lifespan()):
    "log" (default, no setup) | "ntfy" | "fcm" | "email" | "smtp" | "stub".
    ``FcmNotifier`` lazy-imports firebase-admin and degrades gracefully when
    not installed.  ``GmailApiNotifier`` lazy-imports google-auth / google-api-
    python-client and degrades gracefully when creds are absent.
    ``SmtpEmailNotifier`` uses stdlib smtplib only (no new deps required).
"""

from __future__ import annotations

# --- Protocols (the port — downstream code only imports these) ---------------
from .protocol import AlertRateLimiter, NotificationChannel

# --- Rate-limiter adapters ---------------------------------------------------
from .rate_limiter import (
    InMemoryAlertRateLimiter,
    NoOpAlertRateLimiter,
    StubAlertRateLimiter,
)

# --- Notification-channel adapters -------------------------------------------
from .log_notifier import LogNotifier, compute_alert_id
from .stub_notifier import StubNotifier
from .ntfy_notifier import NtfyNotifier
from .fcm_notifier import FcmNotifier
from .gmail_notifier import GmailApiNotifier
from .smtp_notifier import SmtpEmailNotifier

# --- Supporting infrastructure -----------------------------------------------
from .retry_queue import LocalRetryQueue
from .settings import AlertSettings
from .severity import derive_severity

__all__ = [
    # Protocols
    "NotificationChannel",
    "AlertRateLimiter",
    # Adapters — NotificationChannel
    "LogNotifier",
    "StubNotifier",
    "NtfyNotifier",
    "FcmNotifier",
    "GmailApiNotifier",
    "SmtpEmailNotifier",
    # Adapters — AlertRateLimiter
    "InMemoryAlertRateLimiter",
    "NoOpAlertRateLimiter",
    "StubAlertRateLimiter",
    # Infrastructure
    "LocalRetryQueue",
    "AlertSettings",
    # Helpers
    "compute_alert_id",
    "derive_severity",
]
