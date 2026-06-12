"""Tests for conversation-scoped history in AuditStore adapters.

Covers the fix for the cross-thread false-alarm bug (Daria bleed):
  - Two different conversation_ids for the same child do NOT share history.
  - Default conversation_id ("default") is backward-compatible.
  - Both InMemoryAuditStore and SqliteAuditStore pass the same contract.

Run from repo root:
    .\\server\\.venv\\Scripts\\python.exe -m pytest server/tests/audit_log/test_conversation_scoping.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import AsyncIterator

import pytest
import pytest_asyncio

_SERVER_DIR = str(Path(__file__).resolve().parents[2])
if _SERVER_DIR not in sys.path:
    sys.path.insert(0, _SERVER_DIR)

from app.audit_log.in_memory_adapter import InMemoryAuditStore
from app.audit_log.sqlite_adapter import SqliteAuditStore
from app.audit_log.protocol import AuditStore, ConversationTurn


# ---------------------------------------------------------------------------
# Fixtures — parametrized over both adapters
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(params=["sqlite", "in_memory"])
async def store(request, tmp_path) -> AsyncIterator[AuditStore]:
    if request.param == "sqlite":
        s = SqliteAuditStore(db_path=str(tmp_path / "audit_scoping.db"))
        await s.initialize()
        try:
            yield s
        finally:
            await s.close()
    else:
        yield InMemoryAuditStore()


# ---------------------------------------------------------------------------
# (i) Two different conversation_ids do NOT share history
# ---------------------------------------------------------------------------


async def test_different_conversation_ids_do_not_share_history(store: AuditStore):
    """The Daria bleed bug: unrelated test messages in conv-A must not appear
    when reading conv-B for the same child.

    This is the core regression test for the conversation-scoping fix.
    """
    child = "child-daria-test"
    conv_whatsapp = "com.whatsapp"
    conv_telegram = "org.telegram.messenger"

    # Record threatening messages in conv-A (WhatsApp)
    await store.record_conversation_turn(
        child_id=child, turn_index=0, role="child_inbound",
        text="אתה טמבל", conversation_id=conv_whatsapp,
    )
    await store.record_conversation_turn(
        child_id=child, turn_index=1, role="child_inbound",
        text="אני אהרוג אותך", conversation_id=conv_whatsapp,
    )

    # Record the benign Daria message in conv-B (Telegram)
    await store.record_conversation_turn(
        child_id=child, turn_index=0, role="child_inbound",
        text="Daria: אנחנו לא יכולים, לא אני ולא בעלי 😭",
        conversation_id=conv_telegram,
    )

    # Reading conv-B must ONLY return the Daria message — NOT the threats from conv-A.
    telegram_history = await store.read_conversation_history(
        child, last_n_turns=10, conversation_id=conv_telegram
    )
    assert len(telegram_history) == 1, (
        f"Expected 1 turn in Telegram thread, got {len(telegram_history)}: "
        f"{[t.text for t in telegram_history]}"
    )
    assert telegram_history[0].text == "Daria: אנחנו לא יכולים, לא אני ולא בעלי 😭"

    # Reading conv-A must ONLY return the threats.
    whatsapp_history = await store.read_conversation_history(
        child, last_n_turns=10, conversation_id=conv_whatsapp
    )
    assert len(whatsapp_history) == 2
    assert whatsapp_history[0].text == "אתה טמבל"
    assert whatsapp_history[1].text == "אני אהרוג אותך"


# ---------------------------------------------------------------------------
# (ii) Default conversation_id is backward-compatible
# ---------------------------------------------------------------------------


async def test_default_conversation_id_backward_compat(store: AuditStore):
    """Calling without conversation_id uses 'default' and is backward-compatible.

    Tests that pre-scoping call sites (no conversation_id arg) continue to work
    and that their data ends up in the 'default' bucket.
    """
    child = "child-compat"

    # Old-style calls without explicit conversation_id
    await store.record_conversation_turn(
        child_id=child, turn_index=0, role="child_outbound", text="hello"
    )
    await store.record_conversation_turn(
        child_id=child, turn_index=1, role="child_outbound", text="world"
    )

    # Old-style read without explicit conversation_id
    history = await store.read_conversation_history(child, last_n_turns=5)
    assert len(history) == 2
    assert [t.text for t in history] == ["hello", "world"]

    # Explicit 'default' gives the same result
    history_explicit = await store.read_conversation_history(
        child, last_n_turns=5, conversation_id="default"
    )
    assert len(history_explicit) == 2


# ---------------------------------------------------------------------------
# (iii) Turn index increments per (child, conversation_id)
# ---------------------------------------------------------------------------


async def test_turn_index_per_conversation_thread(store: AuditStore):
    """turn_index must be independent per conversation thread for the same child."""
    child = "child-turns"
    conv_a = "thread-A"
    conv_b = "thread-B"

    await store.record_conversation_turn(
        child_id=child, turn_index=0, role="child_outbound",
        text="A0", conversation_id=conv_a,
    )
    await store.record_conversation_turn(
        child_id=child, turn_index=0, role="child_outbound",
        text="B0", conversation_id=conv_b,
    )
    await store.record_conversation_turn(
        child_id=child, turn_index=1, role="child_outbound",
        text="A1", conversation_id=conv_a,
    )

    hist_a = await store.read_conversation_history(child, last_n_turns=10, conversation_id=conv_a)
    hist_b = await store.read_conversation_history(child, last_n_turns=10, conversation_id=conv_b)

    assert [t.text for t in hist_a] == ["A0", "A1"]
    assert [t.text for t in hist_b] == ["B0"]

    # Cross-check: unknown conversation_id returns empty
    hist_c = await store.read_conversation_history(child, last_n_turns=10, conversation_id="no-such-thread")
    assert hist_c == []


# ---------------------------------------------------------------------------
# (iv) ConversationTurn carries conversation_id field
# ---------------------------------------------------------------------------


async def test_conversation_turn_carries_conversation_id(store: AuditStore):
    """Returned ConversationTurn objects must expose the conversation_id field."""
    child = "child-field"
    conv = "com.signal"

    await store.record_conversation_turn(
        child_id=child, turn_index=0, role="child_inbound",
        text="test", conversation_id=conv,
    )

    history = await store.read_conversation_history(child, last_n_turns=5, conversation_id=conv)
    assert len(history) == 1
    turn = history[0]
    assert isinstance(turn, ConversationTurn)
    assert turn.conversation_id == conv
    assert turn.child_id == child
