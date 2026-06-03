"""MockLlmClient — deterministic LLM client for tests.

Returns a canned JSON response without making any network calls.
Token counts are fixed: input=50, output=30.

Usage::

    client = MockLlmClient()
    # Default response
    result = await client.reason("system", "user")

    # Custom response per-test
    client = MockLlmClient(canned_response={"is_real_threat": True, ...})
"""

from __future__ import annotations

import json
from typing import Any

from ...schemas import HealthState
from ..protocol import LlmCallResult

_DEFAULT_RESPONSE: dict[str, Any] = {
    "is_real_threat": False,
    "severity": "low",
    "explanation": "שיחה ידידותית ללא סיכון אמיתי",
    "reasoning": "playful banter between friends; no real threat detected",
    "tools_called": [],
}

_INPUT_TOKENS = 50
_OUTPUT_TOKENS = 30


class MockLlmClient:
    """Deterministic in-process LLM client. No network calls. For tests."""

    model_name: str = "mock"

    def __init__(self, canned_response: dict[str, Any] | None = None) -> None:
        self._canned = canned_response if canned_response is not None else _DEFAULT_RESPONSE

    async def reason(
        self,
        system: str,
        user: str,
        max_tokens: int = 512,
        temperature: float = 0.2,
    ) -> LlmCallResult:
        return LlmCallResult(
            text=json.dumps(self._canned, ensure_ascii=False),
            input_tokens=_INPUT_TOKENS,
            output_tokens=_OUTPUT_TOKENS,
            model=self.model_name,
        )

    async def health(self) -> tuple[HealthState, str]:
        return (HealthState.OK, "mock client always healthy")
