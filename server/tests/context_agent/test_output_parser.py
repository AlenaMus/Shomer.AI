"""Unit tests for the output_parser module.

Reference: docs/design/context_agent/design.md §7.3.
"""

from __future__ import annotations

import json

import pytest

from app.context_agent.output_parser import AgentLlmResponse, parse_llm_output


# --------------------------------------------------------------------------- #
# Valid JSON                                                                   #
# --------------------------------------------------------------------------- #


def test_parse_valid_not_threat():
    raw = json.dumps({
        "is_real_threat": False,
        "severity": "none",
        "explanation": "שיחה ידידותית",
        "reasoning": "playful banter",
    })
    result, ok = parse_llm_output(raw)
    assert ok is True
    assert result.is_real_threat is False
    assert result.severity == "none"
    assert result.explanation == "שיחה ידידותית"


def test_parse_valid_threat():
    raw = json.dumps({
        "is_real_threat": True,
        "severity": "high",
        "explanation": "איום ישיר",
        "reasoning": "explicit threat detected",
    })
    result, ok = parse_llm_output(raw)
    assert ok is True
    assert result.is_real_threat is True
    assert result.severity == "high"


def test_parse_valid_no_reasoning_field():
    """reasoning field is optional — should use default empty string."""
    raw = json.dumps({
        "is_real_threat": False,
        "severity": "low",
        "explanation": "בסדר",
    })
    result, ok = parse_llm_output(raw)
    assert ok is True
    assert result.reasoning == ""


# --------------------------------------------------------------------------- #
# Invalid JSON → safe defaults                                                 #
# --------------------------------------------------------------------------- #


def test_parse_invalid_json_returns_safe_default():
    result, ok = parse_llm_output("this is not json at all")
    assert ok is False
    assert result.is_real_threat is True  # fail-safe: escalate
    assert result.severity == "low"
    assert "parse_error" in result.reasoning


def test_parse_empty_string_returns_safe_default():
    result, ok = parse_llm_output("")
    assert ok is False
    assert result.is_real_threat is True


def test_parse_missing_required_fields_uses_defaults():
    """Partial JSON — missing is_real_threat → model default (True, fail-safe)."""
    raw = json.dumps({"explanation": "something"})
    result, ok = parse_llm_output(raw)
    assert ok is True  # JSON parsed ok; defaults kicked in from Pydantic
    assert result.is_real_threat is True  # Pydantic default
    assert result.explanation == "something"


def test_parse_invalid_severity_value():
    """Severity not in enum → parse fails → safe default."""
    raw = json.dumps({
        "is_real_threat": False,
        "severity": "extreme",  # not in Literal
        "explanation": "test",
    })
    result, ok = parse_llm_output(raw)
    assert ok is False
    assert result.is_real_threat is True  # safe default


def test_parse_empty_explanation_rejected():
    """Empty explanation → validator raises → safe default."""
    raw = json.dumps({
        "is_real_threat": False,
        "severity": "none",
        "explanation": "   ",  # only whitespace
    })
    result, ok = parse_llm_output(raw)
    assert ok is False
    assert result.is_real_threat is True  # fail-safe


def test_parse_whitespace_only_json():
    result, ok = parse_llm_output("   ")
    assert ok is False
    assert result.is_real_threat is True


# --------------------------------------------------------------------------- #
# AgentLlmResponse model                                                      #
# --------------------------------------------------------------------------- #


def test_agent_llm_response_severity_literals():
    for sev in ("none", "low", "medium", "high"):
        r = AgentLlmResponse(
            is_real_threat=False,
            severity=sev,
            explanation="test",
        )
        assert r.severity == sev


def test_agent_llm_response_explanation_validator():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        AgentLlmResponse(
            is_real_threat=False,
            severity="low",
            explanation="",
        )
