"""Contract tests for email/password methods on IdentityStore.

Parametrized over InMemoryIdentityStore and SqliteIdentityStore — any adapter
implementing the Protocol must pass every test here.

Covers:
  - register_parent with email+password → authenticate_parent_credentials → ParentAuth
  - Wrong password → None
  - Unknown email → None (same return as wrong password — no enumeration)
  - Duplicate email → ValueError("email_taken") from both adapters
  - Email is normalised to lowercase before store and compare
  - passwords.hash_password / verify_password unit tests
  - get_parent_email helper: present after email register, absent for name-only

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
# authenticate_parent_credentials — happy path (email)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_authenticate_credentials_happy_path(store):
    parent_id, token = await store.register_parent(
        display_name="Test User",
        email="testuser@example.com",
        password="longpassword123",
    )
    auth = await store.authenticate_parent_credentials("testuser@example.com", "longpassword123")
    assert auth is not None
    assert auth.parent_id == parent_id
    assert auth.parent_token == token
    assert auth.display_name == "Test User"
    assert auth.email == "testuser@example.com"


# ---------------------------------------------------------------------------
# Email is normalised to lowercase before store and compare
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_email_case_insensitive_login(store):
    """Registering with UPPER@EXAMPLE.COM should log in with lower@example.com."""
    await store.register_parent(
        display_name="CaseSensitive",
        email="UPPER@EXAMPLE.COM",
        password="password12345",
    )
    # Login with mixed case
    auth = await store.authenticate_parent_credentials("upper@Example.com", "password12345")
    assert auth is not None
    assert auth.email == "upper@example.com"


# ---------------------------------------------------------------------------
# authenticate_parent_credentials — wrong password → None
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wrong_password_returns_none(store):
    await store.register_parent(
        display_name="Test User",
        email="wrongpw@example.com",
        password="correctpassword",
    )
    auth = await store.authenticate_parent_credentials("wrongpw@example.com", "incorrectpassword")
    assert auth is None


# ---------------------------------------------------------------------------
# authenticate_parent_credentials — unknown email → None
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_email_returns_none(store):
    auth = await store.authenticate_parent_credentials("no.such@example.com", "anypassword")
    assert auth is None


# ---------------------------------------------------------------------------
# Duplicate email → ValueError("email_taken")
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_duplicate_email_raises(store):
    await store.register_parent(
        display_name="First",
        email="duplicate@example.com",
        password="password123",
    )
    with pytest.raises(ValueError, match="email_taken"):
        await store.register_parent(
            display_name="Second",
            email="duplicate@example.com",
            password="password456",
        )


@pytest.mark.asyncio
async def test_duplicate_email_case_insensitive_raises(store):
    """Registering the same email in different case should also raise email_taken."""
    await store.register_parent(
        display_name="First",
        email="Dup@Example.COM",
        password="password123",
    )
    with pytest.raises(ValueError, match="email_taken"):
        await store.register_parent(
            display_name="Second",
            email="dup@example.com",
            password="password456",
        )


# ---------------------------------------------------------------------------
# register_parent without email+password still works (back-compat)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_without_credentials_still_works(store):
    parent_id, token = await store.register_parent(display_name="Legacy")
    assert parent_id
    assert token
    # authenticate_credentials with no email registered → None
    auth = await store.authenticate_parent_credentials("legacy@example.com", "anything")
    assert auth is None


# ---------------------------------------------------------------------------
# authenticate_parent (token-based) is unaffected by new fields
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_token_auth_still_works_after_credential_registration(store):
    parent_id, token = await store.register_parent(
        display_name="Alice",
        email="alice@example.com",
        password="alicepassword",
    )
    ctx = await store.authenticate_parent(token)
    assert ctx is not None
    assert ctx.parent_id == parent_id
    assert ctx.role == "parent"


# ---------------------------------------------------------------------------
# get_parent_email helper
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_parent_email_present(store):
    parent_id, _ = await store.register_parent(
        display_name="Emailer",
        email="stored@example.com",
        password="storedpass1",
    )
    email = await store.get_parent_email(parent_id)
    assert email == "stored@example.com"


@pytest.mark.asyncio
async def test_get_parent_email_absent_for_name_only(store):
    parent_id, _ = await store.register_parent(display_name="NoEmail")
    email = await store.get_parent_email(parent_id)
    assert email is None
