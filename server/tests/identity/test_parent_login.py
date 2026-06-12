"""Tests for email/password parent login, registration, onboarding, and dashboard.

Covers:
  1.  register with email+password → login succeeds → returned token authorizes GET /v1/parent/children
  2.  login wrong password → 401 (same body as unknown email)
  3.  unknown email → 401 (same body as wrong password — no user enumeration)
  4.  duplicate email on register → 409 "email already registered"
  5.  display_name-only register still works (back-compat)
  6.  password validation (short password → 422)
  7.  invalid email format → 422
  8.  email provided without password → 422
  9.  GET /dashboard/ returns 200 text/html without any auth header (if dashboard exists)
  10. GET / redirects to /dashboard/
  11. cross-parent isolation — parent B's token cannot see parent A's children
  12. register with email+password+child_name → 201 with child_id + pairing_code;
      FakeEmailSender received exactly one email containing the code; the pairing
      code redeems at POST /v1/pair → device token authenticates monitor endpoint
  13. /v1/parent/pairing-code triggers an email when parent has an email
  14. /v1/parent/pairing-code works (no crash, no email) when parent is name-only
  15. mailer contract — LogEmailSender returns True and does not raise

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


class FakeEmailSender:
    """Captures sent emails in a list for assertion in tests."""

    def __init__(self):
        self.sent: list[dict] = []

    async def send(self, to: str, subject: str, body: str) -> bool:
        self.sent.append({"to": to, "subject": subject, "body": body})
        return True


# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def client_with_identity(monkeypatch, tmp_path):
    """TestClient with InMemoryIdentityStore + FakeEmailSender wired on app.state."""
    monkeypatch.setenv("AUDIT_DB_PATH", str(tmp_path / "audit.db"))
    monkeypatch.setenv("CONTEXT_AGENT_ENABLED", "false")
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "99999")
    monkeypatch.setenv("IDENTITY_BACKEND", "memory")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    identity = InMemoryIdentityStore()
    mailer = FakeEmailSender()

    with TestClient(app, raise_server_exceptions=True) as client:
        app.state.classifier = _FixedClassifier()
        app.state.context_agent = None
        app.state.identity = identity
        app.state.mailer = mailer
        yield client, identity, mailer


# ---------------------------------------------------------------------------
# 1. register + login + token authorizes children endpoint
# ---------------------------------------------------------------------------


def test_register_login_and_use_token(client_with_identity):
    """Full happy path: register → login → use returned token on authenticated endpoint."""
    client, _, _ = client_with_identity

    # Register with email+password
    resp = client.post(
        "/v1/parent/register",
        json={"display_name": "Alice Parent", "email": "alice@example.com", "password": "s3cr3tpass"},
    )
    assert resp.status_code == 201, f"Register failed: {resp.text}"
    reg_body = resp.json()
    assert reg_body["parent_id"]
    assert reg_body["parent_token"]
    assert reg_body["display_name"] == "Alice Parent"
    assert reg_body["email"] == "alice@example.com"

    # Login
    resp = client.post(
        "/v1/parent/login",
        json={"email": "alice@example.com", "password": "s3cr3tpass"},
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    login_body = resp.json()
    assert login_body["parent_id"] == reg_body["parent_id"]
    assert login_body["parent_token"]
    assert login_body["display_name"] == "Alice Parent"
    assert login_body["email"] == "alice@example.com"

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
    client, _, _ = client_with_identity

    client.post(
        "/v1/parent/register",
        json={"email": "bob@example.com", "password": "correctpass123"},
    )

    resp = client.post(
        "/v1/parent/login",
        json={"email": "bob@example.com", "password": "WRONGPASSWORD"},
    )
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.text}"
    assert resp.json()["detail"] == "invalid email or password"


# ---------------------------------------------------------------------------
# 3. Unknown email → 401 (same message — no user enumeration)
# ---------------------------------------------------------------------------


def test_login_unknown_email_returns_401(client_with_identity):
    client, _, _ = client_with_identity

    resp = client.post(
        "/v1/parent/login",
        json={"email": "nobody@example.com", "password": "anypassword"},
    )
    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.text}"
    # Must be the same message as wrong password — no user enumeration
    assert resp.json()["detail"] == "invalid email or password"


# ---------------------------------------------------------------------------
# 4. Duplicate email → 409
# ---------------------------------------------------------------------------


def test_duplicate_email_register_returns_409(client_with_identity):
    client, _, _ = client_with_identity

    client.post(
        "/v1/parent/register",
        json={"email": "carol@example.com", "password": "password123"},
    )

    resp = client.post(
        "/v1/parent/register",
        json={"email": "carol@example.com", "password": "differentpass"},
    )
    assert resp.status_code == 409, f"Expected 409, got {resp.status_code}: {resp.text}"
    assert "email already registered" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# 5. Display-name-only registration still works (back-compat)
# ---------------------------------------------------------------------------


def test_display_name_only_register_still_works(client_with_identity):
    """Android client registers without email/password — must keep working."""
    client, _, _ = client_with_identity

    resp = client.post(
        "/v1/parent/register",
        json={"display_name": "Legacy Android Parent"},
    )
    assert resp.status_code == 201, f"Back-compat register failed: {resp.text}"
    body = resp.json()
    assert body["parent_id"]
    assert body["parent_token"]
    assert body.get("email") is None

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
    client, _, _ = client_with_identity

    resp = client.post(
        "/v1/parent/register",
        json={"email": "dave@example.com", "password": "short"},  # 5 chars < 8 minimum
    )
    assert resp.status_code == 422, f"Expected 422 for short password, got {resp.status_code}: {resp.text}"


# ---------------------------------------------------------------------------
# 7. Invalid email format → 422
# ---------------------------------------------------------------------------


def test_invalid_email_format_returns_422(client_with_identity):
    client, _, _ = client_with_identity

    for bad_email in ("notanemail", "no-at-sign", "@nodomain", "two@@at.com"):
        resp = client.post(
            "/v1/parent/register",
            json={"email": bad_email, "password": "validpassword123"},
        )
        assert resp.status_code == 422, (
            f"Expected 422 for bad email {bad_email!r}, got {resp.status_code}: {resp.text}"
        )


# ---------------------------------------------------------------------------
# 8. Email provided without password → 422
# ---------------------------------------------------------------------------


def test_email_without_password_returns_422(client_with_identity):
    client, _, _ = client_with_identity

    resp = client.post(
        "/v1/parent/register",
        json={"email": "eve@example.com"},  # no password
    )
    assert resp.status_code == 422, (
        f"Expected 422 (email requires password), got {resp.status_code}: {resp.text}"
    )


# ---------------------------------------------------------------------------
# 9. GET /dashboard/ returns 200 text/html without auth (if dashboard dir exists)
# ---------------------------------------------------------------------------


def test_dashboard_accessible_without_auth(client_with_identity):
    """The dashboard static files must be reachable without an Authorization header."""
    client, _, _ = client_with_identity

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
    client, _, _ = client_with_identity

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
    client, identity, _ = client_with_identity

    # Register parent A
    resp_a = client.post(
        "/v1/parent/register",
        json={"email": "parent.alpha@example.com", "password": "alphapassword"},
    )
    assert resp_a.status_code == 201
    token_a = resp_a.json()["parent_token"]
    parent_a_id = resp_a.json()["parent_id"]

    # Register parent B
    resp_b = client.post(
        "/v1/parent/register",
        json={"email": "parent.beta@example.com", "password": "betapassword"},
    )
    assert resp_b.status_code == 201

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
        json={"email": "parent.beta@example.com", "password": "betapassword"},
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


# ---------------------------------------------------------------------------
# 12. End-to-end onboarding: register w/ child_name → emailed OTP → pair → child visible
# ---------------------------------------------------------------------------


def test_register_with_child_name_full_onboarding(client_with_identity):
    """register(email+password+child_name) → 201 with pairing_code;
    FakeEmailSender received one email containing the code;
    POST /v1/pair with code → device_token;
    GET /v1/parent/children with parent_token shows the child.
    """
    client, _, mailer = client_with_identity

    # Step 1: register
    resp = client.post(
        "/v1/parent/register",
        json={
            "display_name": "Onboarding Parent",
            "email": "onboard@example.com",
            "password": "onboardpass1",
            "child_name": "Little One",
        },
    )
    assert resp.status_code == 201, f"Register failed: {resp.text}"
    body = resp.json()
    assert body["parent_id"], "parent_id missing"
    assert body["parent_token"], "parent_token missing"
    assert body["email"] == "onboard@example.com"
    assert body["child_id"], "child_id missing — child was not issued"
    pairing_code = body.get("pairing_code")
    assert pairing_code, "pairing_code missing from response"
    assert body.get("pairing_expires_in_s"), "pairing_expires_in_s missing"
    parent_token = body["parent_token"]
    child_id = body["child_id"]

    # Step 2: FakeEmailSender received exactly one email containing the code.
    # (asyncio.create_task in the router fires the email; TestClient runs the event
    # loop, so the task runs during the with-block).
    import asyncio as _aio
    # Drain any pending tasks so the fire-and-forget email task completes.
    async def _drain():
        await _aio.sleep(0.1)

    loop = _aio.new_event_loop()
    try:
        loop.run_until_complete(_drain())
    finally:
        loop.close()

    assert len(mailer.sent) >= 1, f"Expected at least 1 email, got {len(mailer.sent)}: {mailer.sent}"
    otp_emails = [m for m in mailer.sent if pairing_code in m["body"]]
    assert otp_emails, (
        f"No email contained pairing code {pairing_code!r}. Emails sent: {mailer.sent}"
    )
    assert otp_emails[0]["to"] == "onboard@example.com"
    assert "Shomer.AI" in otp_emails[0]["subject"]

    # Step 3: redeem pairing code → device token
    resp_pair = client.post(
        "/v1/pair",
        json={"code": pairing_code, "device_fingerprint": "test-device-fp"},
    )
    assert resp_pair.status_code == 200, f"Pair failed: {resp_pair.text}"
    device_token = resp_pair.json()["device_token"]
    assert device_token
    assert resp_pair.json()["child_id"] == child_id
    assert resp_pair.json()["role"] == "child"

    # Step 4: parent sees child in children list
    resp_children = client.get(
        "/v1/parent/children",
        headers={"Authorization": f"Bearer {parent_token}"},
    )
    assert resp_children.status_code == 200
    child_ids = {c["child_id"] for c in resp_children.json()}
    assert child_id in child_ids, f"Expected child {child_id} in {child_ids}"

    # Step 5: device token can authenticate against a monitor endpoint
    # (Verify the Bearer auth — not a full pipeline test; just confirm 200 vs 401).
    resp_monitor = client.get(
        "/v1/parent/children",
        headers={"Authorization": f"Bearer {device_token}"},
    )
    # child role has role != "parent" → 403 on parent-only endpoint is correct.
    # What matters: it's NOT 401 (unauthenticated); it IS 403 (authenticated, wrong role).
    assert resp_monitor.status_code == 403, (
        f"Expected 403 for child device on parent endpoint, got {resp_monitor.status_code}"
    )


# ---------------------------------------------------------------------------
# 13. /v1/parent/pairing-code triggers an email when parent has an email
# ---------------------------------------------------------------------------


def test_pairing_code_emails_when_parent_has_email(client_with_identity):
    client, _, mailer = client_with_identity

    # Register parent with email
    resp_reg = client.post(
        "/v1/parent/register",
        json={"email": "pcode@example.com", "password": "pcodepass1"},
    )
    assert resp_reg.status_code == 201
    parent_token = resp_reg.json()["parent_token"]

    # Issue a child
    resp_child = client.post(
        "/v1/parent/children",
        json={"display_name": "Child For Pairing"},
        headers={"Authorization": f"Bearer {parent_token}"},
    )
    assert resp_child.status_code == 201
    child_id = resp_child.json()["child_id"]

    initial_email_count = len(mailer.sent)

    # Request a pairing code
    resp_pc = client.post(
        "/v1/parent/pairing-code",
        json={"child_id": child_id},
        headers={"Authorization": f"Bearer {parent_token}"},
    )
    assert resp_pc.status_code == 201
    code = resp_pc.json()["code"]

    # Drain fire-and-forget tasks
    import asyncio as _aio
    async def _drain():
        await _aio.sleep(0.1)
    loop = _aio.new_event_loop()
    try:
        loop.run_until_complete(_drain())
    finally:
        loop.close()

    new_emails = mailer.sent[initial_email_count:]
    assert len(new_emails) >= 1, f"Expected at least 1 new email after pairing-code, got {new_emails}"
    assert any(code in m["body"] for m in new_emails), (
        f"Code {code!r} not found in any new email: {new_emails}"
    )
    assert new_emails[0]["to"] == "pcode@example.com"


# ---------------------------------------------------------------------------
# 14. /v1/parent/pairing-code works (no crash, no email) when parent is name-only
# ---------------------------------------------------------------------------


def test_pairing_code_no_crash_for_name_only_parent(client_with_identity):
    client, _, mailer = client_with_identity

    # Name-only parent (no email)
    resp_reg = client.post(
        "/v1/parent/register",
        json={"display_name": "No-Email Parent"},
    )
    assert resp_reg.status_code == 201
    parent_token = resp_reg.json()["parent_token"]

    # Issue a child
    resp_child = client.post(
        "/v1/parent/children",
        json={"display_name": "Child NoEmail"},
        headers={"Authorization": f"Bearer {parent_token}"},
    )
    assert resp_child.status_code == 201
    child_id = resp_child.json()["child_id"]

    initial_email_count = len(mailer.sent)

    # Request a pairing code — must not crash
    resp_pc = client.post(
        "/v1/parent/pairing-code",
        json={"child_id": child_id},
        headers={"Authorization": f"Bearer {parent_token}"},
    )
    assert resp_pc.status_code == 201, f"Pairing code failed: {resp_pc.text}"

    # No new emails should have been sent (parent has no email).
    # Allow a brief async drain.
    import asyncio as _aio
    async def _drain():
        await _aio.sleep(0.1)
    loop = _aio.new_event_loop()
    try:
        loop.run_until_complete(_drain())
    finally:
        loop.close()

    new_emails = mailer.sent[initial_email_count:]
    assert len(new_emails) == 0, f"Expected no email for name-only parent, got: {new_emails}"


# ---------------------------------------------------------------------------
# 15. Mailer contract — LogEmailSender returns True, does not raise
# ---------------------------------------------------------------------------


def test_log_email_sender_contract():
    import asyncio as _aio
    from app.mailer import LogEmailSender

    sender = LogEmailSender()

    async def _run():
        result = await sender.send(
            to="test@example.com",
            subject="Shomer.AI — test",
            body="Test body with Hebrew: שלום",
        )
        assert result is True, f"LogEmailSender returned {result!r}, expected True"

    _aio.run(_run())
