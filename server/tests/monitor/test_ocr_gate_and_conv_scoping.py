"""Tests for OCR gibberish gate and conversation_id scoping on the monitor path.

Covers:
  (ii)  The OCR gate drops the garbled segment from the confirmed false-alarm case.
  (iii) Screenshot segments get a per-screenshot conversation_id that is distinct
        from the text-event conversation_id.
  (i)   Two different conversation_ids for the same child (covered in depth in
        test_conversation_scoping.py; brief integration check here).

Run from repo root:
    .\\server\\.venv\\Scripts\\python.exe -m pytest server/tests/monitor/test_ocr_gate_and_conv_scoping.py -q
"""

from __future__ import annotations

import asyncio
import hashlib
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

from app.monitor.router import _looks_like_text, _select_text_segments


# ---------------------------------------------------------------------------
# (ii) OCR gibberish gate — unit tests on _looks_like_text
# ---------------------------------------------------------------------------


class TestLooksLikeText:
    """Unit tests for the _looks_like_text gate."""

    def test_drops_confirmed_garbled_segment(self):
        """The exact garbled segment from the confirmed false-alarm case must be dropped."""
        garbled = "09/06/2026 תדושות.ארגוו ה.- ו8.-.קרן | 4%"
        assert _looks_like_text(garbled) is False, (
            f"Expected garbled segment to be dropped: {garbled!r}"
        )

    def test_keeps_real_hebrew_message(self):
        """A real Hebrew message must pass the gate."""
        assert _looks_like_text("Daria: אנחנו לא יכולים, לא אני ולא בעלי 😭") is True

    def test_keeps_simple_hebrew(self):
        assert _looks_like_text("שלום עולם") is True

    def test_keeps_latin_message(self):
        assert _looks_like_text("hello world this is a message") is True

    def test_drops_timestamp_only(self):
        assert _looks_like_text("10:42") is False

    def test_drops_separator(self):
        assert _looks_like_text("--- --- ---") is False

    def test_drops_empty(self):
        assert _looks_like_text("") is False
        assert _looks_like_text("   ") is False

    def test_drops_short_fragment(self):
        # "ה.-ו" has no run of 3 consecutive alpha chars
        assert _looks_like_text("ה.-ו") is False

    def test_keeps_violence_threat(self):
        """An actual threatening Hebrew message must pass the gate."""
        assert _looks_like_text("אני אהרוג אותך") is True

    def test_keeps_mixed_hebrew_english(self):
        assert _looks_like_text("WhatsApp: שלום בוקר טוב") is True

    def test_keeps_abusive_hebrew(self):
        assert _looks_like_text("אתה טמבל גדול") is True

    def test_drops_digits_and_symbols_only(self):
        # All non-alpha non-space
        assert _looks_like_text("12345 67890") is False

    def test_drops_low_alpha_ratio(self):
        # Lots of dots/dashes, very few letters → ratio below threshold
        assert _looks_like_text("... --- ...ה... --- ...") is False


class TestSelectTextSegments:
    """Integration tests for _select_text_segments using the OCR gate."""

    def test_drops_garbled_segment_from_tuple(self):
        """The garbled segment must be excluded by _select_text_segments."""
        garbled = "09/06/2026 תדושות.ארגוו ה.- ו8.-.קרן | 4%"
        real = "שלום עולם"
        result = _select_text_segments((garbled, real))
        assert garbled not in result, f"Garbled segment should be dropped: {garbled!r}"
        assert real in result, f"Real segment should be kept: {real!r}"

    def test_keeps_all_real_segments(self):
        segments = ("שלום עולם", "מה שלומך", "אני בסדר")
        result = _select_text_segments(segments)
        assert len(result) == 3

    def test_empty_tuple(self):
        assert _select_text_segments(()) == []

    def test_deduplication(self):
        """Exact duplicate segments are removed."""
        result = _select_text_segments(("שלום", "שלום", "עולם"))
        assert len(result) == 2


# ---------------------------------------------------------------------------
# (iii) Screenshot segments get per-screenshot conversation_id
# ---------------------------------------------------------------------------


def test_screenshot_segments_get_per_screenshot_conv_id(monkeypatch, tmp_path):
    """When the image endpoint handles a screenshot, all segments must be
    ingested under a single conversation_id derived from client_msg_id.

    We spy on MonitorIngest.ingest_batch to capture the conversation_id kwarg.
    """
    # Import here so monkeypatching env vars takes effect before app load.
    monkeypatch.setenv("AUDIT_DB_PATH", str(tmp_path / "audit.db"))
    monkeypatch.setenv("CONTEXT_AGENT_ENABLED", "false")
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "99999")
    monkeypatch.setenv("IDENTITY_BACKEND", "memory")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    from fastapi.testclient import TestClient
    from app.main import app
    from app.identity.in_memory_adapter import InMemoryIdentityStore
    from app.schemas import ClassificationResult, HealthState, OcrResult

    class _BenignClassifier:
        model_version = "stub-conv-id"
        backend_name = "stub-conv-id"

        async def classify(self, text: str) -> ClassificationResult:
            return ClassificationResult(
                label="non_offensive", confidence=0.95, is_offensive=False,
                model_version=self.model_version, latency_ms=1.0,
                is_borderline=False, raw_confidence=0.95, error=False,
            )

        async def health(self):
            return (HealthState.OK, "stub")

    def _two_line_ocr() -> OcrResult:
        return OcrResult(
            extracted_text="שלום\nעולם",
            confidence=0.9, lang_detected=("heb",), bbox_count=2,
            image_unreadable=False, backend="stub",
            line_segments=("שלום", "עולם"),
        )

    def _seed_identity():
        store = InMemoryIdentityStore()

        async def _setup():
            parent_id, _ = await store.register_parent()
            child = await store.issue_child(parent_id, "Test Child")
            pc = await store.create_pairing_code(parent_id, child.child_id)
            ctx = await store.redeem_pairing_code(pc.code, "fp-conv-id-test")
            return store, child.child_id, ctx.device_token

        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_setup())
        finally:
            loop.close()

    identity_store, child_id, device_token = _seed_identity()

    # Minimal valid JPEG bytes.
    minimal_jpeg = (
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

    captured: dict = {}
    client_msg_id = str(uuid.uuid4())

    with TestClient(app, raise_server_exceptions=True) as client:
        app.state.classifier = _BenignClassifier()
        app.state.context_agent = None
        app.state.identity = identity_store
        app.state.ocr.process = AsyncMock(return_value=_two_line_ocr())

        original_ingest_batch = app.state.monitor.ingest_batch

        async def _spy_ingest_batch(request, batch, *, trace_id, **kwargs):
            captured.update(kwargs)
            return await original_ingest_batch(request, batch, trace_id=trace_id, **kwargs)

        app.state.monitor.ingest_batch = _spy_ingest_batch

        resp = client.post(
            "/v1/monitor/image",
            files={"image": ("screenshot.jpg", io.BytesIO(minimal_jpeg), "image/jpeg")},
            data={
                "child_id": child_id,
                "session_id": "sess-conv-id-001",
                "client_msg_id": client_msg_id,
                "captured_at": str(time.time()),
                "direction": "screen",
            },
            headers={"Authorization": f"Bearer {device_token}"},
        )

    assert resp.status_code == 202, f"Got {resp.status_code}: {resp.text}"

    # The screenshot-level conversation_id must be "screenshot:<client_msg_id>".
    expected_conv_id = f"screenshot:{client_msg_id}"
    actual_conv_id = captured.get("conversation_id")
    assert actual_conv_id == expected_conv_id, (
        f"Expected conversation_id={expected_conv_id!r}, got {actual_conv_id!r}"
    )
