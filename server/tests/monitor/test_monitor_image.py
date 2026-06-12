"""Tests for POST /v1/monitor/image (screenshot OCR → monitor pipeline).

Scenarios covered:
  1. Blank OCR result → 202, accepted=0, ocr_text_len=0 (no-text screenshot is not an error).
  2. OCR returns offensive Hebrew text → 202, flagged=1, ocr_text_len>0.
  3. OCR returns benign text → 202, flagged=0, ocr_text_len>0.
  4. Server-side dedup: same OCR text twice → second call deduped.
  5. Auth: missing token → 401.
  6. Auth: wrong child_id → 403.

OCR is stubbed by monkeypatching ``app.state.ocr.process``; the classifier
stub is the same ``_FixedClassifier`` pattern used in test_monitor_ingest.py.
Identity is seeded via a real InMemoryIdentityStore (same as S2 auth tests).

Run from repo root:
    python -m pytest server/tests/monitor/test_monitor_image.py -q
"""

from __future__ import annotations

import asyncio
import io
import sys
import time
import uuid
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

_SERVER_DIR = str(Path(__file__).resolve().parents[2])
if _SERVER_DIR not in sys.path:
    sys.path.insert(0, _SERVER_DIR)

from fastapi.testclient import TestClient

from app.main import app
from app.identity import InMemoryIdentityStore
from app.schemas import ClassificationResult, HealthState, OcrResult


# ---------------------------------------------------------------------------
# Shared stub helpers
# ---------------------------------------------------------------------------


class _OffensiveClassifier:
    """Always classifies text as offensive (abusive, 0.97)."""

    model_version = "stub-image-test"
    backend_name = "stub-image-test"

    async def classify(self, text: str) -> ClassificationResult:
        return ClassificationResult(
            label="abusive",
            confidence=0.97,
            is_offensive=True,
            model_version=self.model_version,
            latency_ms=1.0,
            is_borderline=False,
            raw_confidence=0.97,
            error=False,
        )

    async def health(self):
        return (HealthState.OK, "stub")


class _BenignClassifier:
    """Always classifies text as non-offensive."""

    model_version = "stub-benign"
    backend_name = "stub-benign"

    async def classify(self, text: str) -> ClassificationResult:
        return ClassificationResult(
            label="non_offensive",
            confidence=0.95,
            is_offensive=False,
            model_version=self.model_version,
            latency_ms=1.0,
            is_borderline=False,
            raw_confidence=0.95,
            error=False,
        )

    async def health(self):
        return (HealthState.OK, "stub")


def _blank_ocr_result() -> OcrResult:
    """OCR that found no text (blank screenshot)."""
    return OcrResult(
        extracted_text="",
        confidence=0.0,
        lang_detected=(),
        bbox_count=0,
        image_unreadable=False,
        backend="stub",
    )


def _offensive_ocr_result() -> OcrResult:
    """OCR that extracted offensive Hebrew text."""
    return OcrResult(
        extracted_text="אתה טמבל גדול",
        confidence=0.92,
        lang_detected=("heb",),
        bbox_count=3,
        image_unreadable=False,
        backend="stub",
    )


def _benign_ocr_result() -> OcrResult:
    """OCR that extracted benign Hebrew text."""
    return OcrResult(
        extracted_text="שלום מה שלומך",
        confidence=0.95,
        lang_detected=("heb",),
        bbox_count=3,
        image_unreadable=False,
        backend="stub",
    )


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _seed_identity() -> tuple[str, str]:
    """Create a paired child device in an InMemoryIdentityStore.

    Returns (child_id, device_token) via the full pairing flow.
    The store is stored as a module-level side-effect so callers can inject
    it onto app.state.identity inside the TestClient context.
    """
    store = InMemoryIdentityStore()

    async def _setup():
        parent_id, _ = await store.register_parent()
        child = await store.issue_child(parent_id, "Test Child")
        pc = await store.create_pairing_code(parent_id, child.child_id)
        ctx = await store.redeem_pairing_code(pc.code, "fp-image-test")
        return store, child.child_id, ctx.device_token

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_setup())
    finally:
        loop.close()


def _minimal_jpeg() -> bytes:
    """Return a minimal valid JPEG (1×1 white pixel) for multipart uploads."""
    # Smallest valid JPEG bytes.
    return (
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t"
        b"\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a"
        b"\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342\x1e"
        b'BB99\x1aB" '
        b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
        b"\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00"
        b"\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b"
        b"\xff\xc4\x00\xb5\x10\x00\x02\x01\x03\x03\x02\x04\x03\x05\x05\x04"
        b"\x04\x00\x00\x01}\x01\x02\x03\x00\x04\x11\x05\x12!1A\x06\x13Qa"
        b'\x07"q\x142\x81\x91\xa1\x08#B\xb1\xc1\x15R\xd1\xf0$3br\x82\t\n\x16'
        b"\x17\x18\x19\x1a%&'()*456789:CDEFGHIJKLMNOPQRSTUVWXYZ"
        b"cdefghijklmnopqrstuvwxyz\x83\x84\x85\x86\x87\x88\x89\x8a\x92\x93"
        b"\x94\x95\x96\x97\x98\x99\x9a\xa2\xa3\xa4\xa5\xa6\xa7\xa8\xa9\xaa"
        b"\xb2\xb3\xb4\xb5\xb6\xb7\xb8\xb9\xba\xc2\xc3\xc4\xc5\xc6\xc7\xc8"
        b"\xc9\xca\xd2\xd3\xd4\xd5\xd6\xd7\xd8\xd9\xda\xe1\xe2\xe3\xe4\xe5"
        b"\xe6\xe7\xe8\xe9\xea\xf1\xf2\xf3\xf4\xf5\xf6\xf7\xf8\xf9\xfa"
        b"\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xfb\xd4P\x00\x00\x00\x1f\xff\xd9"
    )


def _post_image(
    client: TestClient,
    child_id: str,
    device_token: str | None,
    jpeg_bytes: bytes | None = None,
    client_msg_id: str | None = None,
    session_id: str = "sess-001",
    captured_at: float | None = None,
    direction: str = "screen",
    child_id_override: str | None = None,
) -> object:
    """POST /v1/monitor/image with the given parameters."""
    headers = {}
    if device_token is not None:
        headers["Authorization"] = f"Bearer {device_token}"

    files = {
        "image": ("screenshot.jpg", io.BytesIO(jpeg_bytes or _minimal_jpeg()), "image/jpeg"),
    }
    data = {
        "child_id": child_id_override if child_id_override is not None else child_id,
        "session_id": session_id,
        "client_msg_id": client_msg_id or str(uuid.uuid4()),
        "captured_at": str(captured_at or time.time()),
        "direction": direction,
    }
    return client.post(
        "/v1/monitor/image",
        files=files,
        data=data,
        headers=headers,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_blank_ocr_returns_accepted_zero(monkeypatch, tmp_path):
    """Blank OCR result → 202 with accepted=0, ocr_text_len=0.

    A screenshot that yields no extractable text is NOT an error — the device
    may upload a purely graphical screenshot.
    """
    monkeypatch.setenv("AUDIT_DB_PATH", str(tmp_path / "audit.db"))
    monkeypatch.setenv("CONTEXT_AGENT_ENABLED", "false")
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "99999")
    monkeypatch.setenv("IDENTITY_BACKEND", "memory")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    identity_store, child_id, device_token = _seed_identity()

    with TestClient(app, raise_server_exceptions=True) as client:
        app.state.classifier = _BenignClassifier()
        app.state.context_agent = None
        app.state.identity = identity_store
        # Stub OCR to return blank text.
        app.state.ocr.process = AsyncMock(return_value=_blank_ocr_result())

        resp = _post_image(client, child_id, device_token)

    assert resp.status_code == 202, f"Expected 202, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert body["accepted"] == 0
    assert body["deduped"] == 0
    assert body["flagged"] == 0
    assert body["acks"] == []
    assert body["ocr_text_len"] == 0


def test_offensive_ocr_text_is_flagged(monkeypatch, tmp_path):
    """OCR yields offensive Hebrew → 202, flagged=1, ocr_text_len>0."""
    monkeypatch.setenv("AUDIT_DB_PATH", str(tmp_path / "audit.db"))
    monkeypatch.setenv("CONTEXT_AGENT_ENABLED", "false")
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "99999")
    monkeypatch.setenv("IDENTITY_BACKEND", "memory")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    identity_store, child_id, device_token = _seed_identity()

    with TestClient(app, raise_server_exceptions=True) as client:
        app.state.classifier = _OffensiveClassifier()
        app.state.context_agent = None
        app.state.identity = identity_store
        app.state.ocr.process = AsyncMock(return_value=_offensive_ocr_result())

        resp = _post_image(client, child_id, device_token)

    assert resp.status_code == 202, f"Expected 202, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert body["accepted"] == 1
    assert body["flagged"] == 1
    assert body["ocr_text_len"] > 0
    assert len(body["acks"]) == 1
    assert body["acks"][0]["flagged"] is True
    assert body["acks"][0]["status"] == "processed"


def test_benign_ocr_text_not_flagged(monkeypatch, tmp_path):
    """OCR yields benign Hebrew → 202, flagged=0, ocr_text_len>0."""
    monkeypatch.setenv("AUDIT_DB_PATH", str(tmp_path / "audit.db"))
    monkeypatch.setenv("CONTEXT_AGENT_ENABLED", "false")
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "99999")
    monkeypatch.setenv("IDENTITY_BACKEND", "memory")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    identity_store, child_id, device_token = _seed_identity()

    with TestClient(app, raise_server_exceptions=True) as client:
        app.state.classifier = _BenignClassifier()
        app.state.context_agent = None
        app.state.identity = identity_store
        app.state.ocr.process = AsyncMock(return_value=_benign_ocr_result())

        resp = _post_image(client, child_id, device_token)

    assert resp.status_code == 202, f"Expected 202, got {resp.status_code}: {resp.text}"
    body = resp.json()
    assert body["accepted"] == 1
    assert body["flagged"] == 0
    assert body["ocr_text_len"] > 0
    assert len(body["acks"]) == 1
    assert body["acks"][0]["flagged"] is False


def test_duplicate_screenshot_deduped(monkeypatch, tmp_path):
    """Same screenshot (same OCR text) sent twice → second is deduped."""
    monkeypatch.setenv("AUDIT_DB_PATH", str(tmp_path / "audit.db"))
    monkeypatch.setenv("CONTEXT_AGENT_ENABLED", "false")
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "99999")
    monkeypatch.setenv("IDENTITY_BACKEND", "memory")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    identity_store, child_id, device_token = _seed_identity()

    with TestClient(app, raise_server_exceptions=True) as client:
        app.state.classifier = _OffensiveClassifier()
        app.state.context_agent = None
        app.state.identity = identity_store
        # Both calls yield the SAME OCR text → same text_hash → dedup fires.
        app.state.ocr.process = AsyncMock(return_value=_offensive_ocr_result())

        resp1 = _post_image(client, child_id, device_token, client_msg_id="img-001")
        resp2 = _post_image(client, child_id, device_token, client_msg_id="img-002")

    assert resp1.status_code == 202
    body1 = resp1.json()
    assert body1["accepted"] == 1
    assert body1["flagged"] == 1

    assert resp2.status_code == 202
    body2 = resp2.json()
    # Second upload: text_hash already seen → deduped.
    assert body2["accepted"] == 0
    assert body2["deduped"] == 1
    assert body2["flagged"] == 0


def test_missing_token_returns_401(monkeypatch, tmp_path):
    """No Authorization header → 401."""
    monkeypatch.setenv("AUDIT_DB_PATH", str(tmp_path / "audit.db"))
    monkeypatch.setenv("CONTEXT_AGENT_ENABLED", "false")
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "99999")
    monkeypatch.setenv("IDENTITY_BACKEND", "memory")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    identity_store, child_id, _token = _seed_identity()

    with TestClient(app, raise_server_exceptions=True) as client:
        app.state.classifier = _BenignClassifier()
        app.state.context_agent = None
        app.state.identity = identity_store
        app.state.ocr.process = AsyncMock(return_value=_benign_ocr_result())

        # Pass device_token=None so no Authorization header is sent.
        resp = _post_image(client, child_id, device_token=None)

    assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.text}"


def test_wrong_child_id_returns_403(monkeypatch, tmp_path):
    """Token belongs to child-A but form sends child_id=child-B → 403."""
    monkeypatch.setenv("AUDIT_DB_PATH", str(tmp_path / "audit.db"))
    monkeypatch.setenv("CONTEXT_AGENT_ENABLED", "false")
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "99999")
    monkeypatch.setenv("IDENTITY_BACKEND", "memory")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    identity_store, child_id, device_token = _seed_identity()

    with TestClient(app, raise_server_exceptions=True) as client:
        app.state.classifier = _BenignClassifier()
        app.state.context_agent = None
        app.state.identity = identity_store
        app.state.ocr.process = AsyncMock(return_value=_benign_ocr_result())

        # child_id_override makes the form send a different child_id than the token.
        resp = _post_image(
            client,
            child_id,
            device_token,
            child_id_override="wrong-child-id-xyz",
        )

    assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"
