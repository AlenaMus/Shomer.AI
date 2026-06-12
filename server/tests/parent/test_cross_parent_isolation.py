"""Cross-parent / cross-child isolation tests for the parent review API.

Proves that no parent can ever see another parent's children's flagged events.

Scenarios:
  - Parent A authenticates and can list only their own children's events.
  - Parent B authenticates and sees only their own events (not Parent A's).
  - Parent A trying to access Parent B's specific flag_id gets 404 (not 403),
    to prevent enumeration of flag IDs across parents.
  - A child-role token is rejected with 403 on all parent endpoints.

Run from repo root:
    .\\server\\.venv\\Scripts\\python.exe -m pytest server/tests/parent/test_cross_parent_isolation.py -q
"""

from __future__ import annotations

import asyncio
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
from app.flagged import FlaggedEvent, InMemoryFlaggedEventStore
from app.identity.in_memory_adapter import InMemoryIdentityStore


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _seed_two_parents_with_children() -> tuple:
    """Create two parents, each with one child, and a flagged event per child.

    Returns:
        (store, flagged_store,
         parent_a_token, child_a_id,
         parent_b_token, child_b_id,
         flag_a_id, flag_b_id)
    """
    identity = InMemoryIdentityStore()
    flagged = InMemoryFlaggedEventStore()

    async def _setup():
        # Parent A + child A
        parent_a_id, parent_a_token = await identity.register_parent()
        child_a = await identity.issue_child(parent_a_id, "Child A")
        child_a_id = child_a.child_id

        # Parent B + child B
        parent_b_id, parent_b_token = await identity.register_parent()
        child_b = await identity.issue_child(parent_b_id, "Child B")
        child_b_id = child_b.child_id

        # Flagged event for child A
        flag_a_id = "flag-a-001"
        await flagged.record(FlaggedEvent(
            flag_id=flag_a_id,
            child_id=child_a_id,
            created_at=time.time(),
            app_package="com.whatsapp",
            direction="inbound",
            label="abusive",
            severity="high",
            quote="אתה טמבל",
            explanation="הודעה פוגענית.",
            source="frontline_direct",
            trace_id=str(uuid.uuid4()),
            status="alerted",
            confidence=0.85,
        ))

        # Flagged event for child B
        flag_b_id = "flag-b-001"
        await flagged.record(FlaggedEvent(
            flag_id=flag_b_id,
            child_id=child_b_id,
            created_at=time.time(),
            app_package="org.telegram.messenger",
            direction="inbound",
            label="hate",
            severity="medium",
            quote="שנאה",
            explanation="הודעת שנאה.",
            source="frontline_direct",
            trace_id=str(uuid.uuid4()),
            status="alerted",
            confidence=0.72,
        ))

        return (
            identity, flagged,
            parent_a_token, child_a_id,
            parent_b_token, child_b_id,
            flag_a_id, flag_b_id,
        )

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_setup())
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_parent_a_sees_only_own_child_events(monkeypatch, tmp_path):
    """Parent A must only see events for child A — not child B's events."""
    monkeypatch.setenv("AUDIT_DB_PATH", str(tmp_path / "audit.db"))
    monkeypatch.setenv("CONTEXT_AGENT_ENABLED", "false")
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "99999")
    monkeypatch.setenv("IDENTITY_BACKEND", "memory")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    (
        identity, flagged,
        parent_a_token, child_a_id,
        parent_b_token, child_b_id,
        flag_a_id, flag_b_id,
    ) = _seed_two_parents_with_children()

    with TestClient(app, raise_server_exceptions=True) as client:
        app.state.identity = identity
        app.state.flagged = flagged

        resp = client.get(
            "/v1/parent/alerts",
            headers={"Authorization": f"Bearer {parent_a_token}"},
        )

    assert resp.status_code == 200, f"Got {resp.status_code}: {resp.text}"
    events = resp.json()
    child_ids_in_response = {e["child_id"] for e in events}

    assert child_a_id in child_ids_in_response, (
        f"Parent A should see child A's events; child_ids seen: {child_ids_in_response}"
    )
    assert child_b_id not in child_ids_in_response, (
        f"Parent A must NOT see child B's events; child_ids seen: {child_ids_in_response}"
    )


def test_parent_b_sees_only_own_child_events(monkeypatch, tmp_path):
    """Parent B must only see events for child B — not child A's events."""
    monkeypatch.setenv("AUDIT_DB_PATH", str(tmp_path / "audit.db"))
    monkeypatch.setenv("CONTEXT_AGENT_ENABLED", "false")
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "99999")
    monkeypatch.setenv("IDENTITY_BACKEND", "memory")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    (
        identity, flagged,
        parent_a_token, child_a_id,
        parent_b_token, child_b_id,
        flag_a_id, flag_b_id,
    ) = _seed_two_parents_with_children()

    with TestClient(app, raise_server_exceptions=True) as client:
        app.state.identity = identity
        app.state.flagged = flagged

        resp = client.get(
            "/v1/parent/alerts",
            headers={"Authorization": f"Bearer {parent_b_token}"},
        )

    assert resp.status_code == 200, f"Got {resp.status_code}: {resp.text}"
    events = resp.json()
    child_ids_in_response = {e["child_id"] for e in events}

    assert child_b_id in child_ids_in_response, (
        f"Parent B should see child B's events; child_ids seen: {child_ids_in_response}"
    )
    assert child_a_id not in child_ids_in_response, (
        f"Parent B must NOT see child A's events; child_ids seen: {child_ids_in_response}"
    )


def test_parent_a_cannot_access_parent_b_flag_by_id(monkeypatch, tmp_path):
    """Parent A accessing Parent B's flag_id by ID must get 404 (not 403).

    Ownership-blind 404 prevents enumeration attacks across parents.
    """
    monkeypatch.setenv("AUDIT_DB_PATH", str(tmp_path / "audit.db"))
    monkeypatch.setenv("CONTEXT_AGENT_ENABLED", "false")
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "99999")
    monkeypatch.setenv("IDENTITY_BACKEND", "memory")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    (
        identity, flagged,
        parent_a_token, child_a_id,
        parent_b_token, child_b_id,
        flag_a_id, flag_b_id,
    ) = _seed_two_parents_with_children()

    with TestClient(app, raise_server_exceptions=True) as client:
        app.state.identity = identity
        app.state.flagged = flagged

        # Parent A tries to access Parent B's flag
        resp = client.get(
            f"/v1/parent/alerts/{flag_b_id}",
            headers={"Authorization": f"Bearer {parent_a_token}"},
        )

    assert resp.status_code == 404, (
        f"Expected 404 (ownership-blind) when Parent A accesses Parent B's flag; "
        f"got {resp.status_code}: {resp.text}"
    )


def test_child_role_token_rejected_on_parent_endpoint(monkeypatch, tmp_path):
    """A child-role device token must not be accepted on parent endpoints."""
    monkeypatch.setenv("AUDIT_DB_PATH", str(tmp_path / "audit.db"))
    monkeypatch.setenv("CONTEXT_AGENT_ENABLED", "false")
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "99999")
    monkeypatch.setenv("IDENTITY_BACKEND", "memory")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    identity = InMemoryIdentityStore()
    flagged = InMemoryFlaggedEventStore()

    async def _get_child_token():
        parent_id, _ = await identity.register_parent()
        child = await identity.issue_child(parent_id, "C")
        pc = await identity.create_pairing_code(parent_id, child.child_id)
        ctx = await identity.redeem_pairing_code(pc.code, "fp-child-role")
        return ctx.device_token

    loop = asyncio.new_event_loop()
    try:
        child_token = loop.run_until_complete(_get_child_token())
    finally:
        loop.close()

    with TestClient(app, raise_server_exceptions=True) as client:
        app.state.identity = identity
        app.state.flagged = flagged

        resp = client.get(
            "/v1/parent/alerts",
            headers={"Authorization": f"Bearer {child_token}"},
        )

    assert resp.status_code == 403, (
        f"Expected 403 for child-role token on parent endpoint; "
        f"got {resp.status_code}: {resp.text}"
    )


def test_no_token_rejected_on_parent_endpoint(monkeypatch, tmp_path):
    """No Authorization header must get 401 on parent endpoints."""
    monkeypatch.setenv("AUDIT_DB_PATH", str(tmp_path / "audit.db"))
    monkeypatch.setenv("CONTEXT_AGENT_ENABLED", "false")
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "99999")
    monkeypatch.setenv("IDENTITY_BACKEND", "memory")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    identity = InMemoryIdentityStore()
    flagged = InMemoryFlaggedEventStore()

    with TestClient(app, raise_server_exceptions=True) as client:
        app.state.identity = identity
        app.state.flagged = flagged

        resp = client.get("/v1/parent/alerts")

    assert resp.status_code == 401, (
        f"Expected 401 for missing token; got {resp.status_code}: {resp.text}"
    )
