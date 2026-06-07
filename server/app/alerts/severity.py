"""Deterministic severity derivation for the Alerts module.

Reference: docs/design/alerts/design.md §2 (AlertRequest.severity field).

``derive_severity()`` maps a (label, confidence) pair to one of the four
``Severity`` literals.  It is intentionally deterministic — no randomness,
no LLM call.  The Triage Router or Context Agent already decided that this
message is an actionable threat; derive_severity only grades its urgency.

Severity Mapping Table
----------------------

| label          | confidence ≥ 0.70 | confidence 0.40–0.69 | confidence < 0.40 |
|----------------|-------------------|----------------------|-------------------|
| violence       | critical          | high                 | medium            |
| hate           | high              | medium               | low               |
| pornographic   | high              | medium               | low               |
| abusive        | medium            | medium               | low               |
| non_offensive  | low               | low                  | low               |

Design rationale:
- ``violence`` is the highest-risk label → always elevated by one notch
  vs ``hate`` / ``pornographic`` at equal confidence.
- ``hate`` and ``pornographic`` are equally severe — both expose a child to
  harmful content that warrants parental awareness.
- ``abusive`` is interpersonal conflict that needs attention but rarely
  requires immediate action → capped at ``medium``.
- ``non_offensive`` arriving here means the caller sent a non-threat through
  send_alert() by mistake → return ``low`` as a safe default.
- Confidence thresholds (0.40, 0.70) align with the triage ``BORDERLINE``
  zone (default 0.30–0.70) so a message that barely cleared the alert
  threshold is always graded conservatively.
"""

from __future__ import annotations

from ..schemas import Category, Severity


# Mapping: label → (high_threshold, medium_threshold) where confidence ≥
# high_threshold → top tier; high_threshold > confidence ≥ medium_threshold
# → middle tier; else → bottom tier.
_HIGH_CONFIDENCE = 0.70
_MEDIUM_CONFIDENCE = 0.40

# (top_tier, middle_tier, bottom_tier) for each label.
_LABEL_MAP: dict[str, tuple[Severity, Severity, Severity]] = {
    "violence":      ("critical", "high",   "medium"),
    "hate":          ("high",     "medium",  "low"),
    "pornographic":  ("high",     "medium",  "low"),
    "abusive":       ("medium",   "medium",  "low"),
    "non_offensive": ("low",      "low",     "low"),
}


def derive_severity(label: Category, confidence: float) -> Severity:
    """Return the ``Severity`` for a classified message.

    Parameters
    ----------
    label:
        One of the five SinaLab category labels.
    confidence:
        Calibrated ``P(predicted_class)``, in [0.0, 1.0].  This is the
        confidence from ``ClassificationResult`` — already corrected by the
        calibrator and guaranteed to be in range by the classifier module.

    Returns
    -------
    Severity
        One of ``"low" | "medium" | "high" | "critical"``.
    """
    tiers = _LABEL_MAP.get(label, ("medium", "medium", "low"))
    top, mid, bot = tiers

    if confidence >= _HIGH_CONFIDENCE:
        return top
    if confidence >= _MEDIUM_CONFIDENCE:
        return mid
    return bot
