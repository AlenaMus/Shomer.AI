"""test_digest_endpoint.py — Integration tests for digest endpoints.

Tests (via FastAPI TestClient + app.state injection):
  1. PATCH /v1/device/fcm-token stores the FCM token for an authenticated device.
  2. POST /internal/digest/run builds and saves digests.
  3. GET /v1/parent/digests/{date} returns the digest for the requesting parent.
  4. A different parent gets 403/404 (cannot see another parent's child digests).
  5. GET /v1/parent/digests/{date} returns 404 when no digests exist for the date.

All tests use InMemory adapters (no file I/O).

Run from repo root:
    .\\server\\.venv\\Scripts\\python.exe -m pytest server/tests/digest/test_digest_endpoint.py -q
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

_SERVER_DIR = str(Path(__file__).resolve().parents[2])
if _SERVER_DIR not in sys.path:
    sys.path.insert(0, _SERVER_DIR)

from fastapi.testclient import TestClient

from app.main import app
from app.schemas import AlertResult


# ---------------------------------------------------------------------------
# Helpers — swap app.state adapters for deterministic tests
# ---------------------------------------------------------------------------


class _FakeChannel:
    def __init__(self):
        self.calls = []

    async def send_alert(self, req):
        self.calls.append(req)
        return AlertResult(alert_id="a1", sent=True, channel="stub")

    async def get_alert_history(self, *a, **kw):
        return []

    def health_status(self):
        return {"status": "ok", "queued_alerts": 0}


def _patch_state(client, identity, flagged, digest_scheduler, digest_store, channel):
    """Inject test-scoped adapters into app.state."""
    state = client.app.state
    state.identity = identity
    state.flagged = flagged
    state.digest_scheduler = digest_scheduler
    state.digest_store = digest_store
    state.notifier = channel


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fcm_token_registration_stores_token():
    """PATCH /v1/device/fcm-token stores the FCM token for the authenticated parent device."""
    from app.identity.in_memory_adapter import InMemoryIdentityStore
    from app.flagged.in_memory_adapter import InMemoryFlaggedEventStore
    from app.digest.in_memory_store import InMemoryDigestStore
    from app.digest.manual_runner import ManualDigestRunner

    identity = InMemoryIdentityStore()
    flagged = InMemoryFlaggedEventStore()
    digest_store = InMemoryDigestStore()
    channel = _FakeChannel()

    # Set up a parent.
    parent_id, parent_token = await identity.register_parent("Test Parent")

    async def _parent_for_child(cid): return parent_id
    async def _fcm_for_parent(pid): return await identity.fcm_token_for_parent(pid)
    async def _active(since): return []

    runner = ManualDigestRunner(
        flagged=flagged, digest_store=digest_store, channel=channel,
        parent_for_child_fn=_parent_for_child,
        fcm_token_for_parent_fn=_fcm_for_parent,
        active_child_ids_fn=_active,
    )

    with TestClient(app, raise_server_exceptions=True) as client:
        _patch_state(client, identity, flagged, runner, digest_store, channel)

        resp = client.patch(
            "/v1/device/fcm-token",
            json={"fcm_token": "my-fcm-token-abc"},
            headers={"Authorization": f"Bearer {parent_token}"},
        )
        # The parent token is in parent_tokens, but authenticate_device looks at
        # device_tokens first then falls back to authenticate_parent via middleware.
        # InMemoryIdentityStore.authenticate_device won't find the parent token because
        # it's stored in _parent_tokens, not _device_tokens. We need to also check
        # authenticate_parent path — but the middleware calls authenticate_device first.
        # The parent token is a valid parent token, not a device token, so the middleware
        # calls authenticate_parent as a fallback. Let's check what the middleware does.
        # Actually looking at the middleware, it calls authenticate_device first, then
        # authenticate_parent. The parent token is in _parent_tokens.
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True

        # Verify the FCM token was stored.
        stored = await identity.fcm_token_for_parent(parent_id)
        assert stored == "my-fcm-token-abc"


@pytest.mark.asyncio
async def test_internal_digest_run_builds_digests():
    """POST /internal/digest/run triggers run_once and returns digest count."""
    from app.identity.in_memory_adapter import InMemoryIdentityStore
    from app.flagged.in_memory_adapter import InMemoryFlaggedEventStore
    from app.flagged.protocol import FlaggedEvent
    from app.digest.in_memory_store import InMemoryDigestStore
    from app.digest.manual_runner import ManualDigestRunner

    identity = InMemoryIdentityStore()
    flagged = InMemoryFlaggedEventStore()
    digest_store = InMemoryDigestStore()
    channel = _FakeChannel()

    parent_id, parent_token = await identity.register_parent("Test Parent")
    child_record = await identity.issue_child(parent_id, "Test Child")
    child_id = child_record.child_id

    now = time.time()
    # Seed a flagged event within the day.
    evt = FlaggedEvent(
        flag_id="f-test-run",
        child_id=child_id,
        created_at=now - 3600,
        app_package="com.whatsapp",
        direction="inbound",
        label="abusive",  # type: ignore[arg-type]
        severity="medium",  # type: ignore[arg-type]
        quote="שלום",
        explanation="הודעה פוגענית.",
        source="frontline_direct",
        trace_id="trace-test",
        status="alerted",  # type: ignore[arg-type]
    )
    await flagged.record(evt)

    async def _parent_for_child(cid): return await identity.parent_for_child(cid)
    async def _fcm_for_parent(pid): return "fake-fcm"
    async def _active(since): return await flagged.child_ids_with_events_since(since)

    runner = ManualDigestRunner(
        flagged=flagged, digest_store=digest_store, channel=channel,
        parent_for_child_fn=_parent_for_child,
        fcm_token_for_parent_fn=_fcm_for_parent,
        active_child_ids_fn=_active,
    )

    with TestClient(app, raise_server_exceptions=True) as client:
        _patch_state(client, identity, flagged, runner, digest_store, channel)
        # Also need DIGEST_ALLOW_MANUAL_TRIGGER=true (default) — rely on default.
        resp = client.post("/internal/digest/run")
        assert resp.status_code == 200
        data = resp.json()
        assert data["digests_built"] == 1
        assert child_id in data["child_ids"]


@pytest.mark.asyncio
async def test_get_digests_returns_parent_digest():
    """GET /v1/parent/digests/{date} returns the digest for the requesting parent."""
    from app.identity.in_memory_adapter import InMemoryIdentityStore
    from app.flagged.in_memory_adapter import InMemoryFlaggedEventStore
    from app.flagged.protocol import FlaggedEvent
    from app.digest.in_memory_store import InMemoryDigestStore
    from app.digest.manual_runner import ManualDigestRunner
    from app.digest.protocol import ChildDigest

    identity = InMemoryIdentityStore()
    flagged = InMemoryFlaggedEventStore()
    digest_store = InMemoryDigestStore()
    channel = _FakeChannel()

    parent_id, parent_token = await identity.register_parent("Test Parent")
    child_record = await identity.issue_child(parent_id, "Test Child")
    child_id = child_record.child_id

    # Pre-save a digest for today.
    today = time.strftime("%Y-%m-%d")
    digest = ChildDigest(
        child_id=child_id,
        parent_id=parent_id,
        date=today,
        generated_at=time.time(),
        total_flagged=3,
        review_needed=1,
        by_severity={"medium": 2, "high": 1},
        by_label={"abusive": 3},
        entries=[],
    )
    await digest_store.save(digest)

    async def _parent_for_child(cid): return parent_id
    async def _fcm_for_parent(pid): return None
    async def _active(since): return []

    runner = ManualDigestRunner(
        flagged=flagged, digest_store=digest_store, channel=channel,
        parent_for_child_fn=_parent_for_child,
        fcm_token_for_parent_fn=_fcm_for_parent,
        active_child_ids_fn=_active,
    )

    with TestClient(app, raise_server_exceptions=True) as client:
        _patch_state(client, identity, flagged, runner, digest_store, channel)

        resp = client.get(
            f"/v1/parent/digests/{today}",
            headers={"Authorization": f"Bearer {parent_token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["child_id"] == child_id
        assert data[0]["total_flagged"] == 3


@pytest.mark.asyncio
async def test_get_digests_different_parent_gets_404():
    """A different parent cannot see another parent's child digests."""
    from app.identity.in_memory_adapter import InMemoryIdentityStore
    from app.flagged.in_memory_adapter import InMemoryFlaggedEventStore
    from app.digest.in_memory_store import InMemoryDigestStore
    from app.digest.manual_runner import ManualDigestRunner
    from app.digest.protocol import ChildDigest

    identity = InMemoryIdentityStore()
    flagged = InMemoryFlaggedEventStore()
    digest_store = InMemoryDigestStore()
    channel = _FakeChannel()

    # Parent A has a child with a digest.
    parent_a_id, parent_a_token = await identity.register_parent("Parent A")
    child_a = await identity.issue_child(parent_a_id, "Child A")

    today = time.strftime("%Y-%m-%d")
    await digest_store.save(ChildDigest(
        child_id=child_a.child_id,
        parent_id=parent_a_id,
        date=today,
        generated_at=time.time(),
        total_flagged=1,
        review_needed=0,
        by_severity={},
        by_label={},
        entries=[],
    ))

    # Parent B registers.
    parent_b_id, parent_b_token = await identity.register_parent("Parent B")

    async def _parent_for_child(cid): return await identity.parent_for_child(cid)
    async def _fcm_for_parent(pid): return None
    async def _active(since): return []

    runner = ManualDigestRunner(
        flagged=flagged, digest_store=digest_store, channel=channel,
        parent_for_child_fn=_parent_for_child,
        fcm_token_for_parent_fn=_fcm_for_parent,
        active_child_ids_fn=_active,
    )

    with TestClient(app, raise_server_exceptions=True) as client:
        _patch_state(client, identity, flagged, runner, digest_store, channel)

        # Parent B tries to GET the digest — should get 404 (no children under B).
        resp = client.get(
            f"/v1/parent/digests/{today}",
            headers={"Authorization": f"Bearer {parent_b_token}"},
        )
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_digests_404_when_no_digest():
    """GET /v1/parent/digests/{date} returns 404 when no digest exists."""
    from app.identity.in_memory_adapter import InMemoryIdentityStore
    from app.flagged.in_memory_adapter import InMemoryFlaggedEventStore
    from app.digest.in_memory_store import InMemoryDigestStore
    from app.digest.manual_runner import ManualDigestRunner

    identity = InMemoryIdentityStore()
    flagged = InMemoryFlaggedEventStore()
    digest_store = InMemoryDigestStore()
    channel = _FakeChannel()

    parent_id, parent_token = await identity.register_parent("Test Parent")
    await identity.issue_child(parent_id, "Child")

    async def _parent_for_child(cid): return parent_id
    async def _fcm_for_parent(pid): return None
    async def _active(since): return []

    runner = ManualDigestRunner(
        flagged=flagged, digest_store=digest_store, channel=channel,
        parent_for_child_fn=_parent_for_child,
        fcm_token_for_parent_fn=_fcm_for_parent,
        active_child_ids_fn=_active,
    )

    with TestClient(app, raise_server_exceptions=True) as client:
        _patch_state(client, identity, flagged, runner, digest_store, channel)

        resp = client.get(
            "/v1/parent/digests/2023-01-01",
            headers={"Authorization": f"Bearer {parent_token}"},
        )
        assert resp.status_code == 404
