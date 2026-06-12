"""Tests for S4 parent review/react API.

Covers (via FastAPI TestClient + InMemory adapters):
  Store-level:
    - set_parent_severity parametrized over InMemory + Sqlite adapters
  Endpoint:
    - GET /v1/parent/alerts         — list across all children; filter by child_id
    - GET /v1/parent/alerts/{id}    — detail; 404 for unknown/non-owned
    - POST /v1/parent/alerts/{id}/react — acknowledge, label, severity; 422 on missing field
    - GET /v1/parent/labels/export  — only labeled events returned
  Auth:
    - No token → 401
    - Child-role token → 403
    - Parent sees only their own children's events; another parent's flag → 404

Run from repo root:
    .\\server\\.venv\\Scripts\\python.exe -m pytest server/tests/parent/ -q
"""

from __future__ import annotations

import sys
import time
import uuid
from pathlib import Path

import pytest
import pytest_asyncio

_SERVER_DIR = str(Path(__file__).resolve().parents[2])
if _SERVER_DIR not in sys.path:
    sys.path.insert(0, _SERVER_DIR)

from fastapi.testclient import TestClient

from app.main import app
from app.flagged import FlaggedEventStore, FlaggedEvent, InMemoryFlaggedEventStore
from app.flagged.sqlite_adapter import SqliteFlaggedEventStore
from app.identity.in_memory_adapter import InMemoryIdentityStore
from app.schemas import HealthState


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_event(
    flag_id: str = "f-001",
    child_id: str = "child-1",
    status: str = "alerted",
    created_at: float | None = None,
    label: str = "abusive",
    parent_label: str | None = None,
    parent_severity: str | None = None,
) -> FlaggedEvent:
    return FlaggedEvent(
        flag_id=flag_id,
        child_id=child_id,
        created_at=created_at or time.time(),
        app_package="com.whatsapp",
        direction="inbound",
        label=label,  # type: ignore[arg-type]
        severity="medium",  # type: ignore[arg-type]
        quote="הודעה פוגענית לדוגמה",
        explanation="זוהתה הודעה פוגענית מסוג abusive.",
        source="frontline_direct",  # type: ignore[arg-type]
        trace_id="trace-001",
        status=status,  # type: ignore[arg-type]
        parent_label=parent_label,
        parent_severity=parent_severity,
    )


# ---------------------------------------------------------------------------
# Store-level tests for set_parent_severity (parametrized over both adapters)
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture(params=["memory", "sqlite"])
async def store(request, tmp_path) -> FlaggedEventStore:
    """Yield a FlaggedEventStore implementation (parametrized)."""
    if request.param == "sqlite":
        db_path = str(tmp_path / "flagged_sev_test.db")
        s = SqliteFlaggedEventStore(db_path=db_path)
        await s.initialize()
        yield s
        await s.close()
    else:
        yield InMemoryFlaggedEventStore()


@pytest.mark.asyncio
async def test_set_parent_severity_persists(store):
    """set_parent_severity stores severity and transitions to 'labeled'."""
    await store.record(_make_event("f-sev-01", status="alerted"))

    result = await store.set_parent_severity("f-sev-01", severity="high")
    assert result is True

    updated = await store.get("f-sev-01")
    assert updated is not None
    assert updated.parent_severity == "high"
    assert updated.status == "labeled"


@pytest.mark.asyncio
async def test_set_parent_severity_not_found(store):
    """set_parent_severity returns False for unknown flag_id."""
    result = await store.set_parent_severity("nonexistent", severity="high")
    assert result is False


@pytest.mark.asyncio
async def test_set_parent_severity_does_not_clear_label(store):
    """set_parent_severity does not overwrite an existing parent_label."""
    await store.record(_make_event("f-sev-02", status="review_needed"))
    # First apply a label.
    await store.set_parent_label("f-sev-02", label="offensive", severity=None)

    # Then apply severity separately.
    await store.set_parent_severity("f-sev-02", severity="critical")

    updated = await store.get("f-sev-02")
    # label must be preserved.
    assert updated.parent_label == "offensive"
    # severity must be set.
    assert updated.parent_severity == "critical"


# ---------------------------------------------------------------------------
# Fixtures: TestClient with InMemory adapters
# ---------------------------------------------------------------------------


def _patch_state(client, identity, flagged):
    """Inject test-scoped adapters into app.state after TestClient start."""
    state = client.app.state
    state.identity = identity
    state.flagged = flagged


@pytest.fixture
def parent_client(monkeypatch, tmp_path):
    """TestClient with InMemory adapters; yields (client, identity, flagged)."""
    monkeypatch.setenv("AUDIT_DB_PATH", str(tmp_path / "audit.db"))
    monkeypatch.setenv("CONTEXT_AGENT_ENABLED", "false")
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "99999")
    monkeypatch.setenv("IDENTITY_BACKEND", "memory")
    monkeypatch.setenv("FLAGGED_BACKEND", "memory")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    import asyncio

    identity = InMemoryIdentityStore()
    flagged = InMemoryFlaggedEventStore()

    with TestClient(app, raise_server_exceptions=True) as client:
        _patch_state(client, identity, flagged)
        yield client, identity, flagged


# ---------------------------------------------------------------------------
# Helper: set up a parent + child + optional flagged event
# ---------------------------------------------------------------------------


def _setup_parent_and_child(identity: InMemoryIdentityStore) -> tuple[str, str, str]:
    """Register parent + child; return (parent_id, parent_token, child_id)."""
    import asyncio

    loop = asyncio.new_event_loop()
    try:
        async def _run():
            parent_id, parent_token = await identity.register_parent("Test Parent")
            child = await identity.issue_child(parent_id, "Test Child")
            return parent_id, parent_token, child.child_id

        return loop.run_until_complete(_run())
    finally:
        loop.close()


def _seed_event(flagged: InMemoryFlaggedEventStore, event: FlaggedEvent) -> None:
    """Synchronously seed a flagged event into the store."""
    import asyncio

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(flagged.record(event))
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Auth tests: no token → 401, child token → 403
# ---------------------------------------------------------------------------


def test_list_alerts_no_token_returns_401(parent_client):
    client, identity, flagged = parent_client
    resp = client.get("/v1/parent/alerts")
    assert resp.status_code == 401, resp.text


def test_list_alerts_child_token_returns_403(parent_client):
    """A child-role token cannot access parent alert endpoints."""
    client, identity, flagged = parent_client
    import asyncio

    loop = asyncio.new_event_loop()
    try:
        async def _setup():
            parent_id, _ = await identity.register_parent("P")
            child = await identity.issue_child(parent_id, "C")
            pc = await identity.create_pairing_code(parent_id, child.child_id)
            ctx = await identity.redeem_pairing_code(pc.code, "fp")
            return ctx.device_token

        child_token = loop.run_until_complete(_setup())
    finally:
        loop.close()

    resp = client.get(
        "/v1/parent/alerts",
        headers={"Authorization": f"Bearer {child_token}"},
    )
    assert resp.status_code == 403, resp.text


def test_get_alert_no_token_returns_401(parent_client):
    client, identity, flagged = parent_client
    resp = client.get("/v1/parent/alerts/some-flag-id")
    assert resp.status_code == 401, resp.text


def test_react_no_token_returns_401(parent_client):
    client, identity, flagged = parent_client
    resp = client.post(
        "/v1/parent/alerts/some-flag-id/react",
        json={"action": "acknowledge"},
    )
    assert resp.status_code == 401, resp.text


# ---------------------------------------------------------------------------
# GET /v1/parent/alerts — list
# ---------------------------------------------------------------------------


def test_list_alerts_empty_for_no_events(parent_client):
    """A parent with children but no flagged events gets an empty list."""
    client, identity, flagged = parent_client
    _, parent_token, _ = _setup_parent_and_child(identity)

    resp = client.get(
        "/v1/parent/alerts",
        headers={"Authorization": f"Bearer {parent_token}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == []


def test_list_alerts_returns_events_for_own_children(parent_client):
    """Parent sees their own children's flagged events."""
    client, identity, flagged = parent_client
    parent_id, parent_token, child_id = _setup_parent_and_child(identity)

    evt = _make_event("f-list-01", child_id=child_id, status="alerted")
    _seed_event(flagged, evt)

    resp = client.get(
        "/v1/parent/alerts",
        headers={"Authorization": f"Bearer {parent_token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data) == 1
    assert data[0]["flag_id"] == "f-list-01"
    assert data[0]["child_id"] == child_id


def test_list_alerts_different_parent_sees_empty(parent_client):
    """A different parent cannot see another parent's events (gets empty list)."""
    client, identity, flagged = parent_client
    import asyncio

    loop = asyncio.new_event_loop()
    try:
        async def _setup():
            # Parent A + child + event.
            pid_a, tok_a = await identity.register_parent("Parent A")
            child_a = await identity.issue_child(pid_a, "Child A")
            # Parent B.
            pid_b, tok_b = await identity.register_parent("Parent B")
            return child_a.child_id, tok_a, tok_b

        child_id_a, tok_a, tok_b = loop.run_until_complete(_setup())
    finally:
        loop.close()

    evt = _make_event("f-other-01", child_id=child_id_a, status="alerted")
    _seed_event(flagged, evt)

    # Parent B queries — no children, so empty list.
    resp = client.get(
        "/v1/parent/alerts",
        headers={"Authorization": f"Bearer {tok_b}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == []


def test_list_alerts_filter_by_child_id(parent_client):
    """child_id filter restricts to only that child's events."""
    client, identity, flagged = parent_client
    import asyncio

    loop = asyncio.new_event_loop()
    try:
        async def _setup():
            pid, tok = await identity.register_parent("P")
            child_a = await identity.issue_child(pid, "A")
            child_b = await identity.issue_child(pid, "B")
            return tok, child_a.child_id, child_b.child_id

        tok, cid_a, cid_b = loop.run_until_complete(_setup())
    finally:
        loop.close()

    _seed_event(flagged, _make_event("f-ca-01", child_id=cid_a))
    _seed_event(flagged, _make_event("f-cb-01", child_id=cid_b))

    resp = client.get(
        "/v1/parent/alerts",
        params={"child_id": cid_a},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data) == 1
    assert data[0]["flag_id"] == "f-ca-01"


def test_list_alerts_filter_by_child_id_not_owned_returns_403(parent_client):
    """Requesting a child_id not owned by this parent returns 403."""
    client, identity, flagged = parent_client
    import asyncio

    loop = asyncio.new_event_loop()
    try:
        async def _setup():
            pid_a, tok_a = await identity.register_parent("Parent A")
            pid_b, tok_b = await identity.register_parent("Parent B")
            child_b = await identity.issue_child(pid_b, "Child B")
            return tok_a, child_b.child_id

        tok_a, child_b_id = loop.run_until_complete(_setup())
    finally:
        loop.close()

    resp = client.get(
        "/v1/parent/alerts",
        params={"child_id": child_b_id},
        headers={"Authorization": f"Bearer {tok_a}"},
    )
    assert resp.status_code == 403, resp.text


def test_list_alerts_newest_first(parent_client):
    """Events are returned newest-first."""
    client, identity, flagged = parent_client
    _, parent_token, child_id = _setup_parent_and_child(identity)

    now = time.time()
    _seed_event(flagged, _make_event("f-old", child_id=child_id, created_at=now - 200))
    _seed_event(flagged, _make_event("f-new", child_id=child_id, created_at=now))

    resp = client.get(
        "/v1/parent/alerts",
        headers={"Authorization": f"Bearer {parent_token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data[0]["flag_id"] == "f-new"
    assert data[1]["flag_id"] == "f-old"


def test_list_alerts_include_acked_false_by_default(parent_client):
    """Acknowledged events are excluded by default."""
    client, identity, flagged = parent_client
    _, parent_token, child_id = _setup_parent_and_child(identity)

    _seed_event(flagged, _make_event("f-alerted", child_id=child_id, status="alerted"))
    _seed_event(flagged, _make_event("f-acked", child_id=child_id, status="acknowledged"))

    resp = client.get(
        "/v1/parent/alerts",
        headers={"Authorization": f"Bearer {parent_token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    flag_ids = {e["flag_id"] for e in data}
    assert "f-alerted" in flag_ids
    assert "f-acked" not in flag_ids


def test_list_alerts_include_acked_true(parent_client):
    """include_acked=true shows acknowledged events too."""
    client, identity, flagged = parent_client
    _, parent_token, child_id = _setup_parent_and_child(identity)

    _seed_event(flagged, _make_event("f-a2", child_id=child_id, status="alerted"))
    _seed_event(flagged, _make_event("f-ac2", child_id=child_id, status="acknowledged"))

    resp = client.get(
        "/v1/parent/alerts",
        params={"include_acked": "true"},
        headers={"Authorization": f"Bearer {parent_token}"},
    )
    assert resp.status_code == 200, resp.text
    flag_ids = {e["flag_id"] for e in resp.json()}
    assert "f-a2" in flag_ids
    assert "f-ac2" in flag_ids


# ---------------------------------------------------------------------------
# GET /v1/parent/alerts/{id} — detail
# ---------------------------------------------------------------------------


def test_get_alert_detail_happy_path(parent_client):
    """GET detail for an owned flag returns full event fields."""
    client, identity, flagged = parent_client
    _, parent_token, child_id = _setup_parent_and_child(identity)

    evt = _make_event("f-detail-01", child_id=child_id, status="review_needed")
    _seed_event(flagged, evt)

    resp = client.get(
        "/v1/parent/alerts/f-detail-01",
        headers={"Authorization": f"Bearer {parent_token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["flag_id"] == "f-detail-01"
    assert data["child_id"] == child_id
    assert data["status"] == "review_needed"
    assert data["quote"] == "הודעה פוגענית לדוגמה"


def test_get_alert_detail_404_for_unknown(parent_client):
    """GET detail returns 404 for a non-existent flag_id."""
    client, identity, flagged = parent_client
    _, parent_token, _ = _setup_parent_and_child(identity)

    resp = client.get(
        "/v1/parent/alerts/nonexistent-flag-id",
        headers={"Authorization": f"Bearer {parent_token}"},
    )
    assert resp.status_code == 404, resp.text


def test_get_alert_detail_404_for_other_parents_flag(parent_client):
    """GET detail returns 404 (not 403) for a flag belonging to another parent."""
    client, identity, flagged = parent_client
    import asyncio

    loop = asyncio.new_event_loop()
    try:
        async def _setup():
            pid_a, tok_a = await identity.register_parent("Parent A")
            pid_b, tok_b = await identity.register_parent("Parent B")
            child_b = await identity.issue_child(pid_b, "Child B")
            return tok_a, tok_b, child_b.child_id

        tok_a, tok_b, child_b_id = loop.run_until_complete(_setup())
    finally:
        loop.close()

    # Seed event under child B.
    _seed_event(flagged, _make_event("f-other-b", child_id=child_b_id))

    # Parent A tries to access Parent B's flag → 404 (ownership-blind).
    resp = client.get(
        "/v1/parent/alerts/f-other-b",
        headers={"Authorization": f"Bearer {tok_a}"},
    )
    assert resp.status_code == 404, resp.text


# ---------------------------------------------------------------------------
# POST /v1/parent/alerts/{id}/react
# ---------------------------------------------------------------------------


def test_react_acknowledge(parent_client):
    """Acknowledge action sets status='acknowledged' and acknowledged_at."""
    client, identity, flagged = parent_client
    _, parent_token, child_id = _setup_parent_and_child(identity)

    _seed_event(flagged, _make_event("f-ack-01", child_id=child_id, status="alerted"))

    resp = client.post(
        "/v1/parent/alerts/f-ack-01/react",
        json={"action": "acknowledge"},
        headers={"Authorization": f"Bearer {parent_token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["status"] == "acknowledged"
    assert data["acknowledged_at"] is not None


def test_react_label_sets_parent_label(parent_client):
    """Label action persists parent_label and sets status='labeled'."""
    client, identity, flagged = parent_client
    _, parent_token, child_id = _setup_parent_and_child(identity)

    _seed_event(flagged, _make_event("f-lbl-01", child_id=child_id, status="review_needed"))

    resp = client.post(
        "/v1/parent/alerts/f-lbl-01/react",
        json={"action": "label", "label": "offensive"},
        headers={"Authorization": f"Bearer {parent_token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["parent_label"] == "offensive"
    assert data["status"] == "labeled"


def test_react_label_not_offensive(parent_client):
    """Label action with 'not_offensive' stores correctly."""
    client, identity, flagged = parent_client
    _, parent_token, child_id = _setup_parent_and_child(identity)

    _seed_event(flagged, _make_event("f-lbl-02", child_id=child_id, status="review_needed"))

    resp = client.post(
        "/v1/parent/alerts/f-lbl-02/react",
        json={"action": "label", "label": "not_offensive"},
        headers={"Authorization": f"Bearer {parent_token}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["parent_label"] == "not_offensive"


def test_react_severity_sets_parent_severity(parent_client):
    """Severity action persists parent_severity and sets status='labeled'."""
    client, identity, flagged = parent_client
    _, parent_token, child_id = _setup_parent_and_child(identity)

    _seed_event(flagged, _make_event("f-sev-e01", child_id=child_id, status="alerted"))

    resp = client.post(
        "/v1/parent/alerts/f-sev-e01/react",
        json={"action": "severity", "severity": "critical"},
        headers={"Authorization": f"Bearer {parent_token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["parent_severity"] == "critical"
    assert data["status"] == "labeled"


def test_react_label_missing_label_field_returns_422(parent_client):
    """'label' action without label field returns 422."""
    client, identity, flagged = parent_client
    _, parent_token, child_id = _setup_parent_and_child(identity)

    _seed_event(flagged, _make_event("f-val-01", child_id=child_id))

    resp = client.post(
        "/v1/parent/alerts/f-val-01/react",
        json={"action": "label"},  # missing label field
        headers={"Authorization": f"Bearer {parent_token}"},
    )
    assert resp.status_code == 422, resp.text


def test_react_severity_missing_severity_field_returns_422(parent_client):
    """'severity' action without severity field returns 422."""
    client, identity, flagged = parent_client
    _, parent_token, child_id = _setup_parent_and_child(identity)

    _seed_event(flagged, _make_event("f-val-02", child_id=child_id))

    resp = client.post(
        "/v1/parent/alerts/f-val-02/react",
        json={"action": "severity"},  # missing severity field
        headers={"Authorization": f"Bearer {parent_token}"},
    )
    assert resp.status_code == 422, resp.text


def test_react_404_for_unknown_flag(parent_client):
    """React returns 404 for a non-existent flag."""
    client, identity, flagged = parent_client
    _, parent_token, _ = _setup_parent_and_child(identity)

    resp = client.post(
        "/v1/parent/alerts/nonexistent-flag/react",
        json={"action": "acknowledge"},
        headers={"Authorization": f"Bearer {parent_token}"},
    )
    assert resp.status_code == 404, resp.text


def test_react_404_for_other_parents_flag(parent_client):
    """React returns 404 for a flag belonging to another parent's child."""
    client, identity, flagged = parent_client
    import asyncio

    loop = asyncio.new_event_loop()
    try:
        async def _setup():
            pid_a, tok_a = await identity.register_parent("Parent A")
            pid_b, tok_b = await identity.register_parent("Parent B")
            child_b = await identity.issue_child(pid_b, "Child B")
            return tok_a, child_b.child_id

        tok_a, child_b_id = loop.run_until_complete(_setup())
    finally:
        loop.close()

    _seed_event(flagged, _make_event("f-react-other", child_id=child_b_id))

    resp = client.post(
        "/v1/parent/alerts/f-react-other/react",
        json={"action": "acknowledge"},
        headers={"Authorization": f"Bearer {tok_a}"},
    )
    assert resp.status_code == 404, resp.text


def test_react_label_persisted_after_store_mutation(parent_client):
    """After a label react, GET detail reflects the persisted parent_label."""
    client, identity, flagged = parent_client
    _, parent_token, child_id = _setup_parent_and_child(identity)

    _seed_event(flagged, _make_event("f-persist-01", child_id=child_id, status="review_needed"))

    # Apply label.
    resp = client.post(
        "/v1/parent/alerts/f-persist-01/react",
        json={"action": "label", "label": "offensive", "severity": "high"},
        headers={"Authorization": f"Bearer {parent_token}"},
    )
    assert resp.status_code == 200

    # Verify via GET detail.
    resp2 = client.get(
        "/v1/parent/alerts/f-persist-01",
        headers={"Authorization": f"Bearer {parent_token}"},
    )
    assert resp2.status_code == 200
    data = resp2.json()
    assert data["parent_label"] == "offensive"
    assert data["parent_severity"] == "high"
    assert data["status"] == "labeled"


# ---------------------------------------------------------------------------
# GET /v1/parent/labels/export
# ---------------------------------------------------------------------------


def test_export_labels_returns_only_labeled_events(parent_client):
    """Export returns only events with parent_label set."""
    client, identity, flagged = parent_client
    _, parent_token, child_id = _setup_parent_and_child(identity)

    # Seed: one labeled, one alerted without label.
    _seed_event(
        flagged,
        _make_event(
            "f-exp-labeled",
            child_id=child_id,
            status="labeled",
            parent_label="offensive",
        ),
    )
    _seed_event(flagged, _make_event("f-exp-alerted", child_id=child_id, status="alerted"))

    resp = client.get(
        "/v1/parent/labels/export",
        headers={"Authorization": f"Bearer {parent_token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data) == 1
    item = data[0]
    assert item["parent_label"] == "offensive"
    assert "quote" in item
    assert "label" in item
    assert "severity" in item
    assert "app_package" in item
    assert "direction" in item
    assert "created_at" in item


def test_export_labels_empty_when_no_labeled_events(parent_client):
    """Export returns an empty list when no parent labels exist."""
    client, identity, flagged = parent_client
    _, parent_token, child_id = _setup_parent_and_child(identity)

    _seed_event(flagged, _make_event("f-noexp-01", child_id=child_id, status="alerted"))

    resp = client.get(
        "/v1/parent/labels/export",
        headers={"Authorization": f"Bearer {parent_token}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == []


def test_export_labels_no_token_returns_401(parent_client):
    client, identity, flagged = parent_client
    resp = client.get("/v1/parent/labels/export")
    assert resp.status_code == 401, resp.text


def test_export_labels_only_own_children(parent_client):
    """Export only includes events from this parent's children."""
    client, identity, flagged = parent_client
    import asyncio

    loop = asyncio.new_event_loop()
    try:
        async def _setup():
            pid_a, tok_a = await identity.register_parent("Parent A")
            pid_b, tok_b = await identity.register_parent("Parent B")
            child_a = await identity.issue_child(pid_a, "Child A")
            child_b = await identity.issue_child(pid_b, "Child B")
            return tok_a, child_a.child_id, child_b.child_id

        tok_a, cid_a, cid_b = loop.run_until_complete(_setup())
    finally:
        loop.close()

    _seed_event(
        flagged,
        _make_event("f-exp-a", child_id=cid_a, status="labeled", parent_label="offensive"),
    )
    _seed_event(
        flagged,
        _make_event("f-exp-b", child_id=cid_b, status="labeled", parent_label="offensive"),
    )

    # Parent A should only see their own child's label.
    resp = client.get(
        "/v1/parent/labels/export",
        headers={"Authorization": f"Bearer {tok_a}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    # Only child_a's event should be returned (implicitly by isolation).
    # We can check that f-exp-b's data isn't in the list by checking quote doesn't
    # appear for a cross-parent child; since quotes are the same, check count.
    assert len(data) == 1


# ---------------------------------------------------------------------------
# Bug-fix tests (A–D)
# ---------------------------------------------------------------------------
# These tests cover the 4 bugs fixed in the 2026-06-09 parent-alerts extension:
#   A — status filter was ignored (post-filtered after include_acked excluded rows)
#   B — confidence missing from payload
#   C — CA trace not exposed on detail endpoint
#   D — source/explanation mis-stamped on CA-escalated events


def _make_event_with_confidence(
    flag_id: str = "f-conf-01",
    child_id: str = "child-1",
    status: str = "alerted",
    confidence: float | None = 0.92,
    label: str = "abusive",
) -> FlaggedEvent:
    """Build a FlaggedEvent with a confidence value set."""
    return FlaggedEvent(
        flag_id=flag_id,
        child_id=child_id,
        created_at=time.time(),
        app_package="com.whatsapp",
        direction="inbound",
        label=label,  # type: ignore[arg-type]
        severity="medium",  # type: ignore[arg-type]
        quote="הודעה פוגענית",
        explanation="זוהתה הודעה פוגענית מסוג abusive.",
        source="frontline_direct",  # type: ignore[arg-type]
        trace_id="trace-conf-01",
        status=status,  # type: ignore[arg-type]
        confidence=confidence,
    )


# --- Bug A: status filter ---

def test_status_filter_alerted_returns_only_alerted(parent_client):
    """?status=alerted returns ONLY alerted events — not acknowledged ones."""
    client, identity, flagged = parent_client
    _, parent_token, child_id = _setup_parent_and_child(identity)

    _seed_event(flagged, _make_event("f-sa-alerted", child_id=child_id, status="alerted"))
    _seed_event(flagged, _make_event("f-sa-acked", child_id=child_id, status="acknowledged"))
    _seed_event(flagged, _make_event("f-sa-review", child_id=child_id, status="review_needed"))

    resp = client.get(
        "/v1/parent/alerts",
        params={"status": "alerted"},
        headers={"Authorization": f"Bearer {parent_token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    flag_ids = {e["flag_id"] for e in data}
    assert flag_ids == {"f-sa-alerted"}, (
        f"Expected only alerted events; got {flag_ids}"
    )


def test_status_filter_acknowledged_returns_only_acknowledged(parent_client):
    """?status=acknowledged returns ONLY acknowledged events (bug A regression)."""
    client, identity, flagged = parent_client
    _, parent_token, child_id = _setup_parent_and_child(identity)

    _seed_event(flagged, _make_event("f-sack-alerted", child_id=child_id, status="alerted"))
    _seed_event(flagged, _make_event("f-sack-acked", child_id=child_id, status="acknowledged"))

    resp = client.get(
        "/v1/parent/alerts",
        params={"status": "acknowledged"},
        headers={"Authorization": f"Bearer {parent_token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    flag_ids = {e["flag_id"] for e in data}
    assert flag_ids == {"f-sack-acked"}, (
        f"Expected only acknowledged events; got {flag_ids}"
    )


def test_status_filter_review_needed_returns_only_review_needed(parent_client):
    """?status=review_needed returns ONLY review_needed events."""
    client, identity, flagged = parent_client
    _, parent_token, child_id = _setup_parent_and_child(identity)

    _seed_event(flagged, _make_event("f-srn-alerted", child_id=child_id, status="alerted"))
    _seed_event(flagged, _make_event("f-srn-review", child_id=child_id, status="review_needed"))
    _seed_event(flagged, _make_event("f-srn-labeled", child_id=child_id, status="labeled"))

    resp = client.get(
        "/v1/parent/alerts",
        params={"status": "review_needed"},
        headers={"Authorization": f"Bearer {parent_token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    flag_ids = {e["flag_id"] for e in data}
    assert flag_ids == {"f-srn-review"}, (
        f"Expected only review_needed events; got {flag_ids}"
    )


def test_status_filter_labeled_returns_only_labeled(parent_client):
    """?status=labeled returns ONLY labeled events."""
    client, identity, flagged = parent_client
    _, parent_token, child_id = _setup_parent_and_child(identity)

    _seed_event(
        flagged,
        _make_event("f-slb-labeled", child_id=child_id, status="labeled", parent_label="offensive"),
    )
    _seed_event(flagged, _make_event("f-slb-alerted", child_id=child_id, status="alerted"))

    resp = client.get(
        "/v1/parent/alerts",
        params={"status": "labeled"},
        headers={"Authorization": f"Bearer {parent_token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    flag_ids = {e["flag_id"] for e in data}
    assert flag_ids == {"f-slb-labeled"}, (
        f"Expected only labeled events; got {flag_ids}"
    )


def test_status_filter_unknown_value_returns_empty(parent_client):
    """?status=<nonexistent_value> returns an empty list (no match)."""
    client, identity, flagged = parent_client
    _, parent_token, child_id = _setup_parent_and_child(identity)

    _seed_event(flagged, _make_event("f-sunk-alerted", child_id=child_id, status="alerted"))

    resp = client.get(
        "/v1/parent/alerts",
        params={"status": "nonexistent_status"},
        headers={"Authorization": f"Bearer {parent_token}"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == []


# --- Bug B: confidence in payload ---

def test_list_alerts_includes_confidence_when_set(parent_client):
    """confidence field is present and correct in the list payload."""
    client, identity, flagged = parent_client
    _, parent_token, child_id = _setup_parent_and_child(identity)

    evt = _make_event_with_confidence("f-conf-list", child_id=child_id, confidence=0.87)
    _seed_event(flagged, evt)

    resp = client.get(
        "/v1/parent/alerts",
        headers={"Authorization": f"Bearer {parent_token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data) == 1
    assert "confidence" in data[0], "confidence field missing from list payload"
    assert abs(data[0]["confidence"] - 0.87) < 0.001


def test_list_alerts_confidence_is_null_when_not_set(parent_client):
    """confidence is null (not missing) when the event has no confidence stored."""
    client, identity, flagged = parent_client
    _, parent_token, child_id = _setup_parent_and_child(identity)

    # FlaggedEvent with confidence=None (old-style events before this field was added).
    evt = _make_event_with_confidence("f-noconf", child_id=child_id, confidence=None)
    _seed_event(flagged, evt)

    resp = client.get(
        "/v1/parent/alerts",
        headers={"Authorization": f"Bearer {parent_token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data) == 1
    assert "confidence" in data[0], "confidence key missing from payload"
    assert data[0]["confidence"] is None


def test_detail_includes_confidence(parent_client):
    """confidence is also present in the GET detail payload."""
    client, identity, flagged = parent_client
    _, parent_token, child_id = _setup_parent_and_child(identity)

    evt = _make_event_with_confidence("f-conf-det", child_id=child_id, confidence=0.65)
    _seed_event(flagged, evt)

    resp = client.get(
        "/v1/parent/alerts/f-conf-det",
        headers={"Authorization": f"Bearer {parent_token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "confidence" in data
    assert abs(data["confidence"] - 0.65) < 0.001


# --- Bug C: CA trace on detail ---

def test_detail_ca_fields_are_null_when_no_ca_ran(parent_client):
    """CA fields (context_used, is_real_threat, etc.) are null when no CA ran."""
    client, identity, flagged = parent_client
    _, parent_token, child_id = _setup_parent_and_child(identity)

    evt = _make_event("f-noca", child_id=child_id, status="alerted")
    _seed_event(flagged, evt)

    resp = client.get(
        "/v1/parent/alerts/f-noca",
        headers={"Authorization": f"Bearer {parent_token}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    # All CA fields must be present as keys (not absent) and null.
    for field in ("context_used", "is_real_threat", "ca_severity", "ca_reasoning", "ca_model"):
        assert field in data, f"field '{field}' missing from detail payload"
        assert data[field] is None, f"expected null for '{field}' when no CA ran"


def test_detail_ca_fields_populated_when_audit_store_has_trace(parent_client, monkeypatch):
    """CA fields are populated from the audit store when an agent trace exists."""
    import asyncio

    client, identity, flagged = parent_client
    _, parent_token, child_id = _setup_parent_and_child(identity)

    trace_id = "trace-ca-test-001"
    evt = FlaggedEvent(
        flag_id="f-ca-trace",
        child_id=child_id,
        created_at=time.time(),
        app_package="com.telegram",
        direction="inbound",
        label="violence",  # type: ignore[arg-type]
        severity="high",  # type: ignore[arg-type]
        quote="הודעה אלימה",
        explanation="ה-CA זיהה איום ממשי.",
        source="context_agent",  # type: ignore[arg-type]
        trace_id=trace_id,
        status="alerted",  # type: ignore[arg-type]
        confidence=0.88,
    )
    _seed_event(flagged, evt)

    # Patch the audit store on the running app to return a fake CA trace.
    ca_trace = {
        "is_real_threat": 1,
        "severity": "high",
        "explanation": "ה-CA זיהה שהייתה כוונה אמיתית לאלימות.",
        "review_flag": 0,
        "model_used": "gemini-2.5-flash",
        "tools_called_json": '[{"name": "read_history"}, {"name": "is_real_threat"}]',
        "reasoning_trace": "ניתחתי את ההקשר וזיהיתי איום ממשי.",
    }

    class _MockAuditStore:
        async def read_agent_trace_for(self, tid: str):
            if tid == trace_id:
                return ca_trace
            return None

    loop = asyncio.new_event_loop()
    try:
        # Inject the mock audit store into app.state.
        client.app.state.audit_store = _MockAuditStore()

        resp = client.get(
            "/v1/parent/alerts/f-ca-trace",
            headers={"Authorization": f"Bearer {parent_token}"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()

        assert data["context_used"] is True, "read_history was called → context_used must be True"
        assert data["is_real_threat"] is True
        assert data["ca_severity"] == "high"
        assert data["ca_model"] == "gemini-2.5-flash"
        assert data["ca_reasoning"] is not None and len(data["ca_reasoning"]) > 0
    finally:
        loop.close()


# --- Bug D: source + explanation stamping in MonitorIngest ---

def test_ingest_source_stamping_frontline_direct():
    """MonitorIngest stamps source=frontline_direct when no CA ran (ALERT_DIRECT)."""
    import asyncio
    from app.flagged.in_memory_adapter import InMemoryFlaggedEventStore
    from app.dedup.null_adapter import NullDedupStore
    from app.monitor.ingest import MonitorIngest
    from app.schemas import (
        ClassificationResult,
        MonitorBatchRequest,
        MonitorEvent,
        TriageDecision,
    )
    from app.alerts.severity import derive_severity

    flagged_store = InMemoryFlaggedEventStore()
    captured: list = []

    async def fake_pipeline(request, text, *, trace_id, child_id, message_id, input_type, **kwargs):
        result = ClassificationResult(
            label="abusive",
            confidence=0.95,
            is_offensive=True,
            model_version="stub",
            latency_ms=1.0,
            is_borderline=False,
            raw_confidence=0.95,
        )
        # No CA ran → 3-tuple with ctx_decision=None
        return result, TriageDecision.ALERT_DIRECT, None

    monitor = MonitorIngest(
        pipeline_fn=fake_pipeline,
        dedup=NullDedupStore(),
        flagged=flagged_store,
        derive_severity=derive_severity,
    )

    class _FakeRequest:
        class app:
            class state:
                pass
        class state:
            audit = {}

    batch = MonitorBatchRequest(
        session_id="s1",
        child_id="child-d1",
        events=[
            MonitorEvent(
                client_msg_id="msg-d1",
                app_package="com.whatsapp",
                text="אני אהרוג אותך",
                text_hash="abc123",
                captured_at=time.time(),
                direction="inbound",
            )
        ],
    )

    loop = asyncio.new_event_loop()
    try:
        resp = loop.run_until_complete(
            monitor.ingest_batch(_FakeRequest(), batch, trace_id="trace-d1")
        )
    finally:
        loop.close()

    assert resp.flagged == 1

    loop2 = asyncio.new_event_loop()
    try:
        events = loop2.run_until_complete(
            flagged_store.list_for_child("child-d1", include_acked=True)
        )
    finally:
        loop2.close()

    assert len(events) == 1
    evt = events[0]
    assert evt.source == "frontline_direct", f"Expected frontline_direct, got {evt.source}"
    assert evt.confidence is not None
    assert abs(evt.confidence - 0.95) < 0.001


def test_ingest_source_stamping_context_agent():
    """MonitorIngest stamps source=context_agent when the CA ran and confirmed a threat."""
    import asyncio
    from app.flagged.in_memory_adapter import InMemoryFlaggedEventStore
    from app.dedup.null_adapter import NullDedupStore
    from app.monitor.ingest import MonitorIngest
    from app.schemas import (
        ClassificationResult,
        ContextDecision,
        MonitorBatchRequest,
        MonitorEvent,
        TriageDecision,
    )
    from app.alerts.severity import derive_severity

    flagged_store = InMemoryFlaggedEventStore()
    ca_explanation = "ה-CA זיהה איום ממשי בהקשר הצ'אט."

    async def fake_pipeline_with_ca(request, text, *, trace_id, child_id, message_id, input_type, **kwargs):
        result = ClassificationResult(
            label="violence",
            confidence=0.72,
            is_offensive=True,
            model_version="stub",
            latency_ms=1.0,
            is_borderline=True,
            raw_confidence=0.72,
        )
        ctx = ContextDecision(
            is_real_threat=True,
            severity="high",
            explanation=ca_explanation,
            model_used="gemini-2.5-flash",
            tools_called=("read_history", "is_real_threat"),
        )
        # CA ran → 3-tuple with ctx_decision set
        return result, TriageDecision.ALERT_DIRECT, ctx

    monitor = MonitorIngest(
        pipeline_fn=fake_pipeline_with_ca,
        dedup=NullDedupStore(),
        flagged=flagged_store,
        derive_severity=derive_severity,
    )

    class _FakeRequest:
        class app:
            class state:
                pass
        class state:
            audit = {}

    batch = MonitorBatchRequest(
        session_id="s2",
        child_id="child-d2",
        events=[
            MonitorEvent(
                client_msg_id="msg-d2",
                app_package="com.telegram",
                text="אני אהרוג אותך",
                text_hash="xyz789",
                captured_at=time.time(),
                direction="inbound",
            )
        ],
    )

    loop = asyncio.new_event_loop()
    try:
        resp = loop.run_until_complete(
            monitor.ingest_batch(_FakeRequest(), batch, trace_id="trace-d2")
        )
    finally:
        loop.close()

    assert resp.flagged == 1

    loop2 = asyncio.new_event_loop()
    try:
        events = loop2.run_until_complete(
            flagged_store.list_for_child("child-d2", include_acked=True)
        )
    finally:
        loop2.close()

    assert len(events) == 1
    evt = events[0]
    assert evt.source == "context_agent", (
        f"Expected context_agent, got {evt.source!r}. "
        "This is bug D: source was mis-stamped as frontline_direct."
    )
    assert evt.explanation == ca_explanation, (
        f"Expected CA explanation, got {evt.explanation!r}. "
        "This is bug D: explanation was the generic template instead of CA's."
    )
    assert evt.severity == "high", (
        f"Expected CA severity 'high', got {evt.severity!r}"
    )
