"""End-to-end tests for LlmContextAgent.

Uses: MockLlmClient + InMemoryTokenManager + FakeAuditStore.
No network calls, no disk writes (except SQLite for SQLiteTokenManager tests).

Reference: docs/design/context_agent/design.md §3, §4, §8.
"""

from __future__ import annotations

import asyncio

import pytest

from app.context_agent.agent import LlmContextAgent
from app.context_agent.clients.mock_client import MockLlmClient
from app.context_agent.token_manager import InMemoryTokenManager
from app.schemas import ClassificationResult, ContextDecision

from .conftest import FakeAuditStore


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #


def make_agent(
    primary=None,
    fallback=None,
    budget=None,
    audit_store=None,
    **kwargs,
) -> LlmContextAgent:
    return LlmContextAgent(
        primary=primary or MockLlmClient(),
        fallback=fallback or MockLlmClient(),
        budget=budget or InMemoryTokenManager(daily_usd_budget=10.0),
        audit_store=audit_store or FakeAuditStore(),
        slang_lexicon_path="server/data/slang_lexicon.json",
        **kwargs,
    )


class FailingClient:
    model_name = "failing"

    async def reason(self, *a, **kw):
        raise RuntimeError("forced failure")

    async def health(self):
        from app.schemas import HealthState
        return (HealthState.DOWN, "failing")


class SlowClient:
    model_name = "slow"

    async def reason(self, *a, **kw):
        await asyncio.sleep(10)
        raise asyncio.TimeoutError()

    async def health(self):
        from app.schemas import HealthState
        return (HealthState.DEGRADED, "slow")


# --------------------------------------------------------------------------- #
# Happy path                                                                   #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_happy_path_not_threat(sample_classifier_result):
    agent = make_agent()
    result = await agent.evaluate(
        text="לוזר, בוא נשחק",
        classifier_result=sample_classifier_result,
        child_id="child_001",
        trace_id="e2e-happy",
    )
    assert isinstance(result, ContextDecision)
    assert result.is_real_threat is False
    assert result.review_flag is False
    assert result.model_used == "mock"
    assert result.latency_ms >= 0
    assert len(result.tools_called) > 0  # tools were called


@pytest.mark.asyncio
async def test_happy_path_threat(sample_classifier_result):
    client = MockLlmClient(
        canned_response={
            "is_real_threat": True,
            "severity": "high",
            "explanation": "איום ישיר",
            "reasoning": "threat identified",
        }
    )
    agent = make_agent(primary=client)
    result = await agent.evaluate(
        text="אני אשכח אותך",
        classifier_result=sample_classifier_result,
        trace_id="e2e-threat",
    )
    assert result.is_real_threat is True
    assert result.severity == "high"


# --------------------------------------------------------------------------- #
# Fallback path: primary fails → fallback used                                #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_primary_fails_fallback_used(sample_classifier_result):
    fallback = MockLlmClient(
        canned_response={
            "is_real_threat": False,
            "severity": "low",
            "explanation": "מ fallback",
            "reasoning": "fallback ok",
        }
    )
    agent = make_agent(primary=FailingClient(), fallback=fallback)
    result = await agent.evaluate(
        text="test",
        classifier_result=sample_classifier_result,
        trace_id="e2e-fallback",
    )
    # Fallback mock returns is_real_threat=False
    assert isinstance(result, ContextDecision)
    assert result.review_flag is False


# --------------------------------------------------------------------------- #
# Both LLMs fail → review_flag                                                #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_both_llms_fail(sample_classifier_result):
    agent = make_agent(
        primary=FailingClient(),
        fallback=FailingClient(),
    )
    result = await agent.evaluate(
        text="test",
        classifier_result=sample_classifier_result,
        trace_id="e2e-both-fail",
    )
    assert result.review_flag is True
    assert result.model_used is None


# --------------------------------------------------------------------------- #
# Timeout → review_flag                                                        #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_timeout_returns_review_flag(sample_classifier_result):
    agent = make_agent(
        primary=SlowClient(),
        fallback=SlowClient(),
        timeout_s=0.05,
    )
    result = await agent.evaluate(
        text="test",
        classifier_result=sample_classifier_result,
        trace_id="e2e-timeout",
    )
    assert result.review_flag is True
    assert result.model_used is None


# --------------------------------------------------------------------------- #
# Budget exhausted → review_flag                                               #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_budget_exhausted_review_flag(sample_classifier_result):
    tiny_budget = InMemoryTokenManager(
        token_prices_path="server/app/context_agent/token_prices.yaml",
        daily_token_budget=1,
        daily_usd_budget=0.0000001,
    )
    agent = make_agent(budget=tiny_budget)
    result = await agent.evaluate(
        text="test",
        classifier_result=sample_classifier_result,
        trace_id="e2e-budget",
    )
    assert result.review_flag is True
    assert result.model_used is None


@pytest.mark.asyncio
async def test_budget_exhausted_is_real_threat_follows_frontline(
    sample_classifier_result,
):
    """Safety invariant: budget exhaustion never silently clears a threat."""
    tiny_budget = InMemoryTokenManager(
        token_prices_path="server/app/context_agent/token_prices.yaml",
        daily_token_budget=1,
        daily_usd_budget=0.0000001,
    )
    agent = make_agent(budget=tiny_budget)
    result = await agent.evaluate(
        text="test",
        classifier_result=sample_classifier_result,  # is_offensive=True
    )
    assert result.is_real_threat == sample_classifier_result.is_offensive


# --------------------------------------------------------------------------- #
# Malformed JSON from LLM                                                      #
# --------------------------------------------------------------------------- #


class MalformedLlmClient:
    model_name = "malformed"

    async def reason(self, *a, **kw):
        from app.context_agent.protocol import LlmCallResult
        return LlmCallResult(
            text="NOT VALID JSON {{{",
            input_tokens=50,
            output_tokens=30,
            model="malformed",
        )

    async def health(self):
        from app.schemas import HealthState
        return (HealthState.OK, "malformed but alive")


@pytest.mark.asyncio
async def test_malformed_json_review_flag(sample_classifier_result):
    agent = make_agent(primary=MalformedLlmClient())
    result = await agent.evaluate(
        text="test",
        classifier_result=sample_classifier_result,
        trace_id="e2e-malformed",
    )
    # parse_llm_output returns (is_real_threat=True, parse_ok=False)
    assert result.review_flag is True
    # fail-safe: is_real_threat=True (from parse safe default)
    assert result.is_real_threat is True


# --------------------------------------------------------------------------- #
# Conversation history integration                                             #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_history_is_fetched_for_child(sample_classifier_result):
    store = FakeAuditStore()
    await store.record_conversation_turn("child_007", 0, "child_outbound", "שלום")
    await store.record_conversation_turn("child_007", 1, "child_inbound", "היי")

    agent = make_agent(audit_store=store)
    result = await agent.evaluate(
        text="test",
        classifier_result=sample_classifier_result,
        child_id="child_007",
    )
    # Agent completed; history was available (tools were called)
    assert "read_history" in result.tools_called


# --------------------------------------------------------------------------- #
# Health check                                                                 #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_health_ok_when_mock_client():
    agent = make_agent()
    from app.schemas import HealthState
    state, detail = await agent.health()
    assert state == HealthState.OK


# --------------------------------------------------------------------------- #
# Never raises from evaluate()                                                 #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_never_raises_on_unexpected_input(sample_classifier_result):
    """evaluate() must not raise on any input."""
    agent = make_agent()
    # Completely empty text
    result = await agent.evaluate(text="", classifier_result=sample_classifier_result)
    assert isinstance(result, ContextDecision)

    # Very long text
    long_text = "א" * 5000
    result = await agent.evaluate(text=long_text, classifier_result=sample_classifier_result)
    assert isinstance(result, ContextDecision)

    # None child_id
    result = await agent.evaluate(
        text="test",
        classifier_result=sample_classifier_result,
        child_id=None,
    )
    assert isinstance(result, ContextDecision)
