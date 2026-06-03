"""Prometheus metrics for the context_agent module.

All metrics are registered against the default prometheus_client REGISTRY.
Imported once at module load; subsequent imports reuse the same instances.

Reference: docs/design/context_agent/design.md §6.3 + §6.4.
"""

from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

# ── Main agent metrics ──────────────────────────────────────────────────── #

context_agent_invocations_total = Counter(
    "context_agent_invocations_total",
    "Total context agent invocations by outcome.",
    ["outcome"],  # real_threat | not_threat | review_needed | budget_exhausted | llm_failed
)

context_agent_latency_seconds = Histogram(
    "context_agent_latency_seconds",
    "End-to-end latency of ContextAgent.evaluate() per model used.",
    ["model"],
    buckets=[0.1, 0.25, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 7.5, 10.0],
)

context_agent_threat_decision_total = Counter(
    "context_agent_threat_decision_total",
    "Final threat decisions — tracks how often CA reverses frontline.",
    ["decision"],  # real_threat | not_threat
)

# ── LLM failover ────────────────────────────────────────────────────────── #

context_agent_llm_fallback_total = Counter(
    "context_agent_llm_fallback_total",
    "Number of times the primary LLM failed and the fallback was used.",
    [],
)

# ── Tool usage ───────────────────────────────────────────────────────────── #

context_agent_tool_calls_total = Counter(
    "context_agent_tool_calls_total",
    "Number of tool invocations by tool name.",
    ["tool"],  # read_history | lookup_slang | check_age
)

# ── TokenManager metrics ─────────────────────────────────────────────────── #

context_agent_tokens_used_total = Counter(
    "context_agent_tokens_used_total",
    "Cumulative LLM tokens consumed, by model and direction.",
    ["model", "kind"],  # kind: input | output
)

context_agent_usd_spent_total = Counter(
    "context_agent_usd_spent_total",
    "Cumulative USD spent on LLM calls, by model.",
    ["model"],
)

context_agent_budget_remaining_usd = Gauge(
    "context_agent_budget_remaining_usd",
    "Remaining daily USD budget (updated after every LLM call).",
)

# ── Error counters ───────────────────────────────────────────────────────── #

context_agent_error_total = Counter(
    "context_agent_error_total",
    "Context agent errors by error type.",
    ["error_type"],  # timeout | api_error | parse_error | budget_exhausted
)
