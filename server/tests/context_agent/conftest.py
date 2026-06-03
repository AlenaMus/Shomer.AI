"""Shared pytest fixtures for context_agent tests.

Key fixtures:
  - ``fake_audit_store``    — in-memory AuditStore implementation.
  - ``sample_classifier_result`` — borderline ClassificationResult.
  - ``mock_client``         — MockLlmClient with default canned response.
  - ``in_memory_budget``    — InMemoryTokenManager with generous defaults.
  - ``slang_lexicon_path``  — path to test slang lexicon (reuses server/data/).
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

import pytest

# Make sure we can import from server/app
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from app.audit_log.protocol import ConversationTurn
from app.context_agent.clients.mock_client import MockLlmClient
from app.context_agent.token_manager import InMemoryTokenManager
from app.schemas import ClassificationResult


# --------------------------------------------------------------------------- #
# FakeAuditStore — minimal in-memory AuditStore for tests                     #
# --------------------------------------------------------------------------- #


class FakeAuditStore:
    """Minimal in-memory AuditStore.

    Only implements the methods needed by the Context Agent's tools.
    Stores ``record_conversation_turn`` calls in a list and returns
    them via ``read_conversation_history``.
    """

    def __init__(self) -> None:
        self._turns: list[ConversationTurn] = []

    async def record_conversation_turn(
        self,
        child_id: str,
        turn_index: int,
        role: str,
        text: str,
    ) -> None:
        import time
        self._turns.append(
            ConversationTurn(
                child_id=child_id,
                turn_index=turn_index,
                role=role,
                text=text,
                timestamp=time.time(),
            )
        )

    async def read_conversation_history(
        self,
        child_id: str,
        last_n_turns: int = 5,
    ) -> list[ConversationTurn]:
        relevant = [t for t in self._turns if t.child_id == child_id]
        return relevant[-last_n_turns:]

    # Stubs for the rest of the Protocol (not used by context_agent tools)

    async def record_classification(self, *args, **kwargs) -> int:
        return 1

    async def record_agent_trace(self, *args, **kwargs) -> int:
        return 1

    async def record_alert(self, *args, **kwargs) -> None:
        pass

    def query_for_evaluation(self, *args, **kwargs):
        async def _empty():
            return
            yield  # pragma: no cover
        return _empty()

    async def set_gold_label(self, *args, **kwargs) -> None:
        pass

    async def cleanup_expired(self, retention_days: int = 7) -> int:
        return 0

    async def health(self):
        from app.schemas import HealthState
        return (HealthState.OK, "fake audit store ok")

    def reset(self) -> None:
        self._turns.clear()


# --------------------------------------------------------------------------- #
# Pytest fixtures                                                              #
# --------------------------------------------------------------------------- #


@pytest.fixture
def fake_audit_store() -> FakeAuditStore:
    return FakeAuditStore()


@pytest.fixture
def sample_classifier_result() -> ClassificationResult:
    """A borderline classification result (confidence in [0.3, 0.7])."""
    return ClassificationResult(
        label="abusive",
        confidence=0.55,
        is_offensive=True,
        model_version="v1.0-standin",
        latency_ms=12.5,
        is_borderline=True,
        raw_confidence=0.55,
        error=False,
    )


@pytest.fixture
def non_offensive_classifier_result() -> ClassificationResult:
    return ClassificationResult(
        label="non_offensive",
        confidence=0.85,
        is_offensive=False,
        model_version="v1.0-standin",
        latency_ms=10.0,
        is_borderline=False,
        raw_confidence=0.85,
        error=False,
    )


@pytest.fixture
def mock_client() -> MockLlmClient:
    return MockLlmClient()


@pytest.fixture
def mock_client_threatening() -> MockLlmClient:
    return MockLlmClient(
        canned_response={
            "is_real_threat": True,
            "severity": "high",
            "explanation": "איום ישיר זוהה בשיחה",
            "reasoning": "Repeated targeted insults with explicit threat language.",
        }
    )


@pytest.fixture
def in_memory_budget() -> InMemoryTokenManager:
    return InMemoryTokenManager(
        token_prices_path="server/app/context_agent/token_prices.yaml",
        daily_token_budget=100_000,
        daily_usd_budget=10.0,  # generous for tests
    )


@pytest.fixture
def exhausted_budget() -> InMemoryTokenManager:
    """Budget with only 1 token remaining — will deny immediately."""
    return InMemoryTokenManager(
        token_prices_path="server/app/context_agent/token_prices.yaml",
        daily_token_budget=1,
        daily_usd_budget=0.000001,
    )


@pytest.fixture
def slang_lexicon_path() -> str:
    return "server/data/slang_lexicon.json"
