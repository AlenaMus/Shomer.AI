"""Tests for context-source routing on the POST /v1/monitor/image endpoint.

Scenarios covered:
  1. Screenshot with multiple OCR lines → pipeline receives conversation_turns
     containing all lines (integration check: CA sees provided_history).
  2. Screenshot OCR lines are NOT persisted to the conversations table after
     image ingest (assert ``read_conversation_history`` stays empty).
  3. Text monitor event (/v1/monitor/events) → still persisted as a turn
     (regression guard for the text path).

The pipeline is exercised through FastAPI TestClient so the full wiring
(router → ingest → _run_pipeline → CA) is exercised.  We use:
  - A multi-line OcrResult with ``line_segments`` set.
  - A capturing stub that records whether it received ``conversation_turns``.
  - Context Agent DISABLED so we don't need an LLM; instead we verify the
    pipeline kwarg plumbing by inspecting what ``ingest_batch`` was called with.

Run from repo root:
    python -m pytest server/tests/monitor/test_monitor_image_context_routing.py -q
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import sys
import time
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

_SERVER_DIR = str(Path(__file__).resolve().parents[2])
if _SERVER_DIR not in sys.path:
    sys.path.insert(0, _SERVER_DIR)

from fastapi.testclient import TestClient

from app.main import app
from app.identity import InMemoryIdentityStore
from app.schemas import ClassificationResult, HealthState, OcrResult
from app.audit_log.in_memory_adapter import InMemoryAuditStore


# ---------------------------------------------------------------------------
# Shared stubs
# ---------------------------------------------------------------------------


class _BenignClassifier:
    model_version = "stub-ctx-routing"
    backend_name = "stub-ctx-routing"

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


def _multi_line_ocr_result() -> OcrResult:
    """OCR result with two distinct line segments (a simple chat exchange)."""
    return OcrResult(
        extracted_text="מה שלומך\nשלום עולם",
        confidence=0.90,
        lang_detected=("heb",),
        bbox_count=4,
        image_unreadable=False,
        backend="stub",
        line_segments=("מה שלומך", "שלום עולם"),
    )


def _seed_identity() -> tuple:
    """Create a paired child device in an InMemoryIdentityStore."""
    store = InMemoryIdentityStore()

    async def _setup():
        parent_id, _ = await store.register_parent()
        child = await store.issue_child(parent_id, "Test Child")
        pc = await store.create_pairing_code(parent_id, child.child_id)
        ctx = await store.redeem_pairing_code(pc.code, "fp-ctx-routing")
        return store, child.child_id, ctx.device_token

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_setup())
    finally:
        loop.close()


def _minimal_jpeg() -> bytes:
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


def _post_image(client, child_id, device_token, session_id="sess-ctx-001",
               client_msg_id=None):
    headers = {"Authorization": f"Bearer {device_token}"}
    files = {
        "image": ("screenshot.jpg", io.BytesIO(_minimal_jpeg()), "image/jpeg"),
    }
    data = {
        "child_id": child_id,
        "session_id": session_id,
        "client_msg_id": client_msg_id or str(uuid.uuid4()),
        "captured_at": str(time.time()),
        "direction": "screen",
    }
    return client.post("/v1/monitor/image", files=files, data=data, headers=headers)


# ---------------------------------------------------------------------------
# Test 1: screenshot with multiple lines → ingest_batch receives conversation_turns
# ---------------------------------------------------------------------------


def test_image_ingest_passes_conversation_turns_to_pipeline(monkeypatch, tmp_path):
    """When the image endpoint handles a multi-line screenshot, it must call
    ``monitor.ingest_batch`` with a non-None ``conversation_turns`` that
    contains the OCR segments.

    We spy on ``MonitorIngest.ingest_batch`` to capture the kwarg.
    """
    monkeypatch.setenv("AUDIT_DB_PATH", str(tmp_path / "audit.db"))
    monkeypatch.setenv("CONTEXT_AGENT_ENABLED", "false")
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "99999")
    monkeypatch.setenv("IDENTITY_BACKEND", "memory")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    identity_store, child_id, device_token = _seed_identity()

    captured_kwargs: dict = {}

    with TestClient(app, raise_server_exceptions=True) as client:
        app.state.classifier = _BenignClassifier()
        app.state.context_agent = None
        app.state.identity = identity_store
        app.state.ocr.process = AsyncMock(return_value=_multi_line_ocr_result())

        original_ingest_batch = app.state.monitor.ingest_batch

        async def _spying_ingest_batch(request, batch, *, trace_id, **kwargs):
            captured_kwargs.update(kwargs)
            return await original_ingest_batch(
                request, batch, trace_id=trace_id, **kwargs
            )

        app.state.monitor.ingest_batch = _spying_ingest_batch

        resp = _post_image(client, child_id, device_token)

    assert resp.status_code == 202, f"Got {resp.status_code}: {resp.text}"

    # conversation_turns must have been passed and must contain both segments.
    assert "conversation_turns" in captured_kwargs, (
        "ingest_batch was not called with conversation_turns"
    )
    turns = captured_kwargs["conversation_turns"]
    assert turns is not None, "conversation_turns must not be None for image path"
    assert len(turns) == 2, f"Expected 2 turns (one per segment), got {len(turns)}"

    texts_in_turns = {t["text"] for t in turns}
    assert "מה שלומך" in texts_in_turns, f"First segment missing from turns: {texts_in_turns}"
    assert "שלום עולם" in texts_in_turns, f"Second segment missing from turns: {texts_in_turns}"

    for turn in turns:
        assert turn.get("role") == "screenshot_line", (
            f"Expected role='screenshot_line', got {turn.get('role')}"
        )


# ---------------------------------------------------------------------------
# Test 2: screenshot lines are NOT persisted to conversations table
# ---------------------------------------------------------------------------


def test_image_ingest_does_not_persist_turns_to_conversations_table(
    monkeypatch, tmp_path
):
    """Screenshot OCR lines must NOT be written to the per-child conversations
    table.  After image ingest, ``read_conversation_history`` must return an
    empty list for that child.
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
        app.state.ocr.process = AsyncMock(return_value=_multi_line_ocr_result())

        resp = _post_image(client, child_id, device_token)

        # Inspect the conversation history synchronously using the real audit store.
        async def _check_history():
            return await app.state.audit_store.read_conversation_history(
                child_id, last_n_turns=10
            )

        loop = asyncio.new_event_loop()
        try:
            history = loop.run_until_complete(_check_history())
        finally:
            loop.close()

    assert resp.status_code == 202, f"Got {resp.status_code}: {resp.text}"
    assert history == [] or len(history) == 0, (
        f"Expected empty conversation history after image ingest, "
        f"got {len(history)} turns: {[t.text for t in history]}"
    )


# ---------------------------------------------------------------------------
# Test 3: text monitor event IS persisted (regression guard)
# ---------------------------------------------------------------------------


def test_text_event_is_still_persisted_to_conversations_table(
    monkeypatch, tmp_path
):
    """Text monitor events (/v1/monitor/events) must still be persisted to the
    conversations table — the image-path skip must not affect the text path.
    """
    monkeypatch.setenv("AUDIT_DB_PATH", str(tmp_path / "audit.db"))
    monkeypatch.setenv("CONTEXT_AGENT_ENABLED", "false")
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "99999")
    monkeypatch.setenv("IDENTITY_BACKEND", "memory")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    identity_store, child_id, device_token = _seed_identity()
    test_text = "שלום עולם טקסט"
    text_hash = hashlib.sha256(test_text.encode()).hexdigest()

    event_payload = {
        "session_id": "sess-text-persist",
        "child_id": child_id,
        "events": [
            {
                "client_msg_id": str(uuid.uuid4()),
                "app_package": "com.example.app",
                "text": test_text,
                "text_hash": text_hash,
                "captured_at": time.time(),
                "direction": "outbound",
            }
        ],
    }

    with TestClient(app, raise_server_exceptions=True) as client:
        app.state.classifier = _BenignClassifier()
        app.state.context_agent = None
        app.state.identity = identity_store

        resp = client.post(
            "/v1/monitor/events",
            json=event_payload,
            headers={"Authorization": f"Bearer {device_token}"},
        )

        # Read conversation history from the live audit store.
        # The text event has app_package="com.example.app" and no explicit
        # conversation_id, so MonitorIngest resolves it to "com.example.app"
        # (the app_package fallback).  We must read with the same key.
        async def _check_history():
            return await app.state.audit_store.read_conversation_history(
                child_id, last_n_turns=10, conversation_id="com.example.app"
            )

        loop2 = asyncio.new_event_loop()
        try:
            history = loop2.run_until_complete(_check_history())
        finally:
            loop2.close()

    assert resp.status_code == 202, f"Got {resp.status_code}: {resp.text}"
    assert len(history) == 1, (
        f"Expected 1 conversation turn for text event, got {len(history)}. "
        f"(Turn is stored under conversation_id='com.example.app' — the app_package fallback)"
    )
    assert history[0].text == test_text
