"""ntfy.sh push smoke test — verify the parent's phone receives pushes.

Classifier-independent: posts ONE sample Hebrew alert straight to the configured
ntfy topic, exactly the way ``NtfyNotifier`` does (JSON publish → UTF-8 safe).
Run this BEFORE the full pipeline so you know the phone is subscribed correctly.

Setup (one-time):
  1. Install the free **ntfy** app on the parent's phone (Android/iOS) or open
     https://ntfy.sh in a browser.
  2. Pick a long, unguessable topic and put it in ``server/.env``:
         ALERTS_NTFY_TOPIC=shomer-<something-random>
  3. In the ntfy app, Subscribe to that exact topic.

Run (from repo root):
  server/.venv/Scripts/python.exe scripts/test_ntfy.py
  server/.venv/Scripts/python.exe scripts/test_ntfy.py --topic shomer-test-123

Expected: the script prints HTTP 200 + a message id, and within a second the
push appears on every device subscribed to the topic.
"""

from __future__ import annotations

import argparse
import os
import sys

# Force UTF-8 stdio so the Windows cp1252 console can print Hebrew + icons
# (same belt-and-suspenders fix as server/app/main.py).
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass

import httpx
from dotenv import load_dotenv

# Load server/.env so ALERTS_NTFY_* are available exactly as the server reads them.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(_REPO_ROOT, "server", ".env"))

_SEVERITY_ICON = {"low": "🟡", "medium": "🟠", "high": "🔴", "critical": "🚨"}
_NTFY_PRIORITY = {"low": 2, "medium": 3, "high": 4, "critical": 5}


def main() -> int:
    ap = argparse.ArgumentParser(description="Send a test push to an ntfy topic.")
    ap.add_argument("--topic", default=os.environ.get("ALERTS_NTFY_TOPIC", "").strip(),
                    help="ntfy topic (default: ALERTS_NTFY_TOPIC from server/.env)")
    ap.add_argument("--server", default=os.environ.get("ALERTS_NTFY_SERVER", "https://ntfy.sh").strip(),
                    help="ntfy server base URL (default: ALERTS_NTFY_SERVER or https://ntfy.sh)")
    ap.add_argument("--severity", default="high", choices=list(_NTFY_PRIORITY),
                    help="severity → ntfy priority (default: high)")
    args = ap.parse_args()

    server = args.server.rstrip("/")
    topic = args.topic.strip()
    token = os.environ.get("ALERTS_NTFY_TOKEN", "").strip()
    click = os.environ.get("ALERTS_NTFY_CLICK_URL", "").strip()

    if not topic:
        print("✗ No ntfy topic. Set ALERTS_NTFY_TOPIC in server/.env or pass --topic.")
        print("  Then Subscribe to that same topic in the ntfy app on the phone.")
        return 2

    icon = _SEVERITY_ICON.get(args.severity, "🔔")
    payload = {
        "topic": topic,
        "title": f"{icon} Shomer.AI — בדיקה",
        "message": "זוהי הודעת בדיקה ממערכת ההתראות של Shomer.AI. אם הגיעה — ההתראות עובדות.",
        "priority": _NTFY_PRIORITY[args.severity],
        "tags": ["test", args.severity],
    }
    if click:
        payload["click"] = click
    headers = {"Authorization": f"Bearer {token}"} if token else {}

    print(f"→ Publishing test push to {server} (topic «{topic}», priority {payload['priority']})…")
    try:
        resp = httpx.post(server, json=payload, headers=headers, timeout=10.0)
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        print(f"✗ Publish failed: {exc}")
        print("  Check the topic/server, your network, and (for private topics) ALERTS_NTFY_TOKEN.")
        return 1

    try:
        msg_id = resp.json().get("id")
    except Exception:  # noqa: BLE001
        msg_id = None
    print(f"✓ Sent (HTTP {resp.status_code}, id={msg_id}).")
    print(f"  Check the phone subscribed to «{topic}» — the push should appear within a second.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
