"""End-to-end demo of the Shomer.AI monitoring flow (S1-S4).

Exercises the REAL server composition root in-process via FastAPI's TestClient
(no uvicorn -> no orphaned :8000). The only stubbed component is the ML classifier
(swapped for a deterministic keyword stub so the walkthrough is readable and does
not depend on Ollama being up or returning a particular label). Everything else --
auth/pairing, dedup, triage, the flagged store, the daily digest, and the parent
review/react loop -- runs for real.

Run from the repo root:

    server/.venv/Scripts/python.exe scripts/monitor_demo.py

Flow demonstrated:
    parent register → issue child → pairing code → device pairs (token)
    → child posts a batch of captured messages (offensive / borderline / benign / duplicate)
    → server dedups + classifies + flags
    → parent lists alerts → reacts (labels the borderline case)
    → daily digest is built → parent reads the digest
    → labeled example is exported for future DictaBERT training
"""

from __future__ import annotations

import hashlib
import os
import sys
import time

# Ensure the repo root is importable when run as a standalone script.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Use in-memory backends so the demo is self-contained and leaves no db files.
os.environ.setdefault("DEDUP_BACKEND", "memory")
os.environ.setdefault("FLAGGED_BACKEND", "memory")
os.environ.setdefault("IDENTITY_BACKEND", "memory")
os.environ.setdefault("DIGEST_BACKEND", "manual")
os.environ.setdefault("DIGEST_ALLOW_MANUAL_TRIGGER", "true")
os.environ.setdefault("CONTEXT_AGENT_ENABLED", "false")
os.environ.setdefault("ALERTS_CHANNEL", "log")

from fastapi.testclient import TestClient  # noqa: E402

from server.app.main import app  # noqa: E402
from server.app.schemas import ClassificationResult  # noqa: E402
from server.app.schemas import HealthState  # noqa: E402


# ---------------------------------------------------------------------------
# Deterministic classifier stub (the ONLY faked component).
# ---------------------------------------------------------------------------


class DemoClassifier:
    """Keyword-driven stand-in so demo messages map to predictable outcomes.

    Real pipeline (triage → flag → digest → parent loop) runs unchanged; only
    the ML verdict is made deterministic here.
    """

    model_version = "demo-stub"

    async def classify(self, text: str) -> ClassificationResult:
        t = text.strip()
        # Borderline / "unknown but may be offensive" → classifier error → REVIEW_NEEDED.
        if "גבולי" in t or t.startswith("?"):
            return ClassificationResult(
                label="non_offensive", confidence=0.5, is_offensive=False,
                model_version=self.model_version, latency_ms=1.0,
                is_borderline=True, raw_confidence=0.5, error=True,
            )
        # Clearly offensive (abusive) → high-confidence → ALERT_DIRECT.
        if "מטומטם" in t or "טיפש" in t or "שונא" in t:
            return ClassificationResult(
                label="abusive", confidence=0.96, is_offensive=True,
                model_version=self.model_version, latency_ms=1.0,
                is_borderline=False, raw_confidence=0.96, error=False,
            )
        # Otherwise benign → SILENT.
        return ClassificationResult(
            label="non_offensive", confidence=0.93, is_offensive=False,
            model_version=self.model_version, latency_ms=1.0,
            is_borderline=False, raw_confidence=0.93, error=False,
        )

    async def health(self):
        return (HealthState.OK, "demo stub")


def h(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def section(title: str) -> None:
    print("\n" + "=" * 64)
    print(f"  {title}")
    print("=" * 64)


def main() -> None:
    with TestClient(app) as client:
        # Swap in the deterministic classifier AFTER lifespan built the real one.
        # _run_pipeline reads app.state.classifier per call, so this takes effect.
        app.state.classifier = DemoClassifier()

        # --- 1. Parent onboarding ------------------------------------------
        section("1. Parent registers (MVP bootstrap)")
        r = client.post("/v1/parent/register", json={"display_name": "Demo Parent"})
        r.raise_for_status()
        parent = r.json()
        parent_auth = {"Authorization": f"Bearer {parent['parent_token']}"}
        print(f"   parent_id = {parent['parent_id']}")

        section("2. Parent issues a child + a pairing code")
        r = client.post("/v1/parent/children", json={"display_name": "Demo Child"}, headers=parent_auth)
        r.raise_for_status()
        child_id = r.json()["child_id"]
        print(f"   child_id = {child_id}")
        r = client.post("/v1/parent/pairing-code", json={"child_id": child_id}, headers=parent_auth)
        r.raise_for_status()
        code = r.json()["code"]
        print(f"   pairing code (OTP) = {code}")

        section("3. Child device redeems the OTP → device token")
        r = client.post("/v1/pair", json={"code": code, "device_fingerprint": "demo-pixel-7"})
        r.raise_for_status()
        device = r.json()
        device_auth = {"Authorization": f"Bearer {device['device_token']}"}
        print(f"   role={device['role']}  token={device['device_token'][:10]}…")

        # --- 4. Child posts a batch of captured messages -------------------
        section("4. Child app uploads a batch of captured messages")
        offensive_text = "אתה מטומטם ואני שונא אותך"          # → ALERT_DIRECT
        borderline_text = "גבולי: לא ברור אם זו בדיחה או איום"  # → REVIEW_NEEDED
        benign_text = "נתראה מחר אחרי בית הספר"                 # → SILENT
        events = [
            {"client_msg_id": "m1", "app_package": "com.whatsapp", "text": offensive_text,
             "text_hash": h(offensive_text), "captured_at": time.time(), "direction": "inbound"},
            {"client_msg_id": "m2", "app_package": "com.instagram.android", "text": borderline_text,
             "text_hash": h(borderline_text), "captured_at": time.time(), "direction": "inbound"},
            {"client_msg_id": "m3", "app_package": "com.whatsapp", "text": benign_text,
             "text_hash": h(benign_text), "captured_at": time.time(), "direction": "outbound"},
            # m4 duplicates m1's text_hash → server dedups it.
            {"client_msg_id": "m4", "app_package": "com.whatsapp", "text": offensive_text,
             "text_hash": h(offensive_text), "captured_at": time.time(), "direction": "inbound"},
        ]
        r = client.post(
            "/v1/monitor/events",
            json={"session_id": "sess-1", "child_id": child_id, "events": events},
            headers=device_auth,
        )
        r.raise_for_status()
        batch = r.json()
        print(f"   accepted={batch['accepted']}  deduped={batch['deduped']}  flagged={batch['flagged']}")
        for ack in batch["acks"]:
            tag = f"flag={ack['flag_id']}" if ack.get("flag_id") else ""
            print(f"     {ack['client_msg_id']}: {ack['status']:<9} flagged={ack['flagged']} {tag}")

        # --- 5. Parent reviews the flagged events --------------------------
        section("5. Parent lists flagged events")
        r = client.get("/v1/parent/alerts?include_acked=true", headers=parent_auth)
        r.raise_for_status()
        alerts = r.json()
        for a in alerts:
            print(f"   [{a['status']:<13}] {a['label']}/{a['severity']:<8} {a['app_package']:<22} «{a['quote']}»")

        # --- 6. Parent reacts to the borderline case (the human verdict) ---
        section("6. Parent labels the borderline case (feeds training)")
        borderline = next((a for a in alerts if a["status"] == "review_needed"), None)
        if borderline:
            r = client.post(
                f"/v1/parent/alerts/{borderline['flag_id']}/react",
                json={"action": "label", "label": "offensive"},
                headers=parent_auth,
            )
            r.raise_for_status()
            updated = r.json()
            print(f"   flag {borderline['flag_id']}: parent_label={updated['parent_label']} status={updated['status']}")
        else:
            print("   (no review_needed event found)")

        # --- 7. Daily digest ------------------------------------------------
        section("7. Daily digest is built (once-a-day aggregation)")
        r = client.post("/internal/digest/run")
        r.raise_for_status()
        run = r.json()
        print(f"   digests_built={run['digests_built']} for children={run['child_ids']}")
        today = time.strftime("%Y-%m-%d", time.localtime())
        r = client.get(f"/v1/parent/digests/{today}", headers=parent_auth)
        if r.status_code == 200:
            for d in r.json():
                print(f"   {d['date']}  total={d['total_flagged']}  review_needed={d['review_needed']}  "
                      f"by_severity={d['by_severity']}  by_label={d['by_label']}")
        else:
            print(f"   digest fetch → {r.status_code}")

        # --- 8. Export labeled examples for training -----------------------
        section("8. Export parent-labeled examples (DictaBERT training bridge)")
        r = client.get("/v1/parent/labels/export", headers=parent_auth)
        r.raise_for_status()
        for row in r.json():
            print(f"   classifier={row['label']}  parent_label={row['parent_label']}  «{row['quote']}»")

        section("DONE — child capture → flag → digest → parent review/react verified end-to-end")


if __name__ == "__main__":
    main()
