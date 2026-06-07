"""TriageEngine Protocol contract tests.

Reference: docs/design/triage/design.md §2.5, §7.

Parametrized over every concrete adapter so any new adapter only needs to be
added to the ``ADAPTERS`` list below — no new test functions required.

Contract invariants (every adapter MUST satisfy):
1. ``isinstance(engine, TriageEngine)`` is True (runtime_checkable Protocol).
2. ``decide()`` returns a valid ``TriageDecision`` enum value.
3. ``decide()`` NEVER raises for any valid ``ClassificationResult``.
4. ``decide()`` NEVER raises for a result with ``error=True``.
5. ``decide()`` returns ``REVIEW_NEEDED`` when ``result.error=True``
   (for ``ThresholdTriageEngine``; Stub returns its fixed decision).
6. When ``context_agent_enabled=False``, the result is never ``ESCALATE_TO_CA``.
"""

from __future__ import annotations

import pytest

from app.schemas import ClassificationResult, TriageDecision
from app.triage import StubTriageEngine, ThresholdTriageEngine, TriageEngine, TriageSettings

from .conftest import make_result


# ---------------------------------------------------------------------------
# Adapter parametrization
# ---------------------------------------------------------------------------

VALID_DECISIONS = set(TriageDecision)


def _build_threshold(monkeypatch: pytest.MonkeyPatch) -> ThresholdTriageEngine:
    for var in (
        "BORDERLINE_LOW",
        "BORDERLINE_HIGH",
        "TRIAGE_BASELINE_THRESHOLD",
        "CONTEXT_AGENT_ENABLED",
        "TRIAGE_ALWAYS_ESCALATE_LABELS",
        "TRIAGE_ALWAYS_ALERT_LABELS",
    ):
        monkeypatch.delenv(var, raising=False)
    return ThresholdTriageEngine(TriageSettings())


def _build_stub() -> StubTriageEngine:
    return StubTriageEngine()


@pytest.fixture(params=["threshold", "stub"])
def engine_name(request: pytest.FixtureRequest) -> str:
    return request.param


@pytest.fixture
def engine(engine_name: str, monkeypatch: pytest.MonkeyPatch) -> TriageEngine:
    if engine_name == "threshold":
        return _build_threshold(monkeypatch)
    if engine_name == "stub":
        return _build_stub()
    raise ValueError(f"unknown engine {engine_name!r}")


# ---------------------------------------------------------------------------
# Fixtures — five canonical ClassificationResult inputs from the LLD §2.5
# ---------------------------------------------------------------------------


@pytest.fixture(
    params=[
        "confident_non_offensive",
        "borderline_offensive",
        "confident_offensive",
        "error_result",
        "label_violence",
    ]
)
def sample_result(request: pytest.FixtureRequest) -> ClassificationResult:
    tag = request.param
    if tag == "confident_non_offensive":
        return make_result(
            label="non_offensive",
            confidence=0.92,
            is_offensive=False,
            is_borderline=False,
        )
    if tag == "borderline_offensive":
        return make_result(
            label="abusive",
            confidence=0.55,
            is_offensive=True,
            is_borderline=True,
        )
    if tag == "confident_offensive":
        return make_result(
            label="abusive",
            confidence=0.85,
            is_offensive=True,
            is_borderline=False,
        )
    if tag == "error_result":
        return make_result(
            label="non_offensive",
            confidence=0.5,
            is_offensive=False,
            error=True,
        )
    if tag == "label_violence":
        return make_result(
            label="violence",
            confidence=0.40,
            is_offensive=True,
            is_borderline=True,
        )
    raise ValueError(f"unknown tag {tag!r}")


# ---------------------------------------------------------------------------
# Contract tests
# ---------------------------------------------------------------------------


def test_runtime_checkable(engine: TriageEngine) -> None:
    """Every adapter satisfies ``isinstance(engine, TriageEngine)``."""
    assert isinstance(engine, TriageEngine), (
        f"{type(engine).__name__} does not satisfy isinstance check for TriageEngine"
    )


def test_decide_returns_valid_decision(
    engine: TriageEngine,
    sample_result: ClassificationResult,
) -> None:
    """``decide()`` always returns a valid ``TriageDecision`` enum member."""
    decision = engine.decide(sample_result, context_agent_enabled=True)
    assert decision in VALID_DECISIONS, (
        f"decide() returned {decision!r} which is not a TriageDecision"
    )


def test_decide_never_raises(
    engine: TriageEngine,
    sample_result: ClassificationResult,
) -> None:
    """``decide()`` never raises, even for error results."""
    # Should not raise under any circumstance
    decision = engine.decide(sample_result, context_agent_enabled=True)
    assert isinstance(decision, TriageDecision)


def test_decide_ca_disabled_never_escalates(
    engine: TriageEngine,
    sample_result: ClassificationResult,
    engine_name: str,
) -> None:
    """When context_agent_enabled=False, result is never ESCALATE_TO_CA."""
    if engine_name == "stub":
        # StubTriageEngine always returns its fixed decision regardless of the flag;
        # it's not expected to honour the CA-disabled constraint.
        pytest.skip("StubTriageEngine returns a fixed decision — skip CA constraint check")

    decision = engine.decide(sample_result, context_agent_enabled=False)
    assert decision != TriageDecision.ESCALATE_TO_CA, (
        f"context_agent_enabled=False must not produce ESCALATE_TO_CA, got {decision!r}"
    )


def test_threshold_error_result_produces_review_needed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ThresholdTriageEngine maps result.error=True → REVIEW_NEEDED."""
    engine = _build_threshold(monkeypatch)
    result = make_result(error=True, label="non_offensive", confidence=0.5, is_offensive=False)
    decision = engine.decide(result, context_agent_enabled=True)
    assert decision == TriageDecision.REVIEW_NEEDED


def test_stub_returns_configured_decision() -> None:
    """StubTriageEngine returns whatever decision it was constructed with."""
    for fixed in TriageDecision:
        stub = StubTriageEngine(fixed_decision=fixed)
        result = make_result()
        assert stub.decide(result, context_agent_enabled=True) == fixed
        assert stub.decide(result, context_agent_enabled=False) == fixed


def test_decide_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same input + same settings → same decision on 50 consecutive calls."""
    engine = _build_threshold(monkeypatch)
    result = make_result(label="abusive", confidence=0.55, is_offensive=True)
    first = engine.decide(result, context_agent_enabled=True)
    for _ in range(49):
        assert engine.decide(result, context_agent_enabled=True) == first, (
            "ThresholdTriageEngine is not idempotent"
        )
