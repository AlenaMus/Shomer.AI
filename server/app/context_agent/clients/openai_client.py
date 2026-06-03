"""OpenAiClient — LlmClient adapter wrapping the openai Python SDK.

Model: gpt-4o-mini (json_object response format).
Raises on any SDK exception; ``LlmRouter`` catches and tries fallback.

Reference: docs/design/context_agent/design.md §3.2 (LlmRouter).
"""

from __future__ import annotations

try:
    import openai
    _OPENAI_AVAILABLE = True
except ImportError:
    _OPENAI_AVAILABLE = False

from ...schemas import HealthState
from ..protocol import LlmCallResult

_MODEL = "gpt-4o-mini"


class OpenAiClient:
    """Async OpenAI client; satisfies ``LlmClient`` Protocol."""

    model_name: str = _MODEL

    def __init__(self, api_key: str) -> None:
        if not _OPENAI_AVAILABLE:
            raise ImportError("openai package is not installed. Run: pip install openai>=1.55.0")
        self._client = openai.AsyncOpenAI(api_key=api_key)

    async def reason(
        self,
        system: str,
        user: str,
        max_tokens: int = 512,
        temperature: float = 0.2,
    ) -> LlmCallResult:
        """Call GPT-4o-mini in JSON mode and return the result."""
        response = await self._client.chat.completions.create(
            model=_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
            response_format={"type": "json_object"},
        )
        return LlmCallResult(
            text=response.choices[0].message.content or "",
            input_tokens=response.usage.prompt_tokens,
            output_tokens=response.usage.completion_tokens,
            model=response.model,
        )

    async def health(self) -> tuple[HealthState, str]:
        try:
            # Lightweight reachability check — list models
            await self._client.models.list()
            return (HealthState.OK, "openai api reachable")
        except Exception as exc:
            return (HealthState.DEGRADED, f"openai api unreachable: {exc}")
