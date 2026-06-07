"""Alerts module — push-notification delivery for Shomer.AI.

Public surface (port-only per docs/design/README.md):

    from server.app.alerts import NotificationChannel   # Protocol
    from server.app.alerts import AlertRateLimiter       # Protocol

Concrete adapters and helpers are re-exported here so the composition root
(``server/app/main.py`` lifespan()) can do a single import:

    from server.app.alerts import LogNotifier, InMemoryAlertRateLimiter, ...

See docs/design/alerts/design.md for the full LLD.

Sprint decision D1 (decisions/meeting-6-server-flow.decision.md):
    Default channel = LogNotifier.  FcmNotifier is a deferred backlog task
    (M6-ALERTS-FCM) — importable but returns a "not enabled" result until
    firebase-admin is installed and credentials are configured.
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
from .fcm_notifier import FcmNotifier

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
    "FcmNotifier",
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
