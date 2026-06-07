"""Prometheus metrics for the Triage module.

Reference: docs/design/triage/design.md §6 (Observability).

All metrics are registered against the default Prometheus REGISTRY so the
server's ``/metrics`` endpoint scrapes them automatically. They are defined
at module import time — importing this module is the registration call.
"""

from __future__ import annotations

from prometheus_client import Counter, Histogram

# ---------------------------------------------------------------------------
# 1. Decision volume — labelled by the four possible outcomes.
# ---------------------------------------------------------------------------
triage_decisions_total = Counter(
    "triage_decisions_total",
    "Triage decisions by outcome.",
    labelnames=("decision",),
)

# ---------------------------------------------------------------------------
# 2. Confidence distribution — P(offensive) score at the triage gate.
#    Buckets at every tenth so the borderline zone [0.3, 0.7] is visible.
# ---------------------------------------------------------------------------
triage_input_confidence = Histogram(
    "triage_input_confidence",
    "Distribution of P(offensive) scores entering the triage gate.",
    buckets=(0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0),
)

# ---------------------------------------------------------------------------
# 3. Label override volume — how often static label rules fire.
# ---------------------------------------------------------------------------
triage_label_overrides_total = Counter(
    "triage_label_overrides_total",
    "Label-override decisions at triage, by label and override type.",
    labelnames=("label", "override_type"),
)
