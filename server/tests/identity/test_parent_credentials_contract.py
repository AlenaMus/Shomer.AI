"""Contract tests for username/password methods on IdentityStore.

Parametrized over InMemoryIdentityStore and SqliteIdentityStore — any adapter
implementing the Protocol must pass every test here.

Covers:
  - register_parent with username+password → authenticate_parent_credentials → ParentAuth
  - Wrong password → None
  - Unknown username → None (same return as wrong password — no enumeration)
  - Duplicate username → ValueError("username_taken") from both adapters
  - passwords.hash_password / verify_password unit tests

Run from repo root:
    server\\.venv\\Scripts\\python.exe -m pytest server/tests/identity/test_parent_credentials_contract.py -q
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
from app.identity.passwords import hash_password, verify_password


# ---------------------------------------------------------------------------
# Fixture — parametrize over both adapters
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(params=["memory", "sqlite"])
async def store(request, tmp_path):
    adapter = request.param
    if adapter == "memory":
        s = InMemoryIdentityStore()
        yield s
    else:
        db = str(tmp_path / "cred_test.db")
        s = SqliteIdentityStore(db_path=db)
        await s.initialize()
        yield s
        await s.close()


# ---------------------------------------------------------------------------
# passwords.py unit tests (stdlib only — no adapter)
# ---------------------------------------------------------------------------


def test_hash_and_verify_round_trip():
    pw = "correcthorsebatterystaple"
    h = hash_password(pw)
    assert h.startswith("pbkdf2$")
    assert verify_password(pw, h)


def test_verify_wrong_password():
    h = hash_password("rightpassword")
    assert not verify_password("wrongpassword", h)


def test_verify_malformed_hash():
    assert not verify_password("anything", "notahash")
    assert not verify_password("anything", "pbkdf2$bad$bad$bad")
    assert not verify_password("anything", "")


def test_two_different_passwords_produce_different_hashes():
    h1 = hash_password("password1")
    h2 = hash_password("password1")  # same password, different salt
    # Salts are random → hashes differ even for same password.
    assert h1 != h2
    # But both verify correctly.
    assert verify_password("password1", h1)
    assert verify_password("password1", h2)


# ---------------------------------------------------------------------------
# authenticate_parent_credentials — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_authenticate_credentials_happy_path(store):
    parent_id, token = await store.register_parent(
        display_name="Test User",
        username="testuser",
        password="longpassword123",
    )
    auth = await store.authenticate_parent_credentials("testuser", "longpassword123")
    assert auth is not None
    assert auth.parent_id == parent_id
    assert auth.parent_token == token
    assert auth.display_name == "Test User"


# ---------------------------------------------------------------------------
# authenticate_parent_credentials — wrong password → None
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wrong_password_returns_none(store):
    await store.register_parent(
        display_name="Test User",
        username="wrongpwuser",
        password="correctpassword",
    )
    auth = await store.authenticate_parent_credentials("wrongpwuser", "incorrectpassword")
    assert auth is None


# ---------------------------------------------------------------------------
# authenticate_parent_credentials — unknown username → None
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_username_returns_none(store):
    auth = await store.authenticate_parent_credentials("no.such.user", "anypassword")
    assert auth is None


# ---------------------------------------------------------------------------
# Duplicate username → ValueError("username_taken")
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_duplicate_username_raises(store):
    await store.register_parent(
        display_name="First",
        username="duplicate.user",
        password="password123",
    )
    with pytest.raises(ValueError, match="username_taken"):
        await store.register_parent(
            display_name="Second",
            username="duplicate.user",
            password="password456",
        )


# ---------------------------------------------------------------------------
# register_parent without username+password still works (back-compat)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_without_credentials_still_works(store):
    parent_id, token = await store.register_parent(display_name="Legacy")
    assert parent_id
    assert token
    # authenticate_credentials with no username registered → None
    auth = await store.authenticate_parent_credentials("legacy", "anything")
    assert auth is None


# ---------------------------------------------------------------------------
# authenticate_parent (token-based) is unaffected by new fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_token_auth_still_works_after_credential_registration(store):
    parent_id, token = await store.register_parent(
        display_name="Alice",
        username="alice.cred",
        password="alicepassword",
    )
    ctx = await store.authenticate_parent(token)
    assert ctx is not None
    assert ctx.parent_id == parent_id
    assert ctx.role == "parent"
