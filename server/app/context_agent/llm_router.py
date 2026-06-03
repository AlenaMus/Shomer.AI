"""LlmRouter — primary-to-fallback LLM routing with budget enforcement.

Flow (LLD §3.2):
  1. Check budget via ``TokenBudgetGuard.before_call(primary)``.
  2. If denied → skip primary, try same check for fallback.
  3. Try primary with ``asyncio.wait_for(timeout)``.
  4. On failure → try fallback.
  5. On both failure → return ``None``.
  6. On success → call ``budget.after_call()``, return ``LlmCallResult``.

The router itself satisfies the ``LlmClient`` Protocol from the *caller's*
perspective — it exposes ``reason()`` and ``model_name``.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .protocol import LlmClient, LlmCallResult, TokenBudgetGuard

try:
    import structlog
    _logger = structlog.get_logger("shomer.context_agent.llm_router")
except Exception:
    import logging
    _logger = logging.getLogger("shomer.context_agent.llm_router")  # type: ignore[assignment]

from .metrics import context_agent_llm_fallback_total


class LlmRouter:
    """Routes LLM calls through primary → fallback with budget enforcement.

    Returns ``None`` when both providers are unavailable or budget is exhausted
    for both. The caller (``LlmContextAgent``) interprets ``None`` as a signal
    to return ``ContextDecision(review_flag=True)``.
    """

    model_name = "router"

    def __init__(
        self,
        primary: "LlmClient",
        fallback: "LlmClient",
        budget: "TokenBudgetGuard",
        timeout_s: float = 5.0,
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._budget = budget
        self._timeout_s = timeout_s

    async def route(
        self,
        system: str,
        user: str,
        max_tokens: int = 512,
        temperature: float = 0.2,
        estimated_input_tokens: int = 400,
    ) -> "LlmCallResult | None":
        """Try primary then fallback. Returns None if both fail or budget exhausted."""

        # --- Try primary ------------------------------------------------- #
        allowed, reason = await self._budget.before_call(
            self._primary.model_name, estimated_input_tokens
        )
        if allowed:
            try:
                result = await asyncio.wait_for(
                    self._primary.reason(system, user, max_tokens, temperature),
                    timeout=self._timeout_s,
                )
                await self._budget.after_call(
                    self._primary.model_name,
                    result["input_tokens"],
                    result["output_tokens"],
                )
                return result
            except Exception as primary_exc:
                _logger.warning(
                    "llm_primary_failed",
                    model=self._primary.model_name,
                    error=str(primary_exc),
                    fallback=self._fallback.model_name,
                )
                context_agent_llm_fallback_total.inc()
        else:
            _logger.warning(
                "llm_primary_budget_denied",
                model=self._primary.model_name,
                reason=reason,
            )
            context_agent_llm_fallback_total.inc()

        # --- Try fallback ------------------------------------------------- #
        allowed_fb, reason_fb = await self._budget.before_call(
            self._fallback.model_name, estimated_input_tokens
        )
        if not allowed_fb:
            _logger.warning(
                "llm_fallback_budget_denied",
                model=self._fallback.model_name,
                reason=reason_fb,
            )
            return None

        try:
            result = await asyncio.wait_for(
                self._fallback.reason(system, user, max_tokens, temperature),
                timeout=self._timeout_s,
            )
            await self._budget.after_call(
                self._fallback.model_name,
                result["input_tokens"],
                result["output_tokens"],
            )
            return result
        except Exception as fallback_exc:
            _logger.error(
                "llm_fallback_failed",
                model=self._fallback.model_name,
                error=str(fallback_exc),
            )
            return None

    async def reason(
        self,
        system: str,
        user: str,
        max_tokens: int = 512,
        temperature: float = 0.2,
    ) -> "LlmCallResult":
        """LlmClient-compatible shim. Raises RuntimeError if both fail."""
        result = await self.route(system, user, max_tokens, temperature)
        if result is None:
            raise RuntimeError("All LLM providers failed or budget exhausted")
        return result

    async def health(self):
        from ..schemas import HealthState
        ph, _ = await self._primary.health()
        fh, _ = await self._fallback.health()
        if ph == HealthState.OK or fh == HealthState.OK:
            return (HealthState.OK, "at least one LLM healthy")
        return (HealthState.DEGRADED, "all LLM providers degraded")
