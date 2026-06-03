"""Prometheus metrics for the Frontline Classifier module.

Reference: docs/design/classifier/design.md §6.3.

All metrics are registered against the default Prometheus REGISTRY so the
server's ``/metrics`` endpoint scrapes them automatically. They are defined
at module import time — importing this module is the registration call.

Latency-histogram buckets are placed below the PRD §8.1 budget of 100 ms so
the p99 cell on the dashboard reads "did we beat 0.1 s?" at a glance.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

# -----------------------------------------------------------------------------
# 1. Volume — every classification, broken down by label, model, and outcome.
# -----------------------------------------------------------------------------
CLASSIFIER_REQUESTS = Counter(
    "classifier_requests_total",
    "Total classifications performed, by label / model_version / outcome.",
    labelnames=("label", "model_version", "outcome"),
)

# -----------------------------------------------------------------------------
# 2. Latency — wall-clock for one classify() call. Sub-100ms buckets per LLD.
# -----------------------------------------------------------------------------
CLASSIFIER_LATENCY = Histogram(
    "classifier_latency_seconds",
    "Wall-clock latency of TextClassifier.classify().",
    labelnames=("model_version",),
    buckets=(0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

# -----------------------------------------------------------------------------
# 3. Confidence distribution — split by raw vs calibrated to spot drift.
# -----------------------------------------------------------------------------
CLASSIFIER_CONFIDENCE = Histogram(
    "classifier_confidence_score",
    "Distribution of confidence scores produced by the classifier.",
    labelnames=("label", "calibrated"),
    buckets=(0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0),
)

# -----------------------------------------------------------------------------
# 4. Borderline count — feeds the cost dashboard for Context Agent calls.
# -----------------------------------------------------------------------------
CLASSIFIER_BORDERLINE = Counter(
    "classifier_borderline_total",
    "Classifications that landed in the borderline zone (escalated to CA).",
    labelnames=("label",),
)

# -----------------------------------------------------------------------------
# 5. Errors — every fallback path increments this with a typed error_type.
# -----------------------------------------------------------------------------
CLASSIFIER_ERRORS = Counter(
    "classifier_error_total",
    "Classifier failures by error type (e.g. ollama_unreachable, malformed_json).",
    labelnames=("error_type",),
)

# -----------------------------------------------------------------------------
# 6. Calibration switch — gauge reads 1.0 when the chosen method is active.
# -----------------------------------------------------------------------------
CLASSIFIER_CALIBRATION_ENABLED = Gauge(
    "classifier_calibration_enabled",
    "1 when the matching calibration method is the active one, else 0.",
    labelnames=("method",),
)


def record_classification(
    *,
    label: str,
    model_version: str,
    confidence: float,
    raw_confidence: float,
    latency_s: float,
    is_borderline: bool,
    error: bool,
    calibrated: bool,
) -> None:
    """One-shot helper invoked by every adapter at the end of ``classify()``.

    Centralises label-cardinality decisions and keeps adapter code focused on
    the inference path.
    """
    outcome = "error" if error else "ok"
    CLASSIFIER_REQUESTS.labels(
        label=label, model_version=model_version, outcome=outcome
    ).inc()
    CLASSIFIER_LATENCY.labels(model_version=model_version).observe(latency_s)
    CLASSIFIER_CONFIDENCE.labels(
        label=label, calibrated=str(calibrated).lower()
    ).observe(confidence)
    CLASSIFIER_CONFIDENCE.labels(
        label=label, calibrated="false"
    ).observe(raw_confidence)
    if is_borderline:
        CLASSIFIER_BORDERLINE.labels(label=label).inc()


def record_error(error_type: str) -> None:
    """Record a typed classifier failure (e.g. ``"ollama_unreachable"``)."""
    CLASSIFIER_ERRORS.labels(error_type=error_type).inc()


def set_calibration_method(active_method: str) -> None:
    """Set the calibration gauge so dashboards reflect the running config.

    Sets the gauge to 1.0 for the matching method label and 0.0 for the
    others. Call this once at server startup after the calibrator is built.
    """
    for method in ("none", "temperature", "isotonic"):
        CLASSIFIER_CALIBRATION_ENABLED.labels(method=method).set(
            1.0 if method == active_method else 0.0
        )
