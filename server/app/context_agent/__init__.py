"""Context Agent module — LLM-driven reasoning over borderline classifications.

Public surface (port-only):

    from server.app.context_agent import ContextReasoner, LlmClient, TokenBudgetGuard

Three ports — see docs/design/context_agent/design.md §2.5.

Adapter exports (for composition root / tests):

    from server.app.context_agent.agent import LlmContextAgent
    from server.app.context_agent.clients.mock_client import MockLlmClient
    from server.app.context_agent.clients.openai_client import OpenAiClient
    from server.app.context_agent.clients.anthropic_client import AnthropicClient
    from server.app.context_agent.token_manager import SqliteTokenManager, InMemoryTokenManager
"""

from __future__ import annotations

from .protocol import ContextReasoner, LlmClient, TokenBudgetGuard

__all__ = ["ContextReasoner", "LlmClient", "TokenBudgetGuard"]
