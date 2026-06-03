"""Structured logger for the context_agent module.

Usage::

    from app.context_agent.logging import get_logger
    logger = get_logger()
    logger.info("agent_complete", trace_id=trace_id, latency_ms=42.0)

All context_agent log records share:
  - ``module = "context_agent"``
  - ``event`` ∈ {agent_start, tool_called, llm_call, llm_fallback,
                  budget_denied, agent_complete, agent_error}

Reference: docs/design/context_agent/design.md §6.1.
"""

from __future__ import annotations

import structlog

_MODULE = "context_agent"

# Event name constants (typed so callers don't typo them)
EVT_AGENT_START = "agent_start"
EVT_TOOL_CALLED = "tool_called"
EVT_LLM_CALL = "llm_call"
EVT_LLM_FALLBACK = "llm_fallback"
EVT_BUDGET_DENIED = "budget_denied"
EVT_AGENT_COMPLETE = "agent_complete"
EVT_AGENT_ERROR = "agent_error"


def get_logger() -> structlog.BoundLogger:
    """Return a structlog logger pre-bound with ``module=context_agent``."""
    return structlog.get_logger(_MODULE).bind(module=_MODULE)
