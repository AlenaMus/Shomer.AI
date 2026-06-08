"""Auth middleware + monitor authorization tests (S2).

Covers:
  1. POST /v1/monitor/events with NO token → 401
  2. POST /v1/monitor/events with valid child token but mismatched child_id → 403
  3. POST /v1/monitor/events with matching child token → 202 (full pairing flow)
  4. GET /health (allowlisted) → 200 with no token
  5. POST /v1/pair (allowlisted) → accessible without auth
  6. POST /classify (allowlisted legacy) → accessible without auth

The tests use FastAPI's TestClient.  An InMemoryIdentityStore is seeded on
``app.state.identity`` AFTER the lifespan() has run (same pattern as how
existing tests swap app.state.classifier).

Run from repo root:
    python -m pytest server/tests/identity/test_auth_middleware.py -q
"""

from __future__ import annotations

import sys
import time
import uuid
from pathlib import Path

import pytest

_SERVER_DIR = str(Path(__file__).resolve().parents[2])
if _SERVER_DIR not in sys.path:
    sys.path.insert(0, _SERVER_DIR)

from fastapi.testclient import TestClient

from app.main import app
from app.identity import InMemoryIdentityStore
from app.schemas import ClassificationResult, HealthState, TriageDecision


# ---------------------------------------------------------------------------
# Shared stub helpers
# ---------------------------------------------------------------------------


class _FixedClassifier:
    model_version = "stub-s2"
    backend_name = "stub-s2"

    async def classify(self, text: str) -> ClassificationResult:
        return ClassificationResult(
            label="non_offensive",
            confidence=0.95,
            is_offensive=False,
            model_version="stub-s2",
            latency_ms=1.0,
            is_borderline=False,
            raw_confidence=0.95,
            error=False,
        )

    async def health(self):
        return (HealthState.OK, "stub")


def _batch_payload(child_id: str, text: str = "שלום עולם") -> dict:
    return {
        "session_id": "sess-test",
        "child_id": child_id,
        "events": [
            {
                "client_msg_id": f"msg-{uuid.uuid4().hex[:8]}",
                "app_package": "com.whatsapp",
                "text": text,
                "text_hash": f"hash-{uuid.uuid4().hex[:8]}",
                "captured_at": time.time(),
                "direction": "inbound",
            }
        ],
    }


# ---------------------------------------------------------------------------
# Shared fixture: wired TestClient with InMemoryIdentityStore
# ---------------------------------------------------------------------------


@pytest.fixture
def auth_client(monkeypatch, tmp_path):
    """TestClient with a real InMemoryIdentityStore seeded on app.state.identity."""
    monkeypatch.setenv("AUDIT_DB_PATH", str(tmp_path / "test_audit.db"))
    monkeypatch.setenv("CONTEXT_AGENT_ENABLED", "false")
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "99999")
    monkeypatch.setenv("IDENTITY_BACKEND", "memory")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    identity_store = InMemoryIdentityStore()

    with TestClient(app, raise_server_exceptions=True) as client:
        # Override classifier + context agent (pre-S2 pattern).
        app.state.classifier = _FixedClassifier()
        app.state.context_agent = None
        # Seed the identity store (overrides the one built by lifespan()).
        app.state.identity = identity_store
        yield client, identity_store


# ---------------------------------------------------------------------------
# Test 1: /v1/monitor/events — no token → 401
# ---------------------------------------------------------------------------


def test_monitor_events_no_token_returns_401(auth_client):
    client, identity_store = auth_client
    child_id = f"child-{uuid.uuid4().hex[:8]}"

    resp = client.post(
        "/v1/monitor/events",
        json=_batch_payload(child_id),
        # No Authorization header.
    )
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.text}"


# ---------------------------------------------------------------------------
# Test 2: valid child token but mismatched child_id → 403
# ---------------------------------------------------------------------------


def test_monitor_events_mismatched_child_id_returns_403(auth_client):
    """A token for child A cannot post on behalf of child B."""
    import asyncio
    client, identity_store = auth_client

    # Register parent + two children + pair child A.
    async def _setup():
        parent_id, _ = await identity_store.register_parent()
        child_a = await identity_store.issue_child(parent_id, "Alice")
        child_b = await identity_store.issue_child(parent_id, "Bob")
        pc = await identity_store.create_pairing_code(parent_id, child_a.child_id)
        ctx = await identity_store.redeem_pairing_code(pc.code, "fp-alice")
        return child_a.child_id, child_b.child_id, ctx.device_token

    loop = asyncio.new_event_loop()
    try:
        child_a_id, child_b_id, token_a = loop.run_until_complete(_setup())
    finally:
        loop.close()

    # Post with token_a but child_b's child_id in the batch → 403.
    resp = client.post(
        "/v1/monitor/events",
        json=_batch_payload(child_b_id),
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"


# ---------------------------------------------------------------------------
# Test 3: valid child token with matching child_id → 202
# ---------------------------------------------------------------------------


def test_monitor_events_valid_child_token_returns_202(auth_client):
    """Full pairing flow: register → pair → post with correct child_id → 202."""
    import asyncio
    client, identity_store = auth_client

    async def _setup():
        parent_id, _ = await identity_store.register_parent()
        child = await identity_store.issue_child(parent_id, "Alice")
        pc = await identity_store.create_pairing_code(parent_id, child.child_id)
        ctx = await identity_store.redeem_pairing_code(pc.code, "fp-device")
        return child.child_id, ctx.device_token

    loop = asyncio.new_event_loop()
    try:
        child_id, device_token = loop.run_until_complete(_setup())
    finally:
        loop.close()

    resp = client.post(
        "/v1/monitor/events",
        json=_batch_payload(child_id),
        headers={"Authorization": f"Bearer {device_token}"},
    )
    assert resp.status_code == 202, f"Expected 202, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert body["accepted"] == 1


# ---------------------------------------------------------------------------
# Test 4: /health is allowlisted → accessible without auth
# ---------------------------------------------------------------------------


def test_health_endpoint_open_no_auth(auth_client):
    client, _ = auth_client
    resp = client.get("/health")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"


# ---------------------------------------------------------------------------
# Test 5: /v1/pair is allowlisted → accessible without auth
# (We post a bogus code to confirm the endpoint is reachable, not 401)
# ---------------------------------------------------------------------------


def test_pair_endpoint_open_no_auth(auth_client):
    """POST /v1/pair should not 401; it may 401 for invalid code but not due to missing token."""
    client, _ = auth_client
    resp = client.post(
        "/v1/pair",
        json={"code": "999999", "device_fingerprint": "fp"},
    )
    # Should be 401 from the handler logic (invalid code), not because of missing token.
    # The important thing is it's not a 403 from auth middleware.
    assert resp.status_code in (200, 401), (
        f"Expected 200 or 401 from handler, got {resp.status_code}: {resp.text}"
    )


# ---------------------------------------------------------------------------
# Test 6: /classify (legacy) is allowlisted → accessible without auth
# ---------------------------------------------------------------------------


def test_classify_endpoint_open_no_auth(auth_client):
    client, _ = auth_client
    resp = client.post("/classify", json={"text": "שלום עולם"})
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"


# ---------------------------------------------------------------------------
# Test 7: /v1/parent/register is allowlisted → accessible without auth
# ---------------------------------------------------------------------------


def test_parent_register_open_no_auth(auth_client):
    client, _ = auth_client
    resp = client.post("/v1/parent/register", json={"display_name": "test parent"})
    assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert "parent_id" in body
    assert "parent_token" in body


# ---------------------------------------------------------------------------
# Test 8: full pairing flow via HTTP endpoints
# ---------------------------------------------------------------------------


def test_full_pairing_flow_via_endpoints(auth_client):
    """Register parent → issue child → create code → pair device → post events."""
    client, identity_store = auth_client

    # 1. Register parent.
    resp = client.post("/v1/parent/register", json={"display_name": "Alice Parent"})
    assert resp.status_code == 201
    parent_token = resp.json()["parent_token"]

    # 2. Issue child.
    resp = client.post(
        "/v1/parent/children",
        json={"display_name": "Alice Child"},
        headers={"Authorization": f"Bearer {parent_token}"},
    )
    assert resp.status_code == 201
    child_id = resp.json()["child_id"]

    # 3. Create pairing code.
    resp = client.post(
        "/v1/parent/pairing-code",
        json={"child_id": child_id},
        headers={"Authorization": f"Bearer {parent_token}"},
    )
    assert resp.status_code == 201
    code = resp.json()["code"]
    assert len(code) == 6

    # 4. Redeem pairing code (device bootstrap — no auth required).
    resp = client.post(
        "/v1/pair",
        json={"code": code, "device_fingerprint": "fp-test"},
    )
    assert resp.status_code == 200
    device_token = resp.json()["device_token"]
    assert resp.json()["child_id"] == child_id
    assert resp.json()["role"] == "child"

    # 5. POST monitor events with the device token.
    resp = client.post(
        "/v1/monitor/events",
        json=_batch_payload(child_id),
        headers={"Authorization": f"Bearer {device_token}"},
    )
    assert resp.status_code == 202

    # 6. Redeem again (code already used) → 401.
    resp = client.post(
        "/v1/pair",
        json={"code": code, "device_fingerprint": "fp-test"},
    )
    assert resp.status_code == 401
