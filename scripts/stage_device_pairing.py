"""Stage an on-device pairing: ensure a parent + child exist, print a fresh OTP.

Re-run any time to mint a new 10-minute pairing OTP for the same parent/child
(so the dashboard parent token stays stable across re-runs).  State is cached in
scripts/_device_pairing.json so the parent/child are reused.

Usage:
    python scripts/stage_device_pairing.py [base_url]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8011"
STATE = Path("scripts/_device_pairing.json")


def main() -> int:
    s = httpx.Client(timeout=30.0)

    state = json.loads(STATE.read_text()) if STATE.exists() else {}

    # Reuse parent if we have a still-valid token; else register a new one.
    parent_token = state.get("parent_token")
    parent_id = state.get("parent_id")
    if parent_token:
        chk = s.get(f"{BASE}/v1/parent/alerts", headers={"Authorization": f"Bearer {parent_token}"})
        if chk.status_code != 200:
            parent_token = None

    if not parent_token:
        p = s.post(f"{BASE}/v1/parent/register", json={"display_name": "Device Test Parent"}).json()
        parent_token = p["parent_token"]
        parent_id = p.get("parent_id")
        state = {"parent_token": parent_token, "parent_id": parent_id}

    ph = {"Authorization": f"Bearer {parent_token}"}

    # Reuse child if present; else create one.
    child_id = state.get("child_id")
    if not child_id:
        c = s.post(f"{BASE}/v1/parent/children", headers=ph, json={"display_name": "Device Test Child"}).json()
        child_id = c["child_id"]
        state["child_id"] = child_id

    # Always mint a fresh OTP (10-min TTL).
    code = s.post(f"{BASE}/v1/parent/pairing-code", headers=ph, json={"child_id": child_id}).json()["code"]

    STATE.write_text(json.dumps(state, indent=2))

    print("=" * 56)
    print("  ON-DEVICE PAIRING — enter the OTP in the app")
    print("=" * 56)
    print(f"  Pairing OTP   : {code}      (valid 10 minutes)")
    print(f"  child_id      : {child_id}")
    print(f"  parent_token  : {parent_token}")
    print(f"  Base URL (app): http://127.0.0.1:8011/   (adb reverse)")
    print("=" * 56)
    print("  Dashboard: open dashboard/index.html -> Settings ->")
    print(f"  Base URL http://localhost:8011  +  paste the parent_token above")
    print("=" * 56)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
