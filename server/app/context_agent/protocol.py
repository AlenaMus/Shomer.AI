"""Public ports for the Context Agent module.

Reference: docs/design/context_agent/design.md §2.5.

Three ports for swappability:
  - ``ContextReasoner`` — whole-module port. Lets you swap ``LlmContextAgent``
    for a ``RuleBasedReasoner`` without touching server code.
  - ``LlmClient`` — single LLM provider port (Mock / GPT-4o-mini / Haiku 4.5
    / local Qwen). Swappable inside the agent.
  - ``TokenBudgetGuard`` — cost/budget enforcement port (SQLite / in-memory).
"""

from __future__ import annotations

from typing import Protocol, TypedDict, runtime_checkable

from ..schemas import ClassificationResult, ContextDecision, HealthState


class LlmCallResult(TypedDict):
    """What every ``LlmClient.reason()`` adapter returns."""

    text: str
    input_tokens: int
    output_tokens: int
    model: str  # actual model name (e.g. "gpt-4o-mini-2024-07-18")


@runtime_checkable
class ContextReasoner(Protocol):
    """Whole-module port — reasoning over conversation context for borderline cases."""

    async def evaluate(
        self,
        text: str,
        classifier_result: ClassificationResult,
        child_id: str | None = None,
        trace_id: str | None = None,
        child_age: int = 13,
        provided_history: list[dict] | None = None,
    ) -> ContextDecision:
        """Apply context-aware reasoning to a borderline classification.

        Parameters
        ----------
        provided_history:
            When not None, use these turns directly as conversation context
            and skip the ``read_history`` tool call.  Each dict must have
            ``role`` and ``text`` keys.  This is the screenshot path: the
            visible conversation in the screenshot IS the context, so the DB
            store must not be consulted.  When None (text-event path), the
            existing DB-history behaviour is used.

        Contract:
        - NEVER raises. On total failure (every LLM unreachable, budget
          exhausted, etc.) returns ``ContextDecision(review_flag=True, ...)``.
        - p99 latency target: < 3 s (PRD §8.3, §9).
        - Stateless across calls — persistence goes through ``AuditStore``.
        """
        ...

    async def health(self) -> tuple[HealthState, str]: ...


@runtime_checkable
class LlmClient(Protocol):
    """Single-call LLM provider port. Swappable mock/GPT/Haiku/local Qwen."""

    async def reason(
        self,
        system: str,
        user: str,
        max_tokens: int = 512,
        temperature: float = 0.2,
    ) -> LlmCallResult:
        """Return the LLM's reply plus token-usage telemetry."""
        ...

    @property
    def model_name(self) -> str:
        """e.g. ``"gpt-4o-mini"``, ``"haiku-4.5"``, ``"mock"``."""
        ...

    async def health(self) -> tuple[HealthState, str]: ...


@runtime_checkable
class TokenBudgetGuard(Protocol):
    """Daily token + USD budget enforcement.

    Reference: docs/design/context_agent/design.md §6.4 (TokenManager).
    """

    async def before_call(
        self,
        model: str,
        estimated_input_tokens: int,
    ) -> tuple[bool, str]:
        """Decide whether to allow the call.

        Returns ``(allowed, reason)``. ``allowed=False`` → caller falls back to
        frontline-only with ``review_flag=True``. ``reason`` is a one-line
        explanation that lands in the audit row.
        """
        ...

    async def after_call(
        self,
        model: str,
        actual_input_tokens: int,
        actual_output_tokens: int,
    ) -> None:
        """Record actual usage and update the daily counters."""
        ...

    async def remaining_budget_usd(self) -> float:
        """Read-side helper. Used by the ``/health`` rollup and metrics."""
        ...
