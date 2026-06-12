"""Throwaway smoke: dashboard URL + parent login flow (in-process TestClient)."""
import sys

sys.path.insert(0, "server")
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

ok = True


def check(name, cond, detail=""):
    global ok
    print(("PASS " if cond else "FAIL ") + name + (f"  {detail}" if detail else ""))
    if not cond:
        ok = False


with TestClient(app) as c:
    # 1. dashboard served, public
    r = c.get("/dashboard/")
    check("GET /dashboard/ -> 200 html", r.status_code == 200 and "text/html" in r.headers.get("content-type", ""))
    check("dashboard has English Shomer.AI logo", "Shomer.AI" in r.text)
    check("dashboard has login form", "password" in r.text.lower())

    r = c.get("/", follow_redirects=False)
    check("GET / redirects to /dashboard/", r.status_code in (302, 307) and "/dashboard" in r.headers.get("location", ""))

    # 2. register with username/password
    r = c.post("/v1/parent/register", json={"display_name": "Smoke Parent", "username": "smoke.parent", "password": "s3cretpass"})
    check("register w/ creds -> 2xx", r.status_code in (200, 201), str(r.status_code) + " " + r.text[:200])
    tok_reg = r.json().get("parent_token", "")

    # 3. duplicate username
    r = c.post("/v1/parent/register", json={"display_name": "X", "username": "smoke.parent", "password": "s3cretpass"})
    check("duplicate username -> 409", r.status_code == 409, str(r.status_code))

    # 4. login good / bad
    r = c.post("/v1/parent/login", json={"username": "smoke.parent", "password": "s3cretpass"})
    check("login -> 200 + token + display_name", r.status_code == 200 and r.json().get("parent_token") and r.json().get("display_name") == "Smoke Parent", r.text[:200])
    token = r.json().get("parent_token", tok_reg)
    r = c.post("/v1/parent/login", json={"username": "smoke.parent", "password": "wrongpass1"})
    check("login wrong pass -> 401", r.status_code == 401, str(r.status_code))
    r = c.post("/v1/parent/login", json={"username": "no.such.user", "password": "whatever12"})
    check("login unknown user -> 401 same body", r.status_code == 401 and r.json().get("detail") == "invalid username or password", r.text[:200])

    # 5. children list with the login token
    h = {"Authorization": f"Bearer {token}"}
    r = c.post("/v1/parent/children", json={"display_name": "דנה"}, headers=h)
    check("issue child -> 2xx", r.status_code in (200, 201), str(r.status_code) + " " + r.text[:200])
    child_id = r.json().get("child_id", "")
    r = c.get("/v1/parent/children", headers=h)
    names = [ch.get("display_name") for ch in (r.json() if isinstance(r.json(), list) else r.json().get("children", []))]
    check("list children shows name", r.status_code == 200 and "דנה" in names, r.text[:200])

    # 6. child-scoped alerts: own child ok, foreign child forbidden
    r = c.get(f"/v1/parent/alerts?child_id={child_id}", headers=h)
    check("alerts own child -> 200", r.status_code == 200, str(r.status_code))
    r2 = c.post("/v1/parent/register", json={"display_name": "Other"})
    other_tok = r2.json()["parent_token"]
    r = c.get(f"/v1/parent/alerts?child_id={child_id}", headers={"Authorization": f"Bearer {other_tok}"})
    check("alerts foreign child -> 403/404", r.status_code in (403, 404), str(r.status_code))

    # 7. display_name-only register back-compat
    check("display_name-only register still works", r2.status_code in (200, 201))

print("\nRESULT:", "ALL PASS" if ok else "FAILURES")
sys.exit(0 if ok else 1)
