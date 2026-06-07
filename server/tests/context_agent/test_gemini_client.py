"""Conformance tests for GeminiClient (no live API call).

GeminiClient wraps Gemini's OpenAI-compatible endpoint via the openai SDK.
Reference: server/app/context_agent/clients/gemini_client.py.
"""

from __future__ import annotations

import inspect

from app.context_agent.clients.gemini_client import GeminiClient


def test_constructs_with_default_model() -> None:
    c = GeminiClient("dummy-key")
    assert c.model_name == "gemini-2.5-flash"


def test_model_override() -> None:
    c = GeminiClient("dummy-key", "gemini-2.5-flash")
    assert c.model_name == "gemini-2.5-flash"


def test_satisfies_llm_client_shape() -> None:
    c = GeminiClient("dummy-key")
    # The LlmClient Protocol: async reason(), async health(), model_name property.
    assert inspect.iscoroutinefunction(c.reason)
    assert inspect.iscoroutinefunction(c.health)
    assert isinstance(c.model_name, str)
