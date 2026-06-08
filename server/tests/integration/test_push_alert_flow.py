"""Integration test for the monitoring-flow PUSH/ALERT paths.

`test_full_flow.py` covers the legacy synchronous `/classify` alert path. This
file covers the **monitoring flow** (the real product surface): a paired child
device uploads captured messages and the server fires the two push triggers:

  1. **Critical-immediate push** — `MonitorIngest` step 6: a flagged event with
     ``status="alerted"`` AND severity in (high, critical) → `on_critical_flag`
     closure → ``notifier.send_alert`` with ``message_id="critical:{flag_id}"``.
     (Note: `abusive` caps at *medium* severity, so it does NOT fire this; we
     use a `pornographic` message, which is always-alert AND grades to *high*.)
  2. **Daily-digest push** — `POST /internal/digest/run` →
     `DigestScheduler.deliver` → ``send_alert`` with ``message_id="digest:..."``.

Both paths use the lifespan-constructed notifier instance (captured in closures),
so we select it deterministically with ``ALERTS_CHANNEL=stub`` and assert on the
``StubNotifier`` that ``app.state.notifier`` exposes. The classifier is swapped
for a keyword stub so labels/severities are deterministic (no Ollama needed).
"""

from __future__ import annotations

import hashlib
import sys
import time
import uuid
from pathlib import Path

import pytest

_SERVER_DIR = str(Path(__file__).resolve().parents[2])
if _SERVER_DIR not in sys.path:
    sys.path.insert(0, _SERVER_DIR)

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.schemas import ClassificationResult, HealthState  # noqa: E402


# --------------------------------------------------------------------------- #
# Deterministic keyword classifier (the only faked component)
# --------------------------------------------------------------------------- #


class _DemoClassifier:
    model_version = "demo-stub"
    backend_name = "demo-stub"

    async def classify(self, text: str) -> ClassificationResult:
        t = text.strip()
        # pornographic → always-alert + high severity → fires critical-immediate.
        if "עירום" in t or "פורנו" in t:
            return ClassificationResult(
                label="pornographic", confidence=0.95, is_offensive=True,
                model_version=self.model_version, latency_ms=1.0,
                is_borderline=False, raw_confidence=0.95, error=False,
            )
        # benign → SILENT (not flagged, no push).
        return ClassificationResult(
            label="non_offensive", confidence=0.93, is_offensive=False,
            model_version=self.model_version, latency_ms=1.0,
            is_borderline=False, raw_confidence=0.93, error=False,
        )

    async def health(self):
        return (HealthState.OK, "demo stub")


def _h(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# Fixture: real composition root, in-memory stores, StubNotifier channel
# --------------------------------------------------------------------------- #


@pytest.fixture
def monitor_client(tmp_path, monkeypatch):
    """TestClient over the real lifespan() with the monitor stack on in-memory
    backends and ``ALERTS_CHANNEL=stub`` so every push is captured.

    Yields (client, stub_notifier). The notifier is NOT swapped post-startup:
    the critical-immediate + digest closures capture the lifespan instance, so
    it must be the StubNotifier from construction time (selected via env).
    """
    monkeypatch.setenv("AUDIT_DB_PATH", str(tmp_path / "audit.db"))
    monkeypatch.setenv("DEDUP_BACKEND", "memory")
    monkeypatch.setenv("FLAGGED_BACKEND", "memory")
    monkeypatch.setenv("IDENTITY_BACKEND", "memory")
    monkeypatch.setenv("DIGEST_BACKEND", "manual")
    monkeypatch.setenv("DIGEST_ENABLED", "true")
    monkeypatch.setenv("DIGEST_CRITICAL_IMMEDIATE", "true")
    monkeypatch.setenv("DIGEST_ALLOW_MANUAL_TRIGGER", "true")
    monkeypatch.setenv("CONTEXT_AGENT_ENABLED", "false")
    monkeypatch.setenv("ALERTS_CHANNEL", "stub")
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "99999")

    with TestClient(app, raise_server_exceptions=True) as client:
        # The pipeline reads app.state.classifier per call → deterministic verdicts.
        app.state.classifier = _DemoClassifier()
        notifier = app.state.notifier
        # Guard the test's core premise: the captured channel is the StubNotifier.
        assert notifier.__class__.__name__ == "StubNotifier"
        yield client, notifier


def _pair_child(client) -> tuple[dict, dict, str]:
    """Register parent → issue child → pairing code → pair device.

    Returns (parent_headers, device_headers, child_id).
    """
    p = client.post("/v1/parent/register", json={"display_name": "IT Parent"}).json()
    ph = {"Authorization": f"Bearer {p['parent_token']}"}
    child_id = client.post(
        "/v1/parent/children", json={"display_name": "IT Child"}, headers=ph
    ).json()["child_id"]
    code = client.post(
        "/v1/parent/pairing-code", json={"child_id": child_id}, headers=ph
    ).json()["code"]
    dev = client.post(
        "/v1/pair", json={"code": code, "device_fingerprint": "it-device"}
    ).json()
    dh = {"Authorization": f"Bearer {dev['device_token']}"}
    return ph, dh, child_id


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #


def test_monitor_flow_fires_critical_immediate_and_digest_push(monitor_client):
    """End-to-end: upload → critical-immediate push → digest push, all captured."""
    client, notifier = monitor_client
    ph, dh, child_id = _pair_child(client)

    porn = "שלח לי תמונות עירום עכשיו"   # → pornographic/high → alerted
    benign = "נתראה מחר אחרי בית הספר"     # → SILENT (no push, no flag)
    events = [
        {"client_msg_id": "c1", "app_package": "com.whatsapp", "text": porn,
         "text_hash": _h(porn), "captured_at": time.time(), "direction": "inbound"},
        {"client_msg_id": "c2", "app_package": "com.whatsapp", "text": benign,
         "text_hash": _h(benign), "captured_at": time.time(), "direction": "outbound"},
    ]
    r = client.post(
        "/v1/monitor/events",
        json={"session_id": f"s-{uuid.uuid4().hex[:6]}", "child_id": child_id, "events": events},
        headers=dh,
    )
    assert r.status_code in (200, 202), r.text
    batch = r.json()
    assert batch["flagged"] >= 1  # the pornographic message flagged

    # --- 1. Critical-immediate push fired during ingest (synchronous in-request).
    critical_pushes = [q for q in notifier.requests if q.message_id.startswith("critical:")]
    assert len(critical_pushes) == 1, (
        f"expected 1 critical-immediate push, got {[q.message_id for q in notifier.requests]}"
    )
    cp = critical_pushes[0]
    assert cp.child_id == child_id
    assert cp.label == "pornographic"
    assert cp.severity in ("high", "critical")
    # And the channel actually marked it sent.
    assert notifier._history[0].sent is True

    # --- 2. Daily-digest push fires on the manual run.
    before = len(notifier.requests)
    run = client.post("/internal/digest/run")
    assert run.status_code == 200, run.text
    assert run.json()["digests_built"] >= 1

    digest_pushes = [q for q in notifier.requests if q.message_id.startswith("digest:")]
    assert len(digest_pushes) == 1, (
        f"expected 1 digest push, got {[q.message_id for q in notifier.requests]}"
    )
    assert len(notifier.requests) > before
    assert digest_pushes[0].child_id == child_id

    # --- 3. The same flag is visible on the parent surface (dashboard pull path).
    alerts = client.get("/v1/parent/alerts?include_acked=true", headers=ph).json()
    assert any(a["label"] == "pornographic" for a in alerts)


def test_benign_only_batch_produces_no_push(monitor_client):
    """A batch with no offensive content fires no push (negative control)."""
    client, notifier = monitor_client
    ph, dh, child_id = _pair_child(client)

    benign = "מה שלומך היום"
    events = [
        {"client_msg_id": "b1", "app_package": "com.whatsapp", "text": benign,
         "text_hash": _h(benign), "captured_at": time.time(), "direction": "inbound"},
    ]
    r = client.post(
        "/v1/monitor/events",
        json={"session_id": "s-benign", "child_id": child_id, "events": events},
        headers=dh,
    )
    assert r.status_code in (200, 202), r.text
    assert r.json()["flagged"] == 0
    # No critical push.
    assert not [q for q in notifier.requests if q.message_id.startswith("critical:")]
    # Digest run builds nothing to push (no flagged events today).
    client.post("/internal/digest/run")
    assert not [q for q in notifier.requests if q.message_id.startswith("digest:")]
