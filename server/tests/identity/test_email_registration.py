"""Tests for parent email registration and child→parent→email resolution.

Covers:
  - register_parent with email persists the email (both adapters).
  - get_parent_email returns the stored normalised email.
  - child → parent_for_child → get_parent_email chain works end-to-end.
  - register_parent without email → get_parent_email returns None.
  - Duplicate email → ValueError("email_taken") is raised.
  - Case-insensitive email normalisation (upper-case → lower-case in storage).

Run from repo root:
    python -m pytest server/tests/identity/test_email_registration.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import pytest_asyncio

_SERVER_DIR = str(Path(__file__).resolve().parents[2])
if _SERVER_DIR not in sys.path:
    sys.path.insert(0, _SERVER_DIR)

from app.identity import InMemoryIdentityStore, SqliteIdentityStore


# ---------------------------------------------------------------------------
# Fixture: parametrize over InMemory + SQLite adapters
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(params=["memory", "sqlite"])
async def store(request, tmp_path):
    """Yield an initialized IdentityStore for both adapters."""
    if request.param == "memory":
        s = InMemoryIdentityStore(pairing_code_ttl_s=600)
        yield s
    else:
        db = str(tmp_path / "email_test.db")
        s = SqliteIdentityStore(db_path=db, pairing_code_ttl_s=600)
        await s.initialize()
        yield s
        await s.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_with_email_persists(store):
    """register_parent(email=...) → get_parent_email returns that email."""
    parent_id, _token = await store.register_parent(
        display_name="Alona",
        email="alona@example.com",
        password="password123",
    )
    stored = await store.get_parent_email(parent_id)
    assert stored == "alona@example.com"


@pytest.mark.asyncio
async def test_register_without_email_returns_none(store):
    """register_parent without email → get_parent_email returns None."""
    parent_id, _token = await store.register_parent(display_name="NoEmail")
    stored = await store.get_parent_email(parent_id)
    assert stored is None


@pytest.mark.asyncio
async def test_email_normalised_to_lowercase(store):
    """Email is stored normalised to lowercase regardless of input case."""
    parent_id, _ = await store.register_parent(
        email="Alona.Test@Example.COM",
        password="password123",
    )
    stored = await store.get_parent_email(parent_id)
    assert stored == "alona.test@example.com"


@pytest.mark.asyncio
async def test_child_to_parent_to_email_chain(store):
    """child_id → parent_for_child → get_parent_email resolves correctly."""
    parent_id, _ = await store.register_parent(
        display_name="Parent",
        email="parent@example.com",
        password="strongpass1",
    )
    child_record = await store.issue_child(parent_id=parent_id, display_name="Child")
    child_id = child_record.child_id

    resolved_parent = await store.parent_for_child(child_id)
    assert resolved_parent == parent_id

    resolved_email = await store.get_parent_email(resolved_parent)
    assert resolved_email == "parent@example.com"


@pytest.mark.asyncio
async def test_unknown_parent_returns_none(store):
    """get_parent_email for an unknown parent_id returns None."""
    result = await store.get_parent_email("nonexistent-parent-id")
    assert result is None


@pytest.mark.asyncio
async def test_duplicate_email_raises_value_error(store):
    """Registering the same email twice raises ValueError('email_taken')."""
    await store.register_parent(
        email="dup@example.com",
        password="password1",
    )
    with pytest.raises(ValueError, match="email_taken"):
        await store.register_parent(
            email="dup@example.com",
            password="password2",
        )


@pytest.mark.asyncio
async def test_duplicate_email_case_insensitive(store):
    """Duplicate check is case-insensitive (DUP@EXAMPLE.COM == dup@example.com)."""
    await store.register_parent(
        email="dup@example.com",
        password="password1",
    )
    with pytest.raises(ValueError, match="email_taken"):
        await store.register_parent(
            email="DUP@EXAMPLE.COM",
            password="password2",
        )


@pytest.mark.asyncio
async def test_multiple_children_all_resolve_same_parent(store):
    """Multiple children under the same parent all resolve to that parent's email."""
    parent_id, _ = await store.register_parent(
        email="multi@example.com",
        password="password123",
    )
    c1 = await store.issue_child(parent_id, "Child One")
    c2 = await store.issue_child(parent_id, "Child Two")

    for child_rec in (c1, c2):
        pid = await store.parent_for_child(child_rec.child_id)
        assert pid == parent_id
        email = await store.get_parent_email(pid)
        assert email == "multi@example.com"
