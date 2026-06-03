"""AnthropicClient — LlmClient adapter wrapping the anthropic Python SDK.

Model: claude-haiku-4-5-20251001 (Haiku 4.5).
System prompt goes in the ``system`` parameter (not in messages).
Raises on any SDK exception; ``LlmRouter`` catches and routes appropriately.

Reference: docs/design/context_agent/design.md §3.2 (LlmRouter).
"""

from __future__ import annotations

try:
    import anthropic
    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _ANTHROPIC_AVAILABLE = False

from ...schemas import HealthState
from ..protocol import LlmCallResult

# The exact Anthropic API model ID (LLD open question Q7 answered)
_MODEL_API = "claude-haiku-4-5-20251001"
_MODEL_LABEL = "haiku-4.5"


class AnthropicClient:
    """Async Anthropic client; satisfies ``LlmClient`` Protocol."""

    model_name: str = _MODEL_LABEL

    def __init__(self, api_key: str) -> None:
        if not _ANTHROPIC_AVAILABLE:
            raise ImportError(
                "anthropic package is not installed. Run: pip install anthropic>=0.39.0"
            )
        self._client = anthropic.AsyncAnthropic(api_key=api_key)

    async def reason(
        self,
        system: str,
        user: str,
        max_tokens: int = 512,
        temperature: float = 0.2,
    ) -> LlmCallResult:
        """Call Claude Haiku 4.5 and return the result."""
        response = await self._client.messages.create(
            model=_MODEL_API,
            system=system,
            messages=[{"role": "user", "content": user}],
            max_tokens=max_tokens,
            temperature=temperature,
        )
        text = response.content[0].text if response.content else ""
        return LlmCallResult(
            text=text,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            model=_MODEL_LABEL,
        )

    async def health(self) -> tuple[HealthState, str]:
        try:
            # Lightweight check — list available models
            await self._client.models.list()
            return (HealthState.OK, "anthropic api reachable")
        except Exception as exc:
            return (HealthState.DEGRADED, f"anthropic api unreachable: {exc}")
