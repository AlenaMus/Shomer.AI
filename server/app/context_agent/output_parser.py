"""LLM JSON output parser for the context_agent module.

Validates the JSON string returned by the LLM against ``AgentLlmResponse``.
On any parse / validation failure returns a *safe default* — never silently
suppresses a potential threat.

Reference: docs/design/context_agent/design.md §7.3.
"""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, field_validator

try:
    import structlog
    _logger = structlog.get_logger("shomer.context_agent.output_parser")
except Exception:
    import logging
    _logger = logging.getLogger("shomer.context_agent.output_parser")  # type: ignore[assignment]


class AgentLlmResponse(BaseModel):
    """Pydantic model that mirrors the JSON schema the LLM is asked to emit.

    All fields have safe defaults so that a partial JSON response can be
    coerced into a usable result — but ``is_real_threat=True`` is the default
    to ensure we never silently drop a real threat due to a parse error.
    """

    is_real_threat: bool = True
    severity: Literal["none", "low", "medium", "high"] = "low"
    explanation: str = "לא ניתן לנתח — נדרשת בדיקה ידנית"
    reasoning: str = ""

    @field_validator("explanation")
    @classmethod
    def explanation_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("explanation must not be empty")
        return v


def _extract_json(raw: str) -> str:
    """Pull the JSON object out of an LLM reply.

    Providers that don't honour a strict json_object response format (e.g.
    Anthropic) wrap the JSON in a ```json ... ``` markdown fence or add prose
    around it. Strip the fence, then fall back to the outermost ``{ ... }``.
    """
    s = raw.strip()
    if s.startswith("```"):
        # drop the opening fence line (``` or ```json) and the closing fence
        s = s.split("\n", 1)[1] if "\n" in s else s
        if "```" in s:
            s = s.rsplit("```", 1)[0]
        s = s.strip()
    if not s.startswith("{"):
        i, j = s.find("{"), s.rfind("}")
        if i != -1 and j > i:
            s = s[i:j + 1]
    return s


def parse_llm_output(raw: str) -> tuple[AgentLlmResponse, bool]:
    """Parse and validate the LLM's JSON output.

    Returns ``(AgentLlmResponse, parse_ok)``.  ``parse_ok=False`` means the
    parse failed and the safe default was used.
    """
    try:
        data = json.loads(_extract_json(raw))
        return AgentLlmResponse(**data), True
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        _logger.warning(
            "agent_output_parse_failed",
            error=str(exc),
            raw_truncated=raw[:200],
        )
        # Fail-safe default: escalate, not suppress (LLD §7.3 + §8)
        return (
            AgentLlmResponse(
                is_real_threat=True,
                severity="low",
                explanation="לא ניתן לנתח — נדרשת בדיקה ידנית",
                reasoning=f"parse_error: {exc}",
            ),
            False,
        )
