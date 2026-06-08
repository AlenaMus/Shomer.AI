"""Identity store contract tests — parametrized over InMemory + SQLite adapters.

Tests cover:
  1. Parent register / authenticate round-trip
  2. issue_child uniqueness (two children get different UUIDs)
  3. child_id contains no PII (UUID format, no display name embedded)
  4. list_children returns the right records
  5. parent_for_child resolution
  6. Pairing code TTL: expired code → None
  7. Pairing code single-use: redeem twice → second returns None
  8. Full redeem flow: pairing code → device token → authenticate_device round-trip
  9. authenticate_device unknown token → None
  10. parent_for_child unknown child → None
  11. Health returns OK

Run from repo root:
    python -m pytest server/tests/identity/test_identity_store.py -q
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest
import pytest_asyncio

# Ensure server/ is on sys.path.
_SERVER_DIR = str(Path(__file__).resolve().parents[2])
if _SERVER_DIR not in sys.path:
    sys.path.insert(0, _SERVER_DIR)

from app.identity import (
    InMemoryIdentityStore,
    SqliteIdentityStore,
    ChildRecord,
    DeviceContext,
)
from app.schemas import HealthState


# ---------------------------------------------------------------------------
# Fixtures — parametrize over both adapters
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(params=["memory", "sqlite"])
async def store(request, tmp_path):
    """Yield a ready-to-use IdentityStore for both adapters."""
    adapter = request.param
    if adapter == "memory":
        s = InMemoryIdentityStore(pairing_code_ttl_s=10)
        yield s
    else:
        db = str(tmp_path / "test_identity.db")
        s = SqliteIdentityStore(
            db_path=db,
            pairing_code_ttl_s=10,
            device_token_ttl_days=1,
        )
        await s.initialize()
        yield s
        await s.close()


# ---------------------------------------------------------------------------
# 1. Parent register / authenticate round-trip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parent_register_and_authenticate(store):
    parent_id, token = await store.register_parent(display_name="Test Parent")
    assert parent_id, "parent_id should be non-empty"
    assert token, "token should be non-empty"

    ctx = await store.authenticate_parent(token)
    assert ctx is not None
    assert ctx.parent_id == parent_id
    assert ctx.role == "parent"


@pytest.mark.asyncio
async def test_parent_authenticate_wrong_token_returns_none(store):
    ctx = await store.authenticate_parent("bogus-token-xyz")
    assert ctx is None


# ---------------------------------------------------------------------------
# 2 + 3. issue_child uniqueness and no-PII in child_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_issue_child_unique_ids(store):
    parent_id, _ = await store.register_parent()
    r1 = await store.issue_child(parent_id, "Alice")
    r2 = await store.issue_child(parent_id, "Bob")

    assert r1.child_id != r2.child_id, "Two children must get distinct child_ids"
    # UUIDs are 36 chars; display names must not appear in the child_id.
    assert "Alice" not in r1.child_id
    assert "Bob" not in r2.child_id


@pytest.mark.asyncio
async def test_issue_child_opaque_id_format(store):
    """child_id must look like a UUID — no embedded PII."""
    parent_id, _ = await store.register_parent()
    record = await store.issue_child(parent_id, "very secret name 12345")
    import re
    assert re.match(
        r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
        record.child_id,
    ), f"child_id must be a UUID, got: {record.child_id}"
    assert "secret" not in record.child_id


# ---------------------------------------------------------------------------
# 4. list_children
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_children(store):
    parent_id, _ = await store.register_parent()
    r1 = await store.issue_child(parent_id, "Alice")
    r2 = await store.issue_child(parent_id, "Bob")

    children = await store.list_children(parent_id)
    ids = {c.child_id for c in children}
    assert r1.child_id in ids
    assert r2.child_id in ids
    assert len(children) == 2


@pytest.mark.asyncio
async def test_list_children_empty(store):
    parent_id, _ = await store.register_parent()
    children = await store.list_children(parent_id)
    assert children == []


# ---------------------------------------------------------------------------
# 5. parent_for_child
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parent_for_child(store):
    parent_id, _ = await store.register_parent()
    record = await store.issue_child(parent_id, "child-A")
    resolved = await store.parent_for_child(record.child_id)
    assert resolved == parent_id


@pytest.mark.asyncio
async def test_parent_for_child_unknown_returns_none(store):
    result = await store.parent_for_child("no-such-child-id")
    assert result is None


# ---------------------------------------------------------------------------
# 6. Pairing code TTL — expired code → None
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_expired_pairing_code_returns_none_memory():
    """A pairing code with a negative TTL (already expired) must return None (memory)."""
    # ttl_s=-1 means expires_at = time.time() - 1, which is always in the past.
    s = InMemoryIdentityStore(pairing_code_ttl_s=-1)
    par_id, _ = await s.register_parent()
    child = await s.issue_child(par_id, "kid")
    pc = await s.create_pairing_code(par_id, child.child_id)
    ctx = await s.redeem_pairing_code(pc.code, "fp-xyz")
    assert ctx is None, f"Expired code should return None, got {ctx}"


@pytest.mark.asyncio
async def test_expired_pairing_code_returns_none_sqlite(tmp_path):
    """A pairing code with a negative TTL (already expired) must return None (sqlite)."""
    db = str(tmp_path / "expired_test.db")
    s = SqliteIdentityStore(db_path=db, pairing_code_ttl_s=-1)
    await s.initialize()
    try:
        par_id, _ = await s.register_parent()
        child = await s.issue_child(par_id, "kid")
        pc = await s.create_pairing_code(par_id, child.child_id)
        ctx = await s.redeem_pairing_code(pc.code, "fp-xyz")
        assert ctx is None, f"Expired code should return None, got {ctx}"
    finally:
        await s.close()


# ---------------------------------------------------------------------------
# 7. Pairing code single-use — redeem twice → second returns None
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pairing_code_single_use(store):
    parent_id, _ = await store.register_parent()
    child = await store.issue_child(parent_id, "kid")
    pc = await store.create_pairing_code(parent_id, child.child_id)

    # First redemption should succeed.
    ctx1 = await store.redeem_pairing_code(pc.code, "fp-abc")
    assert ctx1 is not None, "First redemption should succeed"

    # Second redemption of the same code should fail.
    ctx2 = await store.redeem_pairing_code(pc.code, "fp-abc")
    assert ctx2 is None, "Already-redeemed code should return None"


# ---------------------------------------------------------------------------
# 8. Full redeem flow: pairing code → device token → authenticate_device
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_redeem_to_device_token_round_trip(store):
    parent_id, _ = await store.register_parent()
    child = await store.issue_child(parent_id, "kid")
    pc = await store.create_pairing_code(parent_id, child.child_id)

    ctx = await store.redeem_pairing_code(pc.code, "device-fp")
    assert ctx is not None
    assert ctx.child_id == child.child_id
    assert ctx.parent_id == parent_id
    assert ctx.role == "child"
    assert len(ctx.device_token) > 20  # not empty / trivially short

    # Authenticate with the returned device token.
    auth_ctx = await store.authenticate_device(ctx.device_token)
    assert auth_ctx is not None
    assert auth_ctx.child_id == child.child_id
    assert auth_ctx.parent_id == parent_id
    assert auth_ctx.role == "child"


# ---------------------------------------------------------------------------
# 9. authenticate_device unknown token
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_authenticate_device_unknown_token_returns_none(store):
    ctx = await store.authenticate_device("totally-unknown-token-xyz")
    assert ctx is None


# ---------------------------------------------------------------------------
# 10. health() returns OK
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_returns_ok(store):
    state, detail = await store.health()
    assert state == HealthState.OK
    assert detail  # non-empty string
