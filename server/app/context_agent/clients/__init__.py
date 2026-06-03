"""LLM client adapters for the context_agent module.

Each adapter satisfies the ``LlmClient`` Protocol defined in
``server/app/context_agent/protocol.py``.

Adapters:
  - ``MockLlmClient``      — deterministic fixture for tests; never calls any API.
  - ``OpenAiClient``       — wraps the openai SDK; model gpt-4o-mini.
  - ``AnthropicClient``    — wraps the anthropic SDK; model claude-haiku-4-5-20251001.
"""

from .mock_client import MockLlmClient
from .openai_client import OpenAiClient
from .anthropic_client import AnthropicClient

__all__ = ["MockLlmClient", "OpenAiClient", "AnthropicClient"]
