"""End-to-end live check of POST /v1/monitor/image with REAL Tesseract OCR.

Unlike server/tests/monitor/test_monitor_image.py (which stubs OCR), this drives
the running server: register parent -> child -> pairing code -> device token ->
POST a real Hebrew chat screenshot -> print OCR text length + flag result.

Usage:
    python scripts/test_image_endpoint.py [base_url] [image_path]
"""
from __future__ import annotations

import sys
import time
import uuid

import httpx as requests

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8011"
IMG = sys.argv[2] if len(sys.argv) > 2 else "scripts/_chat_screenshot.png"


def main() -> int:
    s = requests.Client(timeout=60.0)

    # 1. Register parent.
    p = s.post(f"{BASE}/v1/parent/register", json={"display_name": "Image Test Parent"}).json()
    ph = {"Authorization": f"Bearer {p['parent_token']}"}

    # 2. Create child + pairing code.
    c = s.post(f"{BASE}/v1/parent/children", headers=ph, json={"display_name": "Image Test Child"}).json()
    child_id = c["child_id"]
    code = s.post(f"{BASE}/v1/parent/pairing-code", headers=ph, json={"child_id": child_id}).json()["code"]

    # 3. Pair device.
    dev = s.post(f"{BASE}/v1/pair", json={"code": code, "device_fingerprint": "image-test-pc"}).json()
    dh = {"Authorization": f"Bearer {dev['device_token']}"}
    assert dev["role"] == "child" and dev["child_id"] == child_id
    print(f"paired: child_id={child_id} role={dev['role']}")

    # 4. POST the screenshot.
    with open(IMG, "rb") as f:
        files = {"image": ("capture.jpg", f, "image/jpeg")}
        data = {
            "child_id": child_id,
            "session_id": "img-sess-1",
            "client_msg_id": str(uuid.uuid4()),
            "captured_at": str(time.time()),
            "direction": "screen",
        }
        t0 = time.time()
        r = s.post(f"{BASE}/v1/monitor/image", headers=dh, files=files, data=data)
        dt = (time.time() - t0) * 1000

    print(f"POST /v1/monitor/image -> {r.status_code} in {dt:.0f}ms")
    body = r.json()
    print(f"  accepted   = {body['accepted']}")
    print(f"  deduped    = {body['deduped']}")
    print(f"  flagged    = {body['flagged']}")
    print(f"  ocr_text_len = {body['ocr_text_len']}")
    for ack in body.get("acks", []):
        print(f"  ack: flagged={ack['flagged']} status={ack['status']} flag_id={ack.get('flag_id')}")

    # 5. Show the flag the parent would see (proves OCR text -> classify -> flag).
    alerts = s.get(f"{BASE}/v1/parent/alerts", headers=ph).json()
    print(f"\nparent /v1/parent/alerts -> {len(alerts)} flag(s)")
    for a in alerts:
        print(f"  [{a.get('severity')}] label={a.get('label')} quote={a.get('quote')!r}")

    ok = body["ocr_text_len"] > 0
    print("\n" + ("PASS: real Tesseract OCR extracted text + pipeline ran" if ok
                  else "FAIL: OCR returned no text"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
