"""In-process smoke: dashboard + email/password parent login + onboarding flow.

Flow verified:
  1. GET /dashboard/ → 200 text/html (public)
  2. GET / → redirect to /dashboard/
  3. register with email+password → 201 + parent_token + email echoed
  4. duplicate email → 409 "email already registered"
  5. login good → 200 + token + display_name
  6. login wrong password → 401 "invalid email or password"
  7. login unknown email → 401 same body (no user enumeration)
  8. children list with the login token → 200
  9. child-scoped alerts: own child ok, foreign child → 403/404
  10. display_name-only register back-compat
  11. register with email+password+child_name → 201 + pairing_code + child_id
  12. POST /v1/pair with pairing_code → 200 device_token (end-to-end onboarding)
  13. child listed under parent after onboarding
"""
from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, "server")
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.identity import InMemoryIdentityStore  # noqa: E402

ok = True


def check(name: str, cond: bool, detail: str = "") -> None:
    global ok
    print(("PASS " if cond else "FAIL ") + name + (f"  {detail}" if detail else ""))
    if not cond:
        ok = False


# ---------------------------------------------------------------------------
# Fake mailer to capture OTP emails
# ---------------------------------------------------------------------------


class FakeEmailSender:
    def __init__(self):
        self.sent: list[dict] = []

    async def send(self, to: str, subject: str, body: str) -> bool:
        self.sent.append({"to": to, "subject": subject, "body": body})
        return True


# ---------------------------------------------------------------------------
# Run smoke
# ---------------------------------------------------------------------------

identity = InMemoryIdentityStore()
mailer = FakeEmailSender()

with TestClient(app, raise_server_exceptions=True) as c:
    # Wire in-memory adapters so the smoke is self-contained.
    app.state.identity = identity
    app.state.mailer = mailer

    # 1. dashboard served, public
    r = c.get("/dashboard/")
    check(
        "GET /dashboard/ -> 200 html",
        r.status_code == 200 and "text/html" in r.headers.get("content-type", ""),
    )
    check("dashboard has Shomer.AI", "Shomer.AI" in r.text)

    # 2. root redirect
    r = c.get("/", follow_redirects=False)
    check(
        "GET / redirects to /dashboard/",
        r.status_code in (302, 307) and "/dashboard" in r.headers.get("location", ""),
    )

    # 3. register with email+password
    r = c.post(
        "/v1/parent/register",
        json={"display_name": "Smoke Parent", "email": "smoke@example.com", "password": "s3cretpass"},
    )
    check("register w/ email+pass -> 201", r.status_code == 201, f"{r.status_code} {r.text[:200]}")
    reg_body = r.json()
    tok_reg = reg_body.get("parent_token", "")
    check("register returns email", reg_body.get("email") == "smoke@example.com")

    # 4. duplicate email
    r = c.post(
        "/v1/parent/register",
        json={"email": "smoke@example.com", "password": "s3cretpass"},
    )
    check("duplicate email -> 409", r.status_code == 409, str(r.status_code))

    # 5. login good
    r = c.post("/v1/parent/login", json={"email": "smoke@example.com", "password": "s3cretpass"})
    check(
        "login -> 200 + token + display_name",
        r.status_code == 200 and r.json().get("parent_token") and r.json().get("display_name") == "Smoke Parent",
        r.text[:200],
    )
    token = r.json().get("parent_token", tok_reg)

    # 6. login wrong pass
    r = c.post("/v1/parent/login", json={"email": "smoke@example.com", "password": "wrongpass1"})
    check("login wrong pass -> 401", r.status_code == 401, str(r.status_code))

    # 7. login unknown email → same body (no user enumeration)
    r = c.post("/v1/parent/login", json={"email": "nobody@example.com", "password": "whatever12"})
    check(
        "login unknown email -> 401 same body",
        r.status_code == 401 and r.json().get("detail") == "invalid email or password",
        r.text[:200],
    )

    # 8. children list with the login token
    h = {"Authorization": f"Bearer {token}"}
    r = c.post("/v1/parent/children", json={"display_name": "דנה"}, headers=h)
    check("issue child -> 2xx", r.status_code in (200, 201), f"{r.status_code} {r.text[:200]}")
    child_id = r.json().get("child_id", "")
    r = c.get("/v1/parent/children", headers=h)
    names = [ch.get("display_name") for ch in (r.json() if isinstance(r.json(), list) else [])]
    check("list children shows name", r.status_code == 200 and "דנה" in names, r.text[:200])

    # 9. child-scoped alerts: own child ok, foreign child forbidden
    r = c.get(f"/v1/parent/alerts?child_id={child_id}", headers=h)
    check("alerts own child -> 200", r.status_code == 200, str(r.status_code))
    r2 = c.post("/v1/parent/register", json={"display_name": "Other"})
    other_tok = r2.json()["parent_token"]
    r = c.get(f"/v1/parent/alerts?child_id={child_id}", headers={"Authorization": f"Bearer {other_tok}"})
    check("alerts foreign child -> 403/404", r.status_code in (403, 404), str(r.status_code))

    # 10. display_name-only register back-compat
    check("display_name-only register still works", r2.status_code in (200, 201))

    # 11. register with email+password+child_name → 201 + pairing_code + child_id
    mailer.sent.clear()  # clear prior sends
    r = c.post(
        "/v1/parent/register",
        json={
            "display_name": "Onboard Parent",
            "email": "onboard@example.com",
            "password": "onboardpass1",
            "child_name": "Little One",
        },
    )
    check(
        "register w/ child_name -> 201 + child_id + pairing_code",
        r.status_code == 201
        and r.json().get("child_id")
        and r.json().get("pairing_code"),
        r.text[:300],
    )
    onboard_body = r.json()
    pairing_code = onboard_body.get("pairing_code", "")
    onboard_token = onboard_body.get("parent_token", "")
    onboard_child_id = onboard_body.get("child_id", "")

    # Drain fire-and-forget email task
    async def _drain():
        await asyncio.sleep(0.15)

    asyncio.run(_drain())

    otp_emails = [m for m in mailer.sent if pairing_code in m.get("body", "")]
    check(
        "OTP email sent with pairing code",
        bool(otp_emails) and otp_emails[0]["to"] == "onboard@example.com",
        f"emails: {mailer.sent}",
    )

    # 12. POST /v1/pair → device token
    r = c.post("/v1/pair", json={"code": pairing_code, "device_fingerprint": "smoke-fp"})
    check(
        "POST /v1/pair with code -> 200 + device_token",
        r.status_code == 200 and r.json().get("device_token"),
        r.text[:200],
    )
    device_token = r.json().get("device_token", "")
    check("pair returns correct child_id", r.json().get("child_id") == onboard_child_id)
    check("pair returns role=child", r.json().get("role") == "child")

    # 13. child listed under parent after onboarding
    r = c.get(
        "/v1/parent/children",
        headers={"Authorization": f"Bearer {onboard_token}"},
    )
    check(
        "onboard parent sees child after pairing",
        r.status_code == 200 and any(ch.get("child_id") == onboard_child_id for ch in r.json()),
        r.text[:200],
    )

print("\nRESULT:", "ALL PASS" if ok else "FAILURES")
sys.exit(0 if ok else 1)
