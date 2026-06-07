"""Polarity matrix tests for ThresholdTriageEngine.

Reference: docs/design/triage/design.md §3 (Polarity Test Matrix).

These six rows are the MANDATORY cases from the LLD. They exercise both
directions of the G-03 normalization fix (is_offensive=True vs False) across
the three routing zones (SILENT / borderline / ALERT_DIRECT).

G-03 regression case (row 4):
    is_offensive=False, confidence=0.92
    → prob_offensive = 1 - 0.92 = 0.08
    → 0.08 <= borderline_low (0.3)
    → SILENT   (was incorrectly ALERT_DIRECT before the fix)

All tests use the default TriageSettings (borderline_low=0.3, borderline_high=0.7,
baseline_threshold=0.5, context_agent_enabled=True for the CA-on group).
"""

from __future__ import annotations

import pytest

from app.schemas import ClassificationResult, TriageDecision
from app.triage import ThresholdTriageEngine, TriageSettings

from .conftest import make_result


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _engine(monkeypatch: pytest.MonkeyPatch, **setting_overrides) -> ThresholdTriageEngine:
    """Build a ThresholdTriageEngine with clean env + optional setting overrides."""
    for var in (
        "BORDERLINE_LOW",
        "BORDERLINE_HIGH",
        "TRIAGE_BASELINE_THRESHOLD",
        "CONTEXT_AGENT_ENABLED",
        "TRIAGE_ALWAYS_ESCALATE_LABELS",
        "TRIAGE_ALWAYS_ALERT_LABELS",
    ):
        monkeypatch.delenv(var, raising=False)
    settings = TriageSettings(**setting_overrides)
    return ThresholdTriageEngine(settings)


# ---------------------------------------------------------------------------
# The mandatory 6-row polarity matrix (LLD §3, table)
# Settings: borderline_low=0.3, borderline_high=0.7, baseline_threshold=0.5
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "is_offensive, confidence, prob_offensive_expected, expected_decision, ca_enabled, description",
    [
        # Row 1: confidently offensive — prob_offensive=0.92 >= borderline_high(0.7)
        (
            True, 0.92, 0.92,
            TriageDecision.ALERT_DIRECT,
            True,
            "is_offensive=True, confidence=0.92 → ALERT_DIRECT",
        ),
        # Row 2: borderline offensive — prob_offensive=0.55 in [0.3, 0.7], CA on
        (
            True, 0.55, 0.55,
            TriageDecision.ESCALATE_TO_CA,
            True,
            "is_offensive=True, confidence=0.55 → ESCALATE_TO_CA (CA enabled)",
        ),
        # Row 3: low-confidence offensive — prob_offensive=0.20 <= borderline_low(0.3)
        (
            True, 0.20, 0.20,
            TriageDecision.SILENT,
            True,
            "is_offensive=True, confidence=0.20 → SILENT",
        ),
        # Row 4: G-03 REGRESSION — confidently non-offensive, must NOT be ALERT_DIRECT
        # is_offensive=False, confidence=0.92 → prob_offensive=0.08 → SILENT
        (
            False, 0.92, 0.08,
            TriageDecision.SILENT,
            True,
            "G-03: is_offensive=False, confidence=0.92 → prob_offensive=0.08 → SILENT (was ALERT_DIRECT before fix)",
        ),
        # Row 5: borderline non-offensive — prob_offensive=1-0.55=0.45 in [0.3, 0.7], CA on
        (
            False, 0.55, 0.45,
            TriageDecision.ESCALATE_TO_CA,
            True,
            "is_offensive=False, confidence=0.55 → prob_offensive=0.45 → ESCALATE_TO_CA",
        ),
        # Row 6: low-confidence non-offensive — prob_offensive=1-0.20=0.80 >= borderline_high(0.7)
        (
            False, 0.20, 0.80,
            TriageDecision.ALERT_DIRECT,
            True,
            "is_offensive=False, confidence=0.20 → prob_offensive=0.80 → ALERT_DIRECT",
        ),
    ],
)
def test_polarity_matrix(
    monkeypatch: pytest.MonkeyPatch,
    is_offensive: bool,
    confidence: float,
    prob_offensive_expected: float,
    expected_decision: TriageDecision,
    ca_enabled: bool,
    description: str,
) -> None:
    """Mandatory 6-row polarity matrix from the LLD."""
    engine = _engine(monkeypatch)
    label = "abusive" if is_offensive else "non_offensive"
    result = make_result(
        label=label,
        confidence=confidence,
        is_offensive=is_offensive,
    )
    decision = engine.decide(result, context_agent_enabled=ca_enabled)
    assert decision == expected_decision, (
        f"FAILED: {description}\n"
        f"  is_offensive={is_offensive}, confidence={confidence}\n"
        f"  expected prob_offensive≈{prob_offensive_expected:.2f}\n"
        f"  expected={expected_decision.value}, got={decision.value}"
    )


# ---------------------------------------------------------------------------
# A/B baseline path — CA disabled, borderline zone
# ---------------------------------------------------------------------------


def test_ab_baseline_borderline_above_threshold_gives_alert_direct(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CA disabled + prob_offensive=0.55 >= baseline_threshold(0.5) → ALERT_DIRECT."""
    engine = _engine(monkeypatch)
    # is_offensive=True, confidence=0.55 → prob_offensive=0.55 ∈ [0.3, 0.7]
    result = make_result(label="abusive", confidence=0.55, is_offensive=True)
    decision = engine.decide(result, context_agent_enabled=False)
    assert decision == TriageDecision.ALERT_DIRECT, (
        f"A/B baseline: expected ALERT_DIRECT (prob=0.55 >= threshold=0.5), got {decision.value}"
    )


def test_ab_baseline_borderline_below_threshold_gives_silent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CA disabled + prob_offensive=0.40 < baseline_threshold(0.5) → SILENT."""
    engine = _engine(monkeypatch)
    # is_offensive=True, confidence=0.40 → prob_offensive=0.40 ∈ [0.3, 0.7]
    result = make_result(label="abusive", confidence=0.40, is_offensive=True)
    decision = engine.decide(result, context_agent_enabled=False)
    assert decision == TriageDecision.SILENT, (
        f"A/B baseline: expected SILENT (prob=0.40 < threshold=0.5), got {decision.value}"
    )


# ---------------------------------------------------------------------------
# Error path
# ---------------------------------------------------------------------------


def test_error_true_gives_review_needed(monkeypatch: pytest.MonkeyPatch) -> None:
    """result.error=True always maps to REVIEW_NEEDED."""
    engine = _engine(monkeypatch)
    result = make_result(
        label="non_offensive",
        confidence=0.5,
        is_offensive=False,
        error=True,
    )
    for ca_enabled in (True, False):
        decision = engine.decide(result, context_agent_enabled=ca_enabled)
        assert decision == TriageDecision.REVIEW_NEEDED, (
            f"error=True with ca_enabled={ca_enabled}: "
            f"expected REVIEW_NEEDED, got {decision.value}"
        )


# ---------------------------------------------------------------------------
# Label override paths
# ---------------------------------------------------------------------------


def test_always_escalate_label_with_ca_enabled_gives_escalate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """'violence' label + CA enabled → ESCALATE_TO_CA regardless of confidence."""
    engine = _engine(monkeypatch)
    # Low confidence offensive — without override this would be SILENT (prob=0.20)
    result = make_result(label="violence", confidence=0.20, is_offensive=True)
    decision = engine.decide(result, context_agent_enabled=True)
    assert decision == TriageDecision.ESCALATE_TO_CA, (
        f"always_escalate label with CA on: expected ESCALATE_TO_CA, got {decision.value}"
    )


def test_always_escalate_label_with_ca_disabled_gives_alert_direct(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """'violence' label + CA disabled → ALERT_DIRECT (override + A/B baseline)."""
    engine = _engine(monkeypatch)
    result = make_result(label="violence", confidence=0.55, is_offensive=True)
    decision = engine.decide(result, context_agent_enabled=False)
    assert decision == TriageDecision.ALERT_DIRECT, (
        f"always_escalate label with CA off: expected ALERT_DIRECT, got {decision.value}"
    )


def test_always_alert_label_gives_alert_direct_regardless_of_ca(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """'pornographic' label always produces ALERT_DIRECT (both CA states)."""
    engine = _engine(monkeypatch)
    result = make_result(label="pornographic", confidence=0.35, is_offensive=True)
    for ca_enabled in (True, False):
        decision = engine.decide(result, context_agent_enabled=ca_enabled)
        assert decision == TriageDecision.ALERT_DIRECT, (
            f"always_alert label with ca_enabled={ca_enabled}: "
            f"expected ALERT_DIRECT, got {decision.value}"
        )


# ---------------------------------------------------------------------------
# Boundary values
# ---------------------------------------------------------------------------


def test_exactly_borderline_low_is_silent(monkeypatch: pytest.MonkeyPatch) -> None:
    """prob_offensive == borderline_low (0.3) → SILENT (inclusive lower bound)."""
    engine = _engine(monkeypatch)
    # is_offensive=True, confidence=0.3 → prob_offensive=0.3 (at boundary)
    result = make_result(label="abusive", confidence=0.3, is_offensive=True)
    decision = engine.decide(result, context_agent_enabled=True)
    assert decision == TriageDecision.SILENT, (
        f"At borderline_low boundary: expected SILENT, got {decision.value}"
    )


def test_exactly_borderline_high_is_alert_direct(monkeypatch: pytest.MonkeyPatch) -> None:
    """prob_offensive == borderline_high (0.7) → ALERT_DIRECT (inclusive upper bound)."""
    engine = _engine(monkeypatch)
    result = make_result(label="abusive", confidence=0.7, is_offensive=True)
    decision = engine.decide(result, context_agent_enabled=True)
    assert decision == TriageDecision.ALERT_DIRECT, (
        f"At borderline_high boundary: expected ALERT_DIRECT, got {decision.value}"
    )


# ---------------------------------------------------------------------------
# Settings validation
# ---------------------------------------------------------------------------


def test_invalid_settings_raises_on_construction(monkeypatch: pytest.MonkeyPatch) -> None:
    """TriageSettings raises ValueError when borderline_low >= borderline_high."""
    for var in (
        "BORDERLINE_LOW",
        "BORDERLINE_HIGH",
        "TRIAGE_BASELINE_THRESHOLD",
        "CONTEXT_AGENT_ENABLED",
        "TRIAGE_ALWAYS_ESCALATE_LABELS",
        "TRIAGE_ALWAYS_ALERT_LABELS",
    ):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(Exception):  # pydantic ValidationError wraps ValueError
        TriageSettings(borderline_low=0.7, borderline_high=0.3)
