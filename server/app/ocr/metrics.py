"""Prometheus metrics for the OCR module.

All metrics use the default registry so they are automatically included in
the ``/metrics`` endpoint exposed by ``prometheus-fastapi-instrumentator``.

Reference: docs/design/ocr/design.md §6.3
"""

from __future__ import annotations

from prometheus_client import Counter, Histogram

# ---------------------------------------------------------------------------
# Latency buckets spanning 0.05 s (fast) to 5.0 s (very slow).
# The p99 SLA is 2 s (PRD §8.2) so the 2.0 s bucket is intentionally present.
# ---------------------------------------------------------------------------
_LATENCY_BUCKETS = (
    0.05, 0.1, 0.2, 0.3, 0.5, 0.75,
    1.0, 1.5, 2.0, 3.0, 5.0,
)

_CONFIDENCE_BUCKETS = (
    0.0, 0.1, 0.2, 0.3, 0.4, 0.5,
    0.6, 0.7, 0.8, 0.9, 1.0,
)

_CHARS_BUCKETS = (
    0, 10, 25, 50, 100, 200, 500, 1000, 2000,
)

_BBOX_BUCKETS = (0, 1, 5, 10, 20, 50, 100, 200)

# ---------------------------------------------------------------------------
# Metric definitions
# ---------------------------------------------------------------------------

ocr_requests_total = Counter(
    "ocr_requests_total",
    "Total OCR process() invocations, labelled by backend and outcome.",
    labelnames=["backend", "outcome"],
    # outcome values: "success" | "no_text" | "error"
)

ocr_latency_seconds = Histogram(
    "ocr_latency_seconds",
    "Wall-clock latency of OcrBackend.process() from bytes-in to OcrResult-out.",
    labelnames=["backend"],
    buckets=_LATENCY_BUCKETS,
)

ocr_confidence = Histogram(
    "ocr_confidence",
    "Distribution of mean per-word OCR confidence scores (0–1).",
    labelnames=["backend"],
    buckets=_CONFIDENCE_BUCKETS,
)

ocr_extracted_chars = Histogram(
    "ocr_extracted_chars",
    "Number of characters in extracted_text (proxy for input size to classifier).",
    labelnames=["backend"],
    buckets=_CHARS_BUCKETS,
)

ocr_image_unreadable_total = Counter(
    "ocr_image_unreadable_total",
    "Number of OcrResult objects returned with image_unreadable=True.",
    labelnames=["backend"],
)

ocr_errors_total = Counter(
    "ocr_errors_total",
    "Unexpected errors during OCR (caught; process() still returns a result).",
    labelnames=["backend", "error_type"],
)

__all__ = [
    "ocr_requests_total",
    "ocr_latency_seconds",
    "ocr_confidence",
    "ocr_extracted_chars",
    "ocr_image_unreadable_total",
    "ocr_errors_total",
]
