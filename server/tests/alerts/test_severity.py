"""Tests for the derive_severity() function.

Reference: docs/design/alerts/design.md §2 (AlertRequest.severity field),
           server/app/alerts/severity.py (mapping table and docstring).

Severity Mapping Table (source of truth for these tests):

| label          | confidence >= 0.70 | 0.40 <= confidence < 0.70 | confidence < 0.40 |
|----------------|--------------------|---------------------------|-------------------|
| violence       | critical           | high                      | medium            |
| hate           | high               | medium                    | low               |
| pornographic   | high               | medium                    | low               |
| abusive        | medium             | medium                    | low               |
| non_offensive  | low                | low                       | low               |
"""

from __future__ import annotations

import pytest

from app.alerts import derive_severity


# ---------------------------------------------------------------------------
# Parametrized table test — mirrors the mapping table exactly.
# ---------------------------------------------------------------------------

MAPPING_TABLE: list[tuple[str, float, str]] = [
    # (label, confidence, expected_severity)
    # --- violence ---
    ("violence",      1.00, "critical"),
    ("violence",      0.70, "critical"),
    ("violence",      0.69, "high"),
    ("violence",      0.50, "high"),
    ("violence",      0.40, "high"),
    ("violence",      0.39, "medium"),
    ("violence",      0.00, "medium"),
    # --- hate ---
    ("hate",          1.00, "high"),
    ("hate",          0.70, "high"),
    ("hate",          0.69, "medium"),
    ("hate",          0.50, "medium"),
    ("hate",          0.40, "medium"),
    ("hate",          0.39, "low"),
    ("hate",          0.00, "low"),
    # --- pornographic ---
    ("pornographic",  1.00, "high"),
    ("pornographic",  0.70, "high"),
    ("pornographic",  0.69, "medium"),
    ("pornographic",  0.50, "medium"),
    ("pornographic",  0.40, "medium"),
    ("pornographic",  0.39, "low"),
    ("pornographic",  0.00, "low"),
    # --- abusive ---
    ("abusive",       1.00, "medium"),
    ("abusive",       0.70, "medium"),
    ("abusive",       0.69, "medium"),
    ("abusive",       0.50, "medium"),
    ("abusive",       0.40, "medium"),
    ("abusive",       0.39, "low"),
    ("abusive",       0.00, "low"),
    # --- non_offensive (safe default in all cases) ---
    ("non_offensive", 1.00, "low"),
    ("non_offensive", 0.70, "low"),
    ("non_offensive", 0.50, "low"),
    ("non_offensive", 0.00, "low"),
]


@pytest.mark.parametrize("label,confidence,expected", MAPPING_TABLE)
def test_derive_severity_mapping(label: str, confidence: float, expected: str) -> None:
    """derive_severity(label, confidence) matches the mapping table."""
    result = derive_severity(label, confidence)  # type: ignore[arg-type]
    assert result == expected, (
        f"derive_severity({label!r}, {confidence}) → {result!r}; "
        f"expected {expected!r}"
    )


# ---------------------------------------------------------------------------
# Boundary conditions — exact threshold values.
# ---------------------------------------------------------------------------


def test_exactly_at_high_threshold_is_top_tier() -> None:
    """confidence=0.70 exactly → top tier for violence."""
    assert derive_severity("violence", 0.70) == "critical"


def test_just_below_high_threshold_is_mid_tier() -> None:
    """confidence=0.699 → middle tier for violence (not critical)."""
    # 0.699 < 0.70 threshold
    result = derive_severity("violence", 0.699)
    assert result == "high"


def test_exactly_at_medium_threshold_is_mid_tier() -> None:
    """confidence=0.40 exactly → middle tier for hate."""
    assert derive_severity("hate", 0.40) == "medium"


def test_just_below_medium_threshold_is_bottom_tier() -> None:
    """confidence=0.399 → bottom tier for hate (low)."""
    result = derive_severity("hate", 0.399)
    assert result == "low"


# ---------------------------------------------------------------------------
# Return type is always a valid Severity literal.
# ---------------------------------------------------------------------------


VALID_SEVERITIES = {"low", "medium", "high", "critical"}


@pytest.mark.parametrize("label", ["violence", "hate", "pornographic", "abusive", "non_offensive"])
@pytest.mark.parametrize("confidence", [0.0, 0.25, 0.5, 0.75, 1.0])
def test_return_type_is_valid_severity(label: str, confidence: float) -> None:
    """derive_severity always returns a valid Severity literal."""
    result = derive_severity(label, confidence)  # type: ignore[arg-type]
    assert result in VALID_SEVERITIES, f"Invalid severity: {result!r}"
