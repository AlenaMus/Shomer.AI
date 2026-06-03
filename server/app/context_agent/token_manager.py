"""TokenManager implementations for the context_agent module.

Two concrete adapters for the TokenBudgetGuard Protocol
(defined in protocol.py):

  - ``SqliteTokenManager`` — persists token usage to SQLite; restart-safe.
  - ``InMemoryTokenManager`` — ephemeral; for tests and dev.

Both share the same ``_estimate_cost()`` calculation loaded from
``token_prices.yaml``.

Reference: docs/design/context_agent/design.md §6.4.
"""

from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Union

import yaml

from .metrics import (
    context_agent_budget_remaining_usd,
    context_agent_tokens_used_total,
    context_agent_usd_spent_total,
)

try:
    import structlog
    _logger = structlog.get_logger("shomer.context_agent.token_manager")
except Exception:
    import logging
    _logger = logging.getLogger("shomer.context_agent.token_manager")  # type: ignore[assignment]

# --------------------------------------------------------------------------- #
# Return types (LLD §6.4 Protocol section)                                    #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Allowed:
    """Budget check passed — caller may proceed with the LLM call."""
    estimated_cost_usd: float


@dataclass(frozen=True)
class DeniedBudgetExhausted:
    """Budget check failed — caller must fall back to frontline-only."""
    reason: str           # "daily_token_budget_exceeded" | "daily_usd_budget_exceeded"
    current_usd: float
    budget_usd: float
    reset_at_utc: str     # ISO 8601 midnight UTC


BudgetDecision = Union[Allowed, DeniedBudgetExhausted]


# --------------------------------------------------------------------------- #
# Shared helpers                                                               #
# --------------------------------------------------------------------------- #

def _next_midnight_utc() -> str:
    """Return ISO-8601 string for next midnight UTC."""
    now = datetime.now(timezone.utc)
    next_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    # If it's already past midnight, add a day
    if next_day <= now:
        from datetime import timedelta
        next_day = next_day + timedelta(days=1)
    return next_day.isoformat()


def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _load_prices(token_prices_path: str) -> dict:
    """Load token price table from YAML. Returns empty dict on failure."""
    path = Path(token_prices_path)
    if not path.exists():
        _logger.warning(
            "token_prices_missing",
            path=str(path),
            detail="All cost estimates will be 0.0",
        )
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _estimate_cost(prices: dict, model: str, input_tokens: int, output_tokens: int) -> float:
    """Calculate USD cost from the loaded price table.

    Unknown model → 0.0 (never raises — per LLD §6.4 acceptance criteria).
    """
    p = prices.get(model, {})
    in_rate = p.get("input_per_1m_tokens_usd", 0.0) / 1_000_000
    out_rate = p.get("output_per_1m_tokens_usd", 0.0) / 1_000_000
    return input_tokens * in_rate + output_tokens * out_rate


# --------------------------------------------------------------------------- #
# SqliteTokenManager                                                           #
# --------------------------------------------------------------------------- #

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS token_usage (
    day            TEXT    NOT NULL,
    model          TEXT    NOT NULL,
    input_tokens   INTEGER NOT NULL DEFAULT 0,
    output_tokens  INTEGER NOT NULL DEFAULT 0,
    usd_spent      REAL    NOT NULL DEFAULT 0.0,
    PRIMARY KEY (day, model)
)
"""


class SqliteTokenManager:
    """SQLite-backed daily token + USD budget enforcement.

    Satisfies the ``TokenBudgetGuard`` Protocol.

    Thread safety: asyncio.Lock serialises concurrent before_call / after_call
    calls within the same process. SQLite write-locking handles concurrent
    processes (e.g. restarted server).

    The ``token_usage`` table is created at construction time and shares the
    same ``audit.db`` file as the audit log module (they use separate tables).
    """

    def __init__(
        self,
        token_prices_path: str,
        db_path: str,
        daily_token_budget: int,
        daily_usd_budget: float,
    ) -> None:
        self._db_path = db_path
        self._daily_token_budget = daily_token_budget
        self._daily_usd_budget = daily_usd_budget
        self._prices = _load_prices(token_prices_path)
        self._lock = asyncio.Lock()
        self._ensure_schema()

        # Initialise the remaining-budget gauge from today's existing data
        today = _today_utc()
        _, today_usd = self._daily_totals(today)
        context_agent_budget_remaining_usd.set(
            max(0.0, daily_usd_budget - today_usd)
        )

    # ------------------------------------------------------------------ #
    # Schema                                                               #
    # ------------------------------------------------------------------ #

    def _ensure_schema(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute(_CREATE_TABLE)
            conn.commit()

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _daily_totals(self, day: str) -> tuple[int, float]:
        """Return (total_tokens, total_usd) for the given day from SQLite."""
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                "SELECT SUM(input_tokens + output_tokens), SUM(usd_spent) "
                "FROM token_usage WHERE day = ?",
                (day,),
            ).fetchone()
        tokens = row[0] or 0
        usd = row[1] or 0.0
        return tokens, usd

    def _estimate(self, model: str, input_tokens: int, output_tokens: int = 0) -> float:
        return _estimate_cost(self._prices, model, input_tokens, output_tokens)

    # ------------------------------------------------------------------ #
    # TokenBudgetGuard Protocol                                            #
    # ------------------------------------------------------------------ #

    async def before_call(
        self,
        model: str,
        estimated_input_tokens: int,
    ) -> tuple[bool, str]:
        """Decide whether the call is within budget.

        Returns (allowed: bool, reason: str).
        """
        async with self._lock:
            today = _today_utc()
            total_tokens, total_usd = self._daily_totals(today)
            estimated_cost = self._estimate(model, estimated_input_tokens)

            if total_tokens + estimated_input_tokens > self._daily_token_budget:
                _logger.warning(
                    "budget_denied",
                    reason="daily_token_budget_exceeded",
                    total_tokens=total_tokens,
                    budget=self._daily_token_budget,
                )
                return (False, "daily_token_budget_exceeded")

            if total_usd + estimated_cost > self._daily_usd_budget:
                _logger.warning(
                    "budget_denied",
                    reason="daily_usd_budget_exceeded",
                    total_usd=total_usd,
                    budget=self._daily_usd_budget,
                )
                return (False, "daily_usd_budget_exceeded")

            return (True, "ok")

    async def after_call(
        self,
        model: str,
        actual_input_tokens: int,
        actual_output_tokens: int,
    ) -> None:
        """Record actual usage; update SQLite and Prometheus."""
        async with self._lock:
            today = _today_utc()
            cost = self._estimate(model, actual_input_tokens, actual_output_tokens)

            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO token_usage (day, model, input_tokens, output_tokens, usd_spent)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(day, model) DO UPDATE SET
                        input_tokens  = input_tokens  + excluded.input_tokens,
                        output_tokens = output_tokens + excluded.output_tokens,
                        usd_spent     = usd_spent     + excluded.usd_spent
                    """,
                    (today, model, actual_input_tokens, actual_output_tokens, cost),
                )
                conn.commit()

            # Prometheus metrics — updated atomically with the DB write
            context_agent_tokens_used_total.labels(model=model, kind="input").inc(
                actual_input_tokens
            )
            context_agent_tokens_used_total.labels(model=model, kind="output").inc(
                actual_output_tokens
            )
            context_agent_usd_spent_total.labels(model=model).inc(cost)

            # Refresh remaining budget gauge
            _, today_usd = self._daily_totals(today)
            context_agent_budget_remaining_usd.set(
                max(0.0, self._daily_usd_budget - today_usd)
            )

            _logger.info(
                "token_usage_recorded",
                model=model,
                input_tokens=actual_input_tokens,
                output_tokens=actual_output_tokens,
                cost_usd=cost,
                day=today,
            )

    async def remaining_budget_usd(self) -> float:
        """Return remaining daily USD budget (read-only helper)."""
        _, today_usd = self._daily_totals(_today_utc())
        return max(0.0, self._daily_usd_budget - today_usd)

    async def health(self):
        try:
            self._daily_totals(_today_utc())
            from ..schemas import HealthState
            return (HealthState.OK, "sqlite token_usage ok")
        except Exception as exc:
            from ..schemas import HealthState
            return (HealthState.DOWN, str(exc))


# --------------------------------------------------------------------------- #
# InMemoryTokenManager                                                         #
# --------------------------------------------------------------------------- #


class InMemoryTokenManager:
    """Ephemeral in-memory token budget guard.

    Satisfies the ``TokenBudgetGuard`` Protocol.
    Resets when the process restarts (or when ``reset()`` is called in tests).
    """

    def __init__(
        self,
        token_prices_path: str = "server/app/context_agent/token_prices.yaml",
        daily_token_budget: int = 100_000,
        daily_usd_budget: float = 0.50,
    ) -> None:
        self._daily_token_budget = daily_token_budget
        self._daily_usd_budget = daily_usd_budget
        self._prices = _load_prices(token_prices_path)
        self._lock = asyncio.Lock()
        # day → {model → (input_tokens, output_tokens, usd)}
        self._usage: dict[str, dict[str, tuple[int, int, float]]] = {}

    # ------------------------------------------------------------------ #
    # Test helper                                                          #
    # ------------------------------------------------------------------ #

    def reset(self) -> None:
        """Clear all accumulated usage — convenience for tests."""
        self._usage.clear()

    # ------------------------------------------------------------------ #
    # Internal                                                             #
    # ------------------------------------------------------------------ #

    def _daily_totals(self, day: str) -> tuple[int, float]:
        day_data = self._usage.get(day, {})
        total_tokens = sum(v[0] + v[1] for v in day_data.values())
        total_usd = sum(v[2] for v in day_data.values())
        return total_tokens, total_usd

    def _estimate(self, model: str, input_tokens: int, output_tokens: int = 0) -> float:
        return _estimate_cost(self._prices, model, input_tokens, output_tokens)

    # ------------------------------------------------------------------ #
    # TokenBudgetGuard Protocol                                            #
    # ------------------------------------------------------------------ #

    async def before_call(
        self,
        model: str,
        estimated_input_tokens: int,
    ) -> tuple[bool, str]:
        async with self._lock:
            today = _today_utc()
            total_tokens, total_usd = self._daily_totals(today)
            estimated_cost = self._estimate(model, estimated_input_tokens)

            if total_tokens + estimated_input_tokens > self._daily_token_budget:
                return (False, "daily_token_budget_exceeded")
            if total_usd + estimated_cost > self._daily_usd_budget:
                return (False, "daily_usd_budget_exceeded")
            return (True, "ok")

    async def after_call(
        self,
        model: str,
        actual_input_tokens: int,
        actual_output_tokens: int,
    ) -> None:
        async with self._lock:
            today = _today_utc()
            cost = self._estimate(model, actual_input_tokens, actual_output_tokens)
            day_data = self._usage.setdefault(today, {})
            prev = day_data.get(model, (0, 0, 0.0))
            day_data[model] = (
                prev[0] + actual_input_tokens,
                prev[1] + actual_output_tokens,
                prev[2] + cost,
            )

    async def remaining_budget_usd(self) -> float:
        _, today_usd = self._daily_totals(_today_utc())
        return max(0.0, self._daily_usd_budget - today_usd)

    async def health(self):
        from ..schemas import HealthState
        return (HealthState.OK, "in-memory token manager ok")
