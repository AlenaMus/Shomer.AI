"""Contract tests for the ContextReasoner Protocol.

Parametrized over ``LlmContextAgent(MockLlmClient, InMemoryTokenManager, FakeAuditStore)``.

Assertions (per docs/design/README.md §5 contract testing):
  - ``evaluate()`` NEVER raises.
  - Returns a ``ContextDecision`` instance.
  - ``isinstance(agent, ContextReasoner)`` is True.
  - Budget-exhausted path returns ``review_flag=True`` with ``model_used=None``.
  - Both-LLMs-fail path (None from router) returns ``review_flag=True``.

Reference: docs/design/context_agent/design.md §2.5 contract tests.
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from app.context_agent import ContextReasoner
from app.context_agent.agent import LlmContextAgent
from app.context_agent.clients.mock_client import MockLlmClient
from app.context_agent.token_manager import InMemoryTokenManager
from app.schemas import ContextDecision

from .conftest import FakeAuditStore


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #

def make_agent(
    primary=None,
    fallback=None,
    budget=None,
    audit_store=None,
) -> LlmContextAgent:
    primary = primary or MockLlmClient()
    fallback = fallback or MockLlmClient()
    budget = budget or InMemoryTokenManager(daily_usd_budget=10.0)
    audit_store = audit_store or FakeAuditStore()
    return LlmContextAgent(
        primary=primary,
        fallback=fallback,
        budget=budget,
        audit_store=audit_store,
        slang_lexicon_path="server/data/slang_lexicon.json",
    )


# --------------------------------------------------------------------------- #
# Contract: Protocol membership                                                #
# --------------------------------------------------------------------------- #


def test_agent_is_context_reasoner():
    agent = make_agent()
    assert isinstance(agent, ContextReasoner), (
        "LlmContextAgent must satisfy the ContextReasoner Protocol"
    )


# --------------------------------------------------------------------------- #
# Contract: evaluate() never raises                                            #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_evaluate_never_raises(sample_classifier_result):
    agent = make_agent()
    # Must not raise even with minimal input
    result = await agent.evaluate(
        text="מה אתה עושה לוזר",
        classifier_result=sample_classifier_result,
        child_id="child_001",
        trace_id="test-trace-001",
    )
    assert result is not None


@pytest.mark.asyncio
async def test_evaluate_returns_context_decision(sample_classifier_result):
    agent = make_agent()
    result = await agent.evaluate(
        text="test",
        classifier_result=sample_classifier_result,
    )
    assert isinstance(result, ContextDecision)


# --------------------------------------------------------------------------- #
# Contract: ContextDecision required fields                                    #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_context_decision_has_required_fields(sample_classifier_result):
    agent = make_agent()
    result = await agent.evaluate(
        text="test message",
        classifier_result=sample_classifier_result,
        child_id="child_001",
        trace_id="test-trace-002",
    )
    assert isinstance(result, ContextDecision)
    assert hasattr(result, "is_real_threat")
    assert hasattr(result, "severity")
    assert hasattr(result, "explanation")
    assert hasattr(result, "review_flag")
    assert hasattr(result, "tokens_input")
    assert hasattr(result, "tokens_output")
    assert hasattr(result, "cost_usd")
    assert hasattr(result, "model_used")
    assert hasattr(result, "reasoning_trace")
    assert hasattr(result, "tools_called")
    assert hasattr(result, "latency_ms")


# --------------------------------------------------------------------------- #
# Contract: budget-exhausted path                                              #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_budget_exhausted_returns_review_flag(
    sample_classifier_result, exhausted_budget
):
    agent = make_agent(budget=exhausted_budget)
    result = await agent.evaluate(
        text="test",
        classifier_result=sample_classifier_result,
        trace_id="budget-test",
    )
    assert isinstance(result, ContextDecision)
    assert result.review_flag is True
    assert result.model_used is None


# --------------------------------------------------------------------------- #
# Contract: both-LLMs-fail path                                               #
# --------------------------------------------------------------------------- #


class FailingLlmClient:
    model_name = "failing-mock"

    async def reason(self, system, user, max_tokens=512, temperature=0.2):
        raise RuntimeError("simulated LLM failure")

    async def health(self):
        from app.schemas import HealthState
        return (HealthState.DOWN, "always fails")


@pytest.mark.asyncio
async def test_both_llms_fail_returns_review_flag(sample_classifier_result):
    agent = make_agent(
        primary=FailingLlmClient(),
        fallback=FailingLlmClient(),
    )
    result = await agent.evaluate(
        text="test",
        classifier_result=sample_classifier_result,
        trace_id="fail-test",
    )
    assert isinstance(result, ContextDecision)
    assert result.review_flag is True


# --------------------------------------------------------------------------- #
# Contract: happy-path (MockLlmClient default = not a threat)                 #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_happy_path_not_threat(sample_classifier_result):
    """Default MockLlmClient returns is_real_threat=False."""
    agent = make_agent()
    result = await agent.evaluate(
        text="לוזר, בוא נשחק",
        classifier_result=sample_classifier_result,
        trace_id="happy-test",
    )
    assert isinstance(result, ContextDecision)
    assert result.is_real_threat is False
    assert result.review_flag is False
    assert result.model_used == "mock"


@pytest.mark.asyncio
async def test_happy_path_threat(sample_classifier_result):
    """MockLlmClient configured with threatening response."""
    client = MockLlmClient(
        canned_response={
            "is_real_threat": True,
            "severity": "high",
            "explanation": "איום ישיר",
            "reasoning": "clear threat language",
        }
    )
    agent = make_agent(primary=client)
    result = await agent.evaluate(
        text="אני אשבור אותך",
        classifier_result=sample_classifier_result,
        trace_id="threat-test",
    )
    assert result.is_real_threat is True
    assert result.severity == "high"


# --------------------------------------------------------------------------- #
# Contract: tools_called is always a tuple                                     #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_tools_called_is_tuple(sample_classifier_result):
    agent = make_agent()
    result = await agent.evaluate(
        text="test",
        classifier_result=sample_classifier_result,
    )
    assert isinstance(result.tools_called, tuple)


# --------------------------------------------------------------------------- #
# Contract: latency_ms is positive                                             #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_latency_ms_positive(sample_classifier_result):
    agent = make_agent()
    result = await agent.evaluate(
        text="test",
        classifier_result=sample_classifier_result,
    )
    assert result.latency_ms >= 0


# --------------------------------------------------------------------------- #
# Contract: safety invariant on failure (is_real_threat follows frontline)    #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_safety_invariant_on_failure(sample_classifier_result, exhausted_budget):
    """On budget exhaustion, is_real_threat must equal is_offensive from frontline."""
    agent = make_agent(budget=exhausted_budget)
    result = await agent.evaluate(
        text="test",
        classifier_result=sample_classifier_result,  # is_offensive=True
    )
    # Safety invariant: we never downgrade a potential threat to safe
    assert result.is_real_threat == sample_classifier_result.is_offensive
