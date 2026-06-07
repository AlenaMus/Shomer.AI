"""Shared fixtures for the Alerts test suite.

Fixtures
--------
alert_request
    A minimal valid ``AlertRequest`` with all required fields populated.

alert_settings
    Default ``AlertSettings`` (no env override — uses model defaults).

noop_rate_limiter
    A ``NoOpAlertRateLimiter`` (always allows).

in_memory_rate_limiter
    An ``InMemoryAlertRateLimiter`` with tight defaults (max=3, window=60s).

retry_queue
    A fresh ``LocalRetryQueue`` (max_size=10 for tests).

log_notifier
    A ``LogNotifier`` wired with ``noop_rate_limiter`` and no audit_recorder.

stub_notifier
    A ``StubNotifier`` (happy-path, no forced failure).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure ``server/`` is on sys.path so tests can do ``from app.alerts import ...``.
_SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(_SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVER_ROOT))

from app.alerts import (
    AlertSettings,
    InMemoryAlertRateLimiter,
    LocalRetryQueue,
    LogNotifier,
    NoOpAlertRateLimiter,
    StubNotifier,
)
from app.schemas import AlertRequest


@pytest.fixture
def alert_settings() -> AlertSettings:
    """Default AlertSettings (model-level defaults, no env override)."""
    return AlertSettings(
        channel="log",
        rate_limit_max_alerts=3,
        rate_limit_window_seconds=60,
        max_retry_attempts=3,
        retry_base_seconds=1.0,
        queue_max_size=10,
    )


@pytest.fixture
def alert_request() -> AlertRequest:
    """A minimal valid AlertRequest for testing."""
    return AlertRequest(
        child_id="child-test-001",
        message_id="msg-test-abc",
        label="violence",
        severity="high",
        explanation="The message contains violent content.",
        quote="...",
        source="frontline_direct",
        trace_id="trace-test-xyz",
        parent_fcm_token="",
        child_name="Test Child",
    )


@pytest.fixture
def noop_rate_limiter() -> NoOpAlertRateLimiter:
    return NoOpAlertRateLimiter()


@pytest.fixture
def in_memory_rate_limiter() -> InMemoryAlertRateLimiter:
    return InMemoryAlertRateLimiter(max_alerts=3, window_seconds=60)


@pytest.fixture
def retry_queue() -> LocalRetryQueue:
    return LocalRetryQueue(max_size=10)


@pytest.fixture
def log_notifier(
    alert_settings: AlertSettings,
    noop_rate_limiter: NoOpAlertRateLimiter,
) -> LogNotifier:
    return LogNotifier(
        settings=alert_settings,
        rate_limiter=noop_rate_limiter,
    )


@pytest.fixture
def stub_notifier() -> StubNotifier:
    return StubNotifier()
