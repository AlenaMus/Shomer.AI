"""Prometheus metrics for the Alerts module.

Reference: docs/design/alerts/design.md §6 (Metrics table).

Metrics are defined at module import time (registration side-effect).
All are registered against the default Prometheus REGISTRY so the server's
``/metrics`` endpoint scrapes them automatically.

NFR coverage:
- ``alert_send_latency_seconds`` → PRD §9 p99 < 2 s notification delivery.
- ``alert_rate_limited_total``   → PRD KPI: Alert Fatigue churn < 3/day.
- ``alert_queue_depth``          → degraded-mode monitoring.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

# ---------------------------------------------------------------------------
# 1. End-to-end send latency — the primary SLO metric.
#    Buckets placed at sub-2s points to make p99 readable at a glance.
# ---------------------------------------------------------------------------
ALERT_SEND_LATENCY = Histogram(
    "alert_send_latency_seconds",
    "Wall-clock latency of NotificationChannel.send_alert(), in seconds.",
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0),
)

# ---------------------------------------------------------------------------
# 2. Success counter — throughput baseline.
# ---------------------------------------------------------------------------
ALERT_SEND_SUCCESS = Counter(
    "alert_send_success_total",
    "Successful alert deliveries (sent=True).",
)

# ---------------------------------------------------------------------------
# 3. Failure counter — labelled by failure reason (exception class name or
#    synthetic reason string like "rate_limited").
# ---------------------------------------------------------------------------
ALERT_SEND_FAILURES = Counter(
    "alert_send_failures_total",
    "Alert delivery failures, by reason.",
    labelnames=("reason",),
)

# ---------------------------------------------------------------------------
# 4. Rate-limited suppression counter — feeds the Alert Fatigue KPI.
# ---------------------------------------------------------------------------
ALERT_RATE_LIMITED = Counter(
    "alert_rate_limited_total",
    "Alerts suppressed by the per-child rate limiter.",
)

# ---------------------------------------------------------------------------
# 5. Retry-queue depth — Gauge reflects current backlog; drops to 0 on drain.
# ---------------------------------------------------------------------------
ALERT_QUEUE_DEPTH = Gauge(
    "alert_queue_depth",
    "Number of failed alerts currently waiting in the LocalRetryQueue.",
)
