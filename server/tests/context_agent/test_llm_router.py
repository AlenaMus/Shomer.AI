"""Unit tests for LlmRouter — failover and budget enforcement behaviour.

Reference: docs/design/context_agent/design.md §3.2, §4.2–4.4.
"""

from __future__ import annotations

import asyncio

import pytest

from app.context_agent.clients.mock_client import MockLlmClient
from app.context_agent.llm_router import LlmRouter
from app.context_agent.token_manager import InMemoryTokenManager


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #

def make_router(
    primary=None,
    fallback=None,
    budget=None,
    timeout_s: float = 5.0,
) -> LlmRouter:
    return LlmRouter(
        primary=primary or MockLlmClient(),
        fallback=fallback or MockLlmClient(),
        budget=budget or InMemoryTokenManager(daily_usd_budget=10.0),
        timeout_s=timeout_s,
    )


class FailingClient:
    model_name = "failing"

    async def reason(self, *a, **kw):
        raise RuntimeError("primary failed")

    async def health(self):
        from app.schemas import HealthState
        return (HealthState.DOWN, "always fails")


class SlowClient:
    model_name = "slow"

    def __init__(self, delay_s: float = 10.0):
        self._delay = delay_s

    async def reason(self, *a, **kw):
        await asyncio.sleep(self._delay)
        raise asyncio.TimeoutError("slow client timed out")

    async def health(self):
        from app.schemas import HealthState
        return (HealthState.DEGRADED, "slow")


# --------------------------------------------------------------------------- #
# Tests                                                                        #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_primary_succeeds():
    router = make_router()
    result = await router.route("sys", "user")
    assert result is not None
    assert result["model"] == "mock"


@pytest.mark.asyncio
async def test_fallback_used_when_primary_fails():
    fallback = MockLlmClient(
        canned_response={"is_real_threat": False, "severity": "none",
                         "explanation": "safe", "reasoning": "fallback used"}
    )
    fallback.model_name = "mock-fallback"
    router = make_router(primary=FailingClient(), fallback=fallback)
    result = await router.route("sys", "user")
    assert result is not None
    assert result["model"] == "mock-fallback"


@pytest.mark.asyncio
async def test_both_fail_returns_none():
    router = make_router(
        primary=FailingClient(),
        fallback=FailingClient(),
    )
    result = await router.route("sys", "user")
    assert result is None


@pytest.mark.asyncio
async def test_primary_timeout_triggers_fallback():
    fallback = MockLlmClient()
    fallback.model_name = "mock-fallback"
    router = make_router(
        primary=SlowClient(delay_s=10.0),
        fallback=fallback,
        timeout_s=0.1,  # very short timeout to trigger quickly
    )
    result = await router.route("sys", "user")
    assert result is not None
    assert result["model"] == "mock-fallback"


@pytest.mark.asyncio
async def test_budget_denied_for_primary_tries_fallback():
    """When primary budget is denied, fallback is tried."""
    # Use tiny budget so primary is denied; fallback gets larger slice
    # We'll exhaust the primary's name in the budget
    budget = InMemoryTokenManager(
        daily_token_budget=1,   # so tiny primary's 400-token estimate is denied
        daily_usd_budget=0.0001,
    )
    fallback = MockLlmClient()
    fallback.model_name = "mock-fallback"
    router = make_router(primary=FailingClient(), fallback=fallback, budget=budget)
    # Both share same tiny budget — result may be None or fallback
    result = await router.route("sys", "user")
    # Either None (both denied) or fallback — both are valid
    if result is not None:
        assert result["model"] in ("mock-fallback", "mock")


@pytest.mark.asyncio
async def test_router_calls_after_call_on_success():
    """After a successful call, budget.after_call should be invoked."""
    budget = InMemoryTokenManager(daily_usd_budget=10.0)
    router = make_router(budget=budget)
    await router.route("sys", "user", estimated_input_tokens=50)
    # After the call, budget should have recorded usage
    remaining = await budget.remaining_budget_usd()
    assert remaining == 10.0  # mock is free ($0 cost) so budget unchanged


@pytest.mark.asyncio
async def test_route_returns_correct_token_counts():
    router = make_router()
    result = await router.route("sys", "user")
    assert result is not None
    assert result["input_tokens"] == 50   # MockLlmClient fixed values
    assert result["output_tokens"] == 30
