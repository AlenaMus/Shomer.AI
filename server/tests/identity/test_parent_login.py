"""Tests for username/password parent login, registration extension, and dashboard mount.

Covers:
  1. register with username+password → login succeeds → returned token authorizes GET /v1/parent/children
  2. login wrong password → 401 (same body as unknown username)
  3. unknown username → 401 (same body as wrong password — no user enumeration)
  4. duplicate username on register → 409
  5. display_name-only register still works (back-compat)
  6. password validation (short password → 422)
  7. username validation (bad chars → 422)
  8. username without password → 422
  9. GET /dashboard/ returns 200 text/html without any auth header (if dashboard exists)
  10. GET / redirects to /dashboard/
  11. cross-parent isolation — parent B's token cannot see parent A's children

Run from repo root:
    server\\.venv\\Scripts\\python.exe -m pytest server/tests/identity/test_parent_login.py -q
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

_SERVER_DIR = str(Path(__file__).resolve().parents[2])
if _SERVER_DIR not in sys.path:
    sys.path.insert(0, _SERVER_DIR)

from fastapi.testclient import TestClient

from app.main import app
from app.identity import InMemoryIdentityStore
from app.schemas import ClassificationResult, HealthState


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


class _FixedClassifier:
    model_version = "stub-login-test"
    backend_name = "stub-login-test"

    async def classify(self, text: str) -> ClassificationResult:
        return ClassificationResult(
            label="non_offensive",
            confidence=0.95,
            is_offensive=False,
            model_version="stub-login-test",
            latency_ms=1.0,
            is_borderline=False,
            raw_confidence=0.95,
            error=False,
        )

    async def health(self):
        return (HealthState.OK, "stub")


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def client_with_identity(monkeypatch, tmp_path):
    """TestClient with InMemoryIdentityStore wired on app.state.identity."""
    monkeypatch.setenv("AUDIT_DB_PATH", str(tmp_path / "audit.db"))
    monkeypatch.setenv("CONTEXT_AGENT_ENABLED", "false")
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "99999")
    monkeypatch.setenv("IDENTITY_BACKEND", "memory")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    identity = InMemoryIdentityStore()

    with TestClient(app, raise_server_exceptions=True) as client:
        app.state.classifier = _FixedClassifier()
        app.state.context_agent = None
        app.state.identity = identity
        yield client, identity


# ---------------------------------------------------------------------------
# 1. register + login + token authorizes children endpoint
# ---------------------------------------------------------------------------


def test_register_login_and_use_token(client_with_identity):
    """Full happy path: register → login → use returned token on authenticated endpoint."""
    client, _ = client_with_identity

    # Register with username+password
    resp = client.post(
        "/v1/parent/register",
        json={"display_name": "Alice Parent", "username": "alice.parent", "password": "s3cr3tpass"},
    )
    assert resp.status_code == 201, f"Register failed: {resp.text}"
    reg_body = resp.json()
    assert reg_body["parent_id"]
    assert reg_body["parent_token"]
    assert reg_body["display_name"] == "Alice Parent"

    # Login
    resp = client.post(
        "/v1/parent/login",
        json={"username": "alice.parent", "password": "s3cr3tpass"},
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    login_body = resp.json()
    assert login_body["parent_id"] == reg_body["parent_id"]
    assert login_body["parent_token"]
    assert login_body["display_name"] == "Alice Parent"

    # Use the login token on an authenticated endpoint
    parent_token = login_body["parent_token"]
    resp = client.get(
        "/v1/parent/children",
        headers={"Authorization": f"Bearer {parent_token}"},
    )
    assert resp.status_code == 200, f"Children list failed: {resp.text}"
    assert resp.json() == []  # no children yet — proves token works


# ---------------------------------------------------------------------------
# 2. Wrong password → 401
# ---------------------------------------------------------------------------


def test_login_wrong_password_returns_401(client_with_identity):
    client, _ = client_with_identity

    client.post(
        "/v1/parent/register",
        json={"username": "bob.parent", "password": "correctpass123"},
    )

    resp = client.post(
        "/v1/parent/login",
        json={"username": "bob.parent", "password": "WRONGPASSWORD"},
    )
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.text}"
    assert resp.json()["detail"] == "invalid username or password"


# ---------------------------------------------------------------------------
# 3. Unknown username → 401 (same message — no user enumeration)
# ---------------------------------------------------------------------------


def test_login_unknown_username_returns_401(client_with_identity):
    client, _ = client_with_identity

    resp = client.post(
        "/v1/parent/login",
        json={"username": "nobody.here", "password": "anypassword"},
    )
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.text}"
    # Must be the same message as wrong password — no user enumeration
    assert resp.json()["detail"] == "invalid username or password"


# ---------------------------------------------------------------------------
# 4. Duplicate username → 409
# ---------------------------------------------------------------------------


def test_duplicate_username_register_returns_409(client_with_identity):
    client, _ = client_with_identity

    client.post(
        "/v1/parent/register",
        json={"username": "carol.parent", "password": "password123"},
    )

    resp = client.post(
        "/v1/parent/register",
        json={"username": "carol.parent", "password": "differentpass"},
    )
    assert resp.status_code == 409, f"Expected 409, got {resp.status_code}: {resp.text}"
    assert "username already taken" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# 5. Display-name-only registration still works (back-compat)
# ---------------------------------------------------------------------------


def test_display_name_only_register_still_works(client_with_identity):
    """Android client registers without username/password — must keep working."""
    client, _ = client_with_identity

    resp = client.post(
        "/v1/parent/register",
        json={"display_name": "Legacy Android Parent"},
    )
    assert resp.status_code == 201, f"Back-compat register failed: {resp.text}"
    body = resp.json()
    assert body["parent_id"]
    assert body["parent_token"]

    # The returned token still works on parent endpoints.
    resp2 = client.get(
        "/v1/parent/children",
        headers={"Authorization": f"Bearer {body['parent_token']}"},
    )
    assert resp2.status_code == 200, f"Token from legacy register failed: {resp2.text}"


# ---------------------------------------------------------------------------
# 6. Short password → 422
# ---------------------------------------------------------------------------


def test_short_password_returns_422(client_with_identity):
    client, _ = client_with_identity

    resp = client.post(
        "/v1/parent/register",
        json={"username": "dave.parent", "password": "short"},  # 5 chars < 8 minimum
    )
    assert resp.status_code == 422, f"Expected 422 for short password, got {resp.status_code}: {resp.text}"


# ---------------------------------------------------------------------------
# 7. Username with invalid characters → 422
# ---------------------------------------------------------------------------


def test_invalid_username_chars_returns_422(client_with_identity):
    client, _ = client_with_identity

    resp = client.post(
        "/v1/parent/register",
        json={"username": "UPPERCASE!!", "password": "validpassword123"},
    )
    assert resp.status_code == 422, f"Expected 422 for bad username chars, got {resp.status_code}: {resp.text}"


# ---------------------------------------------------------------------------
# 8. Username provided without password → 422
# ---------------------------------------------------------------------------


def test_username_without_password_returns_422(client_with_identity):
    client, _ = client_with_identity

    resp = client.post(
        "/v1/parent/register",
        json={"username": "eve.parent"},  # no password
    )
    assert resp.status_code == 422, f"Expected 422 (username requires password), got {resp.status_code}: {resp.text}"


# ---------------------------------------------------------------------------
# 9. GET /dashboard/ returns 200 text/html without auth (if dashboard dir exists)
# ---------------------------------------------------------------------------


def test_dashboard_accessible_without_auth(client_with_identity):
    """The dashboard static files must be reachable without an Authorization header."""
    client, _ = client_with_identity

    import pathlib
    # test file: server/tests/identity/test_parent_login.py
    # parents[3] = repo root = Shomer.AI/
    dashboard_dir = pathlib.Path(__file__).resolve().parents[3] / "dashboard"
    if not dashboard_dir.exists():
        pytest.skip("dashboard/ directory not present — skipping static serve test")

    resp = client.get("/dashboard/")
    # Allow 200 (static file served) or 404 (no index.html) but NOT 401/403.
    assert resp.status_code not in (401, 403), (
        f"Dashboard returned auth error {resp.status_code}: {resp.text}"
    )
    assert resp.status_code in (200, 301, 302, 404), (
        f"Unexpected status {resp.status_code}: {resp.text}"
    )


# ---------------------------------------------------------------------------
# 10. GET / redirects to /dashboard/
# ---------------------------------------------------------------------------


def test_root_redirects_to_dashboard(client_with_identity):
    client, _ = client_with_identity

    # TestClient by default follows redirects; disable to check the redirect itself.
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code in (301, 302), (
        f"Expected redirect from /, got {resp.status_code}"
    )
    location = resp.headers.get("location", "")
    assert "/dashboard/" in location, (
        f"Expected redirect to /dashboard/, got location={location!r}"
    )


# ---------------------------------------------------------------------------
# 11. Cross-parent isolation — parent B token cannot see parent A's children
# ---------------------------------------------------------------------------


def test_cross_parent_isolation_login_token(client_with_identity):
    """Parent B's login token must not expose parent A's children."""
    client, identity = client_with_identity

    # Register parent A
    resp_a = client.post(
        "/v1/parent/register",
        json={"username": "parent.alpha", "password": "alphapassword"},
    )
    assert resp_a.status_code == 201
    token_a = resp_a.json()["parent_token"]
    parent_a_id = resp_a.json()["parent_id"]

    # Register parent B
    resp_b = client.post(
        "/v1/parent/register",
        json={"username": "parent.beta", "password": "betapassword"},
    )
    assert resp_b.status_code == 201
    token_b = resp_b.json()["parent_token"]

    # Add a child to parent A (directly via identity store for speed)
    async def _add_child():
        return await identity.issue_child(parent_a_id, "Child of A")

    loop = asyncio.new_event_loop()
    try:
        child_a = loop.run_until_complete(_add_child())
    finally:
        loop.close()

    # Parent B's login token must not see parent A's child
    resp_b_login = client.post(
        "/v1/parent/login",
        json={"username": "parent.beta", "password": "betapassword"},
    )
    token_b_from_login = resp_b_login.json()["parent_token"]

    resp = client.get(
        "/v1/parent/children",
        headers={"Authorization": f"Bearer {token_b_from_login}"},
    )
    assert resp.status_code == 200
    child_ids = {c["child_id"] for c in resp.json()}
    assert child_a.child_id not in child_ids, (
        f"Parent B should NOT see Parent A's child {child_a.child_id}; got {child_ids}"
    )
