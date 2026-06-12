"""Tests for the ``provided_history`` param on ``LlmContextAgent.evaluate()``.

Covers:
  1. evaluate(provided_history=[...]) — skips read_history tool, uses supplied
     turns, records "provided_history" in tools_called.
  2. evaluate() without provided_history — existing behaviour: read_history is
     called, "read_history" appears in tools_called (regression guard).
  3. History appears in the LLM prompt (the MockLlmClient receives the prompt
     containing the supplied turns).

Run from repo root:
    python -m pytest server/tests/context_agent/test_provided_history.py -q
"""

from __future__ import annotations

import asyncio

import pytest

from app.context_agent.agent import LlmContextAgent
from app.context_agent.clients.mock_client import MockLlmClient
from app.context_agent.token_manager import InMemoryTokenManager
from app.schemas import ClassificationResult, ContextDecision

from .conftest import FakeAuditStore


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _make_result() -> ClassificationResult:
    return ClassificationResult(
        label="abusive",
        confidence=0.55,
        is_offensive=True,
        model_version="v1.0-test",
        latency_ms=5.0,
        is_borderline=True,
        raw_confidence=0.55,
        error=False,
    )


def _make_agent(audit_store=None, primary=None) -> LlmContextAgent:
    return LlmContextAgent(
        primary=primary or MockLlmClient(),
        fallback=MockLlmClient(),
        budget=InMemoryTokenManager(daily_usd_budget=10.0),
        audit_store=audit_store or FakeAuditStore(),
        slang_lexicon_path="server/data/slang_lexicon.json",
    )


# ---------------------------------------------------------------------------
# A MockLlmClient subclass that records the user prompt it was called with
# ---------------------------------------------------------------------------


class _CapturingMockClient(MockLlmClient):
    """MockLlmClient that stores the last user prompt it received."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.last_user_prompt: str | None = None

    async def reason(
        self,
        system: str,
        user: str,
        max_tokens: int = 512,
        temperature: float = 0.2,
    ):
        self.last_user_prompt = user
        return await super().reason(system, user, max_tokens=max_tokens, temperature=temperature)


# ---------------------------------------------------------------------------
# Test 1: provided_history skips read_history, appears in tools_called
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_provided_history_skips_read_history():
    """When provided_history is given, read_history must NOT be called.

    ``tools_called`` must contain "provided_history" and must NOT contain
    "read_history".
    """
    store = FakeAuditStore()
    # Pre-seed the store with some history — it must NOT be fetched.
    await store.record_conversation_turn("child_test", 0, "child_outbound", "שלום")

    agent = _make_agent(audit_store=store)

    result = await agent.evaluate(
        text="אתה גנב",
        classifier_result=_make_result(),
        child_id="child_test",
        trace_id="test-provided",
        provided_history=[
            {"role": "screenshot_line", "text": "מה שלומך"},
            {"role": "screenshot_line", "text": "אתה גנב"},
        ],
    )

    assert isinstance(result, ContextDecision)
    assert "provided_history" in result.tools_called, (
        f"Expected 'provided_history' in tools_called, got: {result.tools_called}"
    )
    assert "read_history" not in result.tools_called, (
        f"read_history must NOT be called when provided_history is given, "
        f"got: {result.tools_called}"
    )


# ---------------------------------------------------------------------------
# Test 2: without provided_history → read_history is called (regression guard)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_provided_history_uses_read_history():
    """Without provided_history, the existing read_history path is taken.

    ``tools_called`` must contain "read_history".
    """
    store = FakeAuditStore()
    await store.record_conversation_turn("child_008", 0, "child_outbound", "היי")

    agent = _make_agent(audit_store=store)

    result = await agent.evaluate(
        text="אתה נוראי",
        classifier_result=_make_result(),
        child_id="child_008",
        trace_id="test-no-provided",
        # provided_history not passed → default None
    )

    assert isinstance(result, ContextDecision)
    assert "read_history" in result.tools_called, (
        f"Expected 'read_history' in tools_called when provided_history=None, "
        f"got: {result.tools_called}"
    )
    assert "provided_history" not in result.tools_called


# ---------------------------------------------------------------------------
# Test 3: provided turns appear in the LLM prompt
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_provided_history_turns_appear_in_prompt():
    """The turns in ``provided_history`` must be present in the user prompt
    that is forwarded to the LLM.
    """
    capturing_client = _CapturingMockClient()
    agent = _make_agent(primary=capturing_client)

    turns = [
        {"role": "screenshot_line", "text": "line one"},
        {"role": "screenshot_line", "text": "line two offending"},
    ]

    result = await agent.evaluate(
        text="line two offending",
        classifier_result=_make_result(),
        child_id="child_prompt_test",
        provided_history=turns,
    )

    assert isinstance(result, ContextDecision)
    assert capturing_client.last_user_prompt is not None, (
        "MockLlmClient was never called — test setup is wrong"
    )
    prompt = capturing_client.last_user_prompt
    assert "line one" in prompt, (
        f"Expected 'line one' in user prompt; prompt excerpt:\n{prompt[:500]}"
    )
    assert "line two offending" in prompt, (
        f"Expected 'line two offending' in user prompt"
    )


# ---------------------------------------------------------------------------
# Test 4: empty provided_history is accepted (renders as "no history" block)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_provided_history_is_accepted():
    """An empty list is a valid provided_history — the CA must not crash."""
    agent = _make_agent()
    result = await agent.evaluate(
        text="test",
        classifier_result=_make_result(),
        provided_history=[],
    )
    assert isinstance(result, ContextDecision)
    assert "provided_history" in result.tools_called
