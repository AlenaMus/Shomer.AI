"""GeminiClient — LlmClient adapter for Google Gemini.

Uses Gemini's **OpenAI-compatible** endpoint, so it reuses the already-installed
``openai`` SDK (no extra dependency) — only the ``base_url`` and key differ.

    base_url = https://generativelanguage.googleapis.com/v1beta/openai/
    key      = GEMINI_API_KEY
    model    = gemini-2.0-flash  (override with GEMINI_MODEL)

Raises on any SDK exception; ``LlmRouter`` catches and tries the fallback.

Reference: docs/design/context_agent/design.md §3.2 (LlmRouter); the LlmClient
Protocol in ../protocol.py.
"""

from __future__ import annotations

try:
    import openai
    _OPENAI_AVAILABLE = True
except ImportError:
    _OPENAI_AVAILABLE = False

from ...schemas import HealthState
from ..protocol import LlmCallResult

_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
_DEFAULT_MODEL = "gemini-2.5-flash"


class GeminiClient:
    """Async Gemini client via the OpenAI-compatible API; satisfies ``LlmClient``."""

    def __init__(self, api_key: str, model: str = _DEFAULT_MODEL) -> None:
        if not _OPENAI_AVAILABLE:
            raise ImportError(
                "openai package is not installed. Run: pip install openai>=1.55.0"
            )
        self._model = model or _DEFAULT_MODEL
        self._client = openai.AsyncOpenAI(api_key=api_key, base_url=_BASE_URL)

    @property
    def model_name(self) -> str:
        return self._model

    async def reason(
        self,
        system: str,
        user: str,
        max_tokens: int = 512,
        temperature: float = 0.2,
    ) -> LlmCallResult:
        """Call Gemini (JSON mode) and return text + token usage."""
        # Gemini 2.5 Flash is a "thinking" model: by default it spends the
        # output-token budget on internal reasoning and can truncate the actual
        # JSON. Disable thinking via the OpenAI-compat ``reasoning_effort`` knob
        # so the whole budget goes to the response.
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
            response_format={"type": "json_object"},
            extra_body={"reasoning_effort": "none"},
        )
        usage = getattr(response, "usage", None)
        return LlmCallResult(
            text=response.choices[0].message.content or "",
            input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage, "completion_tokens", 0) or 0,
            model=getattr(response, "model", self._model),
        )

    async def health(self) -> tuple[HealthState, str]:
        try:
            await self._client.models.list()
            return (HealthState.OK, "gemini api reachable")
        except Exception as exc:  # noqa: BLE001
            return (HealthState.DEGRADED, f"gemini api check failed: {exc}")
