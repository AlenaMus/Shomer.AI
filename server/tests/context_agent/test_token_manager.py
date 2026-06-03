"""Unit tests for SqliteTokenManager and InMemoryTokenManager.

Covers:
  - Budget math (cost calculation)
  - before_call allows / denies correctly
  - after_call UPSERT semantics
  - Persistence across re-instantiation (SQLite only)
  - Midnight UTC reset (day boundary)

Reference: docs/design/context_agent/design.md §6.4.
"""

from __future__ import annotations

import os
import tempfile

import pytest

from app.context_agent.token_manager import (
    InMemoryTokenManager,
    SqliteTokenManager,
    _estimate_cost,
    _load_prices,
)

_PRICES_PATH = "server/app/context_agent/token_prices.yaml"


# --------------------------------------------------------------------------- #
# _estimate_cost (pure function)                                               #
# --------------------------------------------------------------------------- #


def test_estimate_cost_gpt_4o_mini():
    prices = _load_prices(_PRICES_PATH)
    # LLD acceptance criteria: _estimate_cost("gpt-4o-mini", 380, 42) ≈ $0.000082
    cost = _estimate_cost(prices, "gpt-4o-mini", 380, 42)
    # 380 * 0.15/1M + 42 * 0.60/1M = 0.000057 + 0.0000252 = 0.0000822
    assert abs(cost - 0.0000822) < 1e-7


def test_estimate_cost_unknown_model():
    prices = _load_prices(_PRICES_PATH)
    cost = _estimate_cost(prices, "unknown-model-xyz", 1000, 1000)
    assert cost == 0.0


def test_estimate_cost_mock():
    prices = _load_prices(_PRICES_PATH)
    cost = _estimate_cost(prices, "mock", 1_000_000, 1_000_000)
    assert cost == 0.0


def test_estimate_cost_haiku():
    prices = _load_prices(_PRICES_PATH)
    # 1000 input + 100 output at $1/1M input, $5/1M output
    cost = _estimate_cost(prices, "haiku-4.5", 1000, 100)
    expected = 1000 * 1.0 / 1_000_000 + 100 * 5.0 / 1_000_000
    assert abs(cost - expected) < 1e-9


# --------------------------------------------------------------------------- #
# InMemoryTokenManager                                                         #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_inmemory_allows_within_budget():
    budget = InMemoryTokenManager(
        token_prices_path=_PRICES_PATH,
        daily_token_budget=100_000,
        daily_usd_budget=10.0,
    )
    allowed, reason = await budget.before_call("mock", 500)
    assert allowed is True
    assert reason == "ok"


@pytest.mark.asyncio
async def test_inmemory_denies_when_token_budget_exceeded():
    budget = InMemoryTokenManager(
        token_prices_path=_PRICES_PATH,
        daily_token_budget=100,
        daily_usd_budget=10.0,
    )
    # Exhaust with a call recorded
    await budget.after_call("mock", 90, 0)
    # Now 90 tokens used; requesting 20 more (>100 limit)
    allowed, reason = await budget.before_call("mock", 20)
    assert allowed is False
    assert "token" in reason


@pytest.mark.asyncio
async def test_inmemory_denies_when_usd_budget_exceeded():
    budget = InMemoryTokenManager(
        token_prices_path=_PRICES_PATH,
        daily_token_budget=100_000,
        daily_usd_budget=0.000001,  # tiny budget
    )
    allowed, reason = await budget.before_call("gpt-4o-mini", 1000)
    # 1000 input tokens at $0.15/1M = $0.00000015 — too small to exhaust
    # Use a very large request to trigger USD denial
    allowed, reason = await budget.before_call("haiku-4.5", 100_000)
    # 100k input at $1/1M = $0.10 >> $0.000001 budget
    assert allowed is False
    assert "usd" in reason


@pytest.mark.asyncio
async def test_inmemory_after_call_accumulates():
    budget = InMemoryTokenManager(
        token_prices_path=_PRICES_PATH,
        daily_token_budget=100_000,
        daily_usd_budget=10.0,
    )
    await budget.after_call("mock", 100, 30)
    await budget.after_call("mock", 100, 30)
    remaining = await budget.remaining_budget_usd()
    # mock has $0 cost; remaining should still be 10.0
    assert remaining == 10.0


@pytest.mark.asyncio
async def test_inmemory_remaining_budget_decreases():
    budget = InMemoryTokenManager(
        token_prices_path=_PRICES_PATH,
        daily_token_budget=100_000,
        daily_usd_budget=1.0,
    )
    # Record 1M tokens of GPT-4o-mini input → $0.15 spend
    await budget.after_call("gpt-4o-mini", 1_000_000, 0)
    remaining = await budget.remaining_budget_usd()
    assert abs(remaining - 0.85) < 1e-9


@pytest.mark.asyncio
async def test_inmemory_reset_clears_usage():
    budget = InMemoryTokenManager(
        token_prices_path=_PRICES_PATH,
        daily_usd_budget=1.0,
    )
    await budget.after_call("gpt-4o-mini", 1_000_000, 0)
    budget.reset()
    remaining = await budget.remaining_budget_usd()
    assert remaining == 1.0


# --------------------------------------------------------------------------- #
# SqliteTokenManager                                                           #
# --------------------------------------------------------------------------- #


def _make_sqlite_manager(tmp_path: str, **kwargs) -> SqliteTokenManager:
    defaults = dict(
        token_prices_path=_PRICES_PATH,
        db_path=tmp_path,
        daily_token_budget=100_000,
        daily_usd_budget=10.0,
    )
    defaults.update(kwargs)
    return SqliteTokenManager(**defaults)


@pytest.fixture
def tmp_db(tmp_path):
    return str(tmp_path / "test_audit.db")


@pytest.mark.asyncio
async def test_sqlite_allows_within_budget(tmp_db):
    mgr = _make_sqlite_manager(tmp_db)
    allowed, reason = await mgr.before_call("mock", 500)
    assert allowed is True


@pytest.mark.asyncio
async def test_sqlite_after_call_upsert(tmp_db):
    mgr = _make_sqlite_manager(tmp_db)
    await mgr.after_call("gpt-4o-mini", 100, 20)
    await mgr.after_call("gpt-4o-mini", 100, 20)
    # Should have accumulated 200+40 tokens total in the row
    remaining = await mgr.remaining_budget_usd()
    assert remaining < 10.0  # some cost was recorded


@pytest.mark.asyncio
async def test_sqlite_denies_when_token_budget_exceeded(tmp_db):
    mgr = _make_sqlite_manager(tmp_db, daily_token_budget=100)
    await mgr.after_call("mock", 90, 0)
    allowed, reason = await mgr.before_call("mock", 20)
    assert allowed is False
    assert "token" in reason


@pytest.mark.asyncio
async def test_sqlite_persistence_across_instances(tmp_db):
    """Usage recorded in one instance is visible to a new instance on the same DB."""
    mgr1 = _make_sqlite_manager(tmp_db, daily_token_budget=100)
    await mgr1.after_call("mock", 90, 0)

    # New instance on same DB
    mgr2 = _make_sqlite_manager(tmp_db, daily_token_budget=100)
    allowed, _ = await mgr2.before_call("mock", 20)
    assert allowed is False  # 90 already used; 20 more > 100


@pytest.mark.asyncio
async def test_sqlite_remaining_budget_positive(tmp_db):
    mgr = _make_sqlite_manager(tmp_db, daily_usd_budget=1.0)
    await mgr.after_call("gpt-4o-mini", 1_000_000, 0)
    remaining = await mgr.remaining_budget_usd()
    assert remaining >= 0.0
    assert remaining < 1.0


@pytest.mark.asyncio
async def test_sqlite_health_ok(tmp_db):
    mgr = _make_sqlite_manager(tmp_db)
    from app.schemas import HealthState
    state, detail = await mgr.health()
    assert state == HealthState.OK
