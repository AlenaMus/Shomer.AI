"""Helper for MANUAL testing: mint a parent + child + pairing OTP in one shot.

Talks to a RUNNING server over HTTP (start it first — see android_client/MANUAL_TESTING.md).
Prints the parent token (for the dashboard / parent-mode app) and a 6-digit pairing
code (to type into the child device's Pairing screen).

Usage (from repo root, server already running):
    server/.venv/Scripts/python.exe scripts/make_pairing_code.py
    server/.venv/Scripts/python.exe scripts/make_pairing_code.py --base http://localhost:8000

The pairing code expires in ~10 minutes and is single-use — re-run to get a fresh one.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request


def _post(base: str, path: str, body: dict, token: str | None = None) -> dict:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(base + path, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000", help="server base URL")
    ap.add_argument("--parent-name", default="Manual Test Parent")
    ap.add_argument("--child-name", default="Manual Test Child")
    args = ap.parse_args()
    base = args.base.rstrip("/")

    try:
        parent = _post(base, "/v1/parent/register", {"display_name": args.parent_name})
        ptoken = parent["parent_token"]
        child = _post(base, "/v1/parent/children", {"display_name": args.child_name}, token=ptoken)
        cid = child["child_id"]
        pc = _post(base, "/v1/parent/pairing-code", {"child_id": cid}, token=ptoken)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR talking to {base}: {exc}", file=sys.stderr)
        print("Is the server running?  python -m uvicorn server.app.main:app --host 0.0.0.0 --port 8000",
              file=sys.stderr)
        sys.exit(1)

    print("=" * 56)
    print("  PAIRING CODE (type this into the child device):")
    print(f"      >>>  {pc['code']}  <<<")
    print("=" * 56)
    print(f"  parent_token (dashboard / parent-mode app): {ptoken}")
    print(f"  parent_id : {parent['parent_id']}")
    print(f"  child_id  : {cid}")
    print(f"  server    : {base}")
    print("  Code expires in ~10 min, single-use. Re-run for a fresh one.")


if __name__ == "__main__":
    main()
