"""Unit tests for the three context_agent tools.

reference: docs/design/context_agent/design.md §3.1–3.3.
"""

from __future__ import annotations

import pytest

from app.context_agent.tools.check_age import CheckAgeAppropriatenessTool
from app.context_agent.tools.lookup_slang import LookupSlangTool
from app.context_agent.tools.read_history import ReadHistoryTool

from .conftest import FakeAuditStore


# --------------------------------------------------------------------------- #
# ReadHistoryTool                                                              #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_read_history_returns_turns():
    store = FakeAuditStore()
    await store.record_conversation_turn("child_1", 0, "child_outbound", "שלום")
    await store.record_conversation_turn("child_1", 1, "child_inbound", "היי")
    await store.record_conversation_turn("child_1", 2, "child_outbound", "מה קורה?")

    tool = ReadHistoryTool(store)
    result = await tool.run({"child_id": "child_1", "last_n_turns": 5})
    assert result["tool"] == "read_history"
    assert result["result"]["turn_count"] == 3
    turns = result["result"]["turns"]
    assert len(turns) == 3
    assert turns[0]["text"] == "שלום"


@pytest.mark.asyncio
async def test_read_history_respects_last_n():
    store = FakeAuditStore()
    for i in range(10):
        await store.record_conversation_turn("child_2", i, "child_outbound", f"msg {i}")

    tool = ReadHistoryTool(store)
    result = await tool.run({"child_id": "child_2", "last_n_turns": 3})
    assert result["result"]["turn_count"] == 3


@pytest.mark.asyncio
async def test_read_history_empty():
    store = FakeAuditStore()
    tool = ReadHistoryTool(store)
    result = await tool.run({"child_id": "no-such-child"})
    assert result["result"]["turn_count"] == 0
    assert result["result"]["turns"] == []


@pytest.mark.asyncio
async def test_read_history_only_returns_correct_child():
    store = FakeAuditStore()
    await store.record_conversation_turn("child_A", 0, "child_outbound", "msg A")
    await store.record_conversation_turn("child_B", 0, "child_outbound", "msg B")

    tool = ReadHistoryTool(store)
    result = await tool.run({"child_id": "child_A"})
    assert result["result"]["turn_count"] == 1
    assert result["result"]["turns"][0]["text"] == "msg A"


# --------------------------------------------------------------------------- #
# LookupSlangTool                                                              #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_lookup_slang_finds_match(slang_lexicon_path):
    tool = LookupSlangTool(slang_lexicon_path)
    result = await tool.run({"text": "אתה לוזר גדול"})
    matches = result["result"]["matches"]
    words = [m["word"] for m in matches]
    assert "לוזר" in words


@pytest.mark.asyncio
async def test_lookup_slang_multiple_matches(slang_lexicon_path):
    tool = LookupSlangTool(slang_lexicon_path)
    result = await tool.run({"text": "לוזר מטומטם"})
    matches = result["result"]["matches"]
    words = [m["word"] for m in matches]
    assert "לוזר" in words
    assert "מטומטם" in words


@pytest.mark.asyncio
async def test_lookup_slang_no_match(slang_lexicon_path):
    tool = LookupSlangTool(slang_lexicon_path)
    result = await tool.run({"text": "שלום עולם"})
    assert result["result"]["matches"] == []


@pytest.mark.asyncio
async def test_lookup_slang_missing_lexicon_graceful():
    """Missing lexicon → empty matches, not an error."""
    tool = LookupSlangTool("/nonexistent/path/slang.json")
    result = await tool.run({"text": "לוזר"})
    assert result["result"]["matches"] == []


@pytest.mark.asyncio
async def test_lookup_slang_returns_metadata(slang_lexicon_path):
    tool = LookupSlangTool(slang_lexicon_path)
    result = await tool.run({"text": "לוזר"})
    matches = result["result"]["matches"]
    assert len(matches) >= 1
    m = matches[0]
    assert "word" in m
    assert "meaning" in m
    assert "common_use" in m
    assert "valence" in m


# --------------------------------------------------------------------------- #
# CheckAgeAppropriatenessTool                                                  #
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_check_age_13_moderate():
    tool = CheckAgeAppropriatenessTool()
    result = await tool.run({"child_age": 13})
    assert result["tool"] == "check_age"
    assert result["result"]["sensitivity_level"] == "moderate"
    assert result["result"]["child_age"] == 13


@pytest.mark.asyncio
async def test_check_age_9_high():
    tool = CheckAgeAppropriatenessTool()
    result = await tool.run({"child_age": 9})
    assert result["result"]["sensitivity_level"] == "high"


@pytest.mark.asyncio
async def test_check_age_17_moderate_low():
    tool = CheckAgeAppropriatenessTool()
    result = await tool.run({"child_age": 17})
    assert result["result"]["sensitivity_level"] == "moderate_low"


@pytest.mark.asyncio
async def test_check_age_25_low():
    tool = CheckAgeAppropriatenessTool()
    result = await tool.run({"child_age": 25})
    assert result["result"]["sensitivity_level"] == "low"


@pytest.mark.asyncio
async def test_check_age_has_notes():
    tool = CheckAgeAppropriatenessTool()
    result = await tool.run({"child_age": 13})
    assert "notes" in result["result"]
    assert len(result["result"]["notes"]) > 0
