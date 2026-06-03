"""LlmContextAgent — main ContextReasoner implementation.

Orchestrates:
  1. Tool calls (deterministic, pre-LLM): read_history, lookup_slang, check_age
  2. Budget check via TokenBudgetGuard
  3. LLM call via LlmRouter (primary → fallback)
  4. Output parsing + validation
  5. Prometheus metrics + structured logging
  6. Returns ContextDecision (NEVER raises)

Reference: docs/design/context_agent/design.md §3.2, §4.1–4.4, §8.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..audit_log.protocol import AuditStore

from ..schemas import ClassificationResult, ContextDecision, HealthState
from .logging import (
    EVT_AGENT_COMPLETE,
    EVT_AGENT_ERROR,
    EVT_AGENT_START,
    EVT_BUDGET_DENIED,
    EVT_LLM_FALLBACK,
    EVT_TOOL_CALLED,
    get_logger,
)
from .metrics import (
    context_agent_error_total,
    context_agent_invocations_total,
    context_agent_latency_seconds,
    context_agent_threat_decision_total,
    context_agent_tool_calls_total,
)
from .output_parser import parse_llm_output
from .prompt import build_system_prompt, build_user_prompt

logger = get_logger()

# Rough token estimate for the assembled prompt — used for budget pre-check
_ESTIMATED_PROMPT_TOKENS = 400


class LlmContextAgent:
    """Implements the ``ContextReasoner`` Protocol via LLM + tool calls.

    Constructor-injected dependencies (all typed by Protocol):
      - ``primary``   — LlmClient (e.g. OpenAiClient or MockLlmClient)
      - ``fallback``  — LlmClient (e.g. AnthropicClient or MockLlmClient)
      - ``budget``    — TokenBudgetGuard (SqliteTokenManager or InMemoryTokenManager)
      - ``audit_store`` — AuditStore (for read_history tool + history lookup)
      - ``slang_lexicon_path`` — path to slang_lexicon.json
      - ``timeout_s`` — per-call timeout (default 5.0 s per PRD §8.3)
      - ``max_history_turns`` — how many prior turns to fetch (default 5)
    """

    def __init__(
        self,
        primary,    # LlmClient
        fallback,   # LlmClient
        budget,     # TokenBudgetGuard
        audit_store: "AuditStore",
        slang_lexicon_path: str = "server/data/slang_lexicon.json",
        timeout_s: float = 5.0,
        max_history_turns: int = 5,
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._budget = budget
        self._audit_store = audit_store
        self._timeout_s = timeout_s
        self._max_history_turns = max_history_turns

        # Import tools here (lazy) to avoid circular at module level
        from .tools.read_history import ReadHistoryTool
        from .tools.lookup_slang import LookupSlangTool
        from .tools.check_age import CheckAgeAppropriatenessTool
        from .llm_router import LlmRouter

        self._read_history_tool = ReadHistoryTool(audit_store)
        self._lookup_slang_tool = LookupSlangTool(slang_lexicon_path)
        self._check_age_tool = CheckAgeAppropriatenessTool()
        self._router = LlmRouter(primary, fallback, budget, timeout_s)

    # ------------------------------------------------------------------ #
    # ContextReasoner Protocol                                             #
    # ------------------------------------------------------------------ #

    async def evaluate(
        self,
        text: str,
        classifier_result: ClassificationResult,
        child_id: str | None = None,
        trace_id: str | None = None,
        child_age: int = 13,
    ) -> ContextDecision:
        """Evaluate a borderline classification. NEVER raises.

        Returns ``ContextDecision(review_flag=True)`` on any failure.
        """
        t0 = time.perf_counter()
        _tid = trace_id or "no-trace"

        logger.info(EVT_AGENT_START, trace_id=_tid, child_id=child_id)

        try:
            return await self._evaluate_inner(
                text, classifier_result, child_id, _tid, child_age, t0
            )
        except Exception as exc:
            latency_ms = (time.perf_counter() - t0) * 1000
            logger.error(EVT_AGENT_ERROR, trace_id=_tid, error=str(exc), latency_ms=latency_ms)
            context_agent_error_total.labels(error_type="unexpected").inc()
            context_agent_invocations_total.labels(outcome="llm_failed").inc()
            return self._fallback_decision(classifier_result, latency_ms)

    async def health(self) -> tuple[HealthState, str]:
        try:
            ph, _ = await self._primary.health()
            fh, _ = await self._fallback.health()
            if ph == HealthState.OK or fh == HealthState.OK:
                return (HealthState.OK, "at least one LLM provider healthy")
            return (HealthState.DEGRADED, "all LLM providers degraded")
        except Exception as exc:
            return (HealthState.DOWN, str(exc))

    # ------------------------------------------------------------------ #
    # Internal orchestration                                               #
    # ------------------------------------------------------------------ #

    async def _evaluate_inner(
        self,
        text: str,
        classifier_result: ClassificationResult,
        child_id: str | None,
        trace_id: str,
        child_age: int,
        t0: float,
    ) -> ContextDecision:

        # --- Step 1: Run tools deterministically (pre-LLM) --------------- #
        tools_called: list[str] = []

        history_result = await self._read_history_tool.run(
            {"child_id": child_id or "", "last_n_turns": self._max_history_turns}
        )
        tools_called.append(self._read_history_tool.name)
        context_agent_tool_calls_total.labels(tool=self._read_history_tool.name).inc()
        logger.debug(EVT_TOOL_CALLED, trace_id=trace_id, tool=self._read_history_tool.name)

        slang_result = await self._lookup_slang_tool.run({"text": text})
        tools_called.append(self._lookup_slang_tool.name)
        context_agent_tool_calls_total.labels(tool=self._lookup_slang_tool.name).inc()
        logger.debug(EVT_TOOL_CALLED, trace_id=trace_id, tool=self._lookup_slang_tool.name)

        age_result = await self._check_age_tool.run({"child_age": child_age})
        tools_called.append(self._check_age_tool.name)
        context_agent_tool_calls_total.labels(tool=self._check_age_tool.name).inc()
        logger.debug(EVT_TOOL_CALLED, trace_id=trace_id, tool=self._check_age_tool.name)

        # Convert history turns to dicts for the prompt builder
        history_turns = history_result.get("result", {}).get("turns", [])

        # --- Step 2: Budget pre-check ------------------------------------ #
        allowed, reason = await self._budget.before_call(
            self._primary.model_name, _ESTIMATED_PROMPT_TOKENS
        )
        if not allowed:
            latency_ms = (time.perf_counter() - t0) * 1000
            logger.warning(
                EVT_BUDGET_DENIED,
                trace_id=trace_id,
                reason=reason,
                latency_ms=latency_ms,
            )
            context_agent_error_total.labels(error_type="budget_exhausted").inc()
            context_agent_invocations_total.labels(outcome="budget_exhausted").inc()
            return ContextDecision(
                is_real_threat=classifier_result.is_offensive,
                severity="low",
                explanation="תקציב יומי מוצה — נדרשת בדיקה ידנית",
                review_flag=True,
                model_used=None,
                latency_ms=latency_ms,
                tools_called=tuple(tools_called),
            )

        # --- Step 3: Build prompt ---------------------------------------- #
        system_prompt = build_system_prompt()
        user_prompt = build_user_prompt(
            text=text,
            classifier_result=classifier_result,
            conversation_history=history_turns,
            slang_hits=slang_result.get("result", {}),
            age_info=age_result.get("result", {}),
            child_age=child_age,
        )

        # --- Step 4: LLM call (primary → fallback via router) ------------ #
        llm_result = await self._router.route(
            system_prompt,
            user_prompt,
            max_tokens=512,
            temperature=0.2,
            estimated_input_tokens=_ESTIMATED_PROMPT_TOKENS,
        )

        if llm_result is None:
            latency_ms = (time.perf_counter() - t0) * 1000
            logger.warning(
                EVT_LLM_FALLBACK,
                trace_id=trace_id,
                reason="all_llms_failed",
                latency_ms=latency_ms,
                review_flag=True,
            )
            context_agent_error_total.labels(error_type="api_error").inc()
            context_agent_invocations_total.labels(outcome="llm_failed").inc()
            return self._fallback_decision(classifier_result, latency_ms, tools_called)

        # --- Step 5: Parse output ---------------------------------------- #
        parsed, parse_ok = parse_llm_output(llm_result["text"])
        if not parse_ok:
            context_agent_error_total.labels(error_type="parse_error").inc()

        latency_ms = (time.perf_counter() - t0) * 1000
        model_used = llm_result["model"]

        # --- Step 6: Metrics + logging ------------------------------------ #
        context_agent_latency_seconds.labels(model=model_used).observe(latency_ms / 1000)
        outcome = "real_threat" if parsed.is_real_threat else "not_threat"
        context_agent_invocations_total.labels(outcome=outcome).inc()
        context_agent_threat_decision_total.labels(
            decision="real_threat" if parsed.is_real_threat else "not_threat"
        ).inc()

        logger.info(
            EVT_AGENT_COMPLETE,
            trace_id=trace_id,
            model_used=model_used,
            is_real_threat=parsed.is_real_threat,
            latency_ms=latency_ms,
            tokens_in=llm_result["input_tokens"],
            tokens_out=llm_result["output_tokens"],
            context_used=bool(history_turns),
            tools_called=tools_called,
        )

        return ContextDecision(
            is_real_threat=parsed.is_real_threat,
            severity=parsed.severity,
            explanation=parsed.explanation,
            review_flag=not parse_ok,  # flag for review if parse failed
            tokens_input=llm_result["input_tokens"],
            tokens_output=llm_result["output_tokens"],
            model_used=model_used,
            reasoning_trace=parsed.reasoning,
            tools_called=tuple(tools_called),
            latency_ms=latency_ms,
        )

    # ------------------------------------------------------------------ #
    # Fallback constructors                                                #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _fallback_decision(
        classifier_result: ClassificationResult,
        latency_ms: float,
        tools_called: list[str] | None = None,
    ) -> ContextDecision:
        """Build a safe-default ContextDecision for any failure path.

        Safety invariant: ``is_real_threat`` follows the frontline result —
        we never silently downgrade a potential threat.
        """
        return ContextDecision(
            is_real_threat=classifier_result.is_offensive,
            severity="low",
            explanation="שגיאה בניתוח ההקשר — נדרשת בדיקה ידנית",
            review_flag=True,
            model_used=None,
            latency_ms=latency_ms,
            tools_called=tuple(tools_called or []),
        )
