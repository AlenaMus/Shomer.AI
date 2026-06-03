"""Unit tests for StubOcrBackend."""

from __future__ import annotations

import pytest

from app.ocr.stub_adapter import StubOcrBackend
from app.schemas import HealthState, OcrResult


@pytest.fixture
def stub() -> StubOcrBackend:
    return StubOcrBackend()


@pytest.mark.asyncio
async def test_returns_fixed_ocr_result(stub: StubOcrBackend) -> None:
    result = await stub.process(b"anything")
    assert isinstance(result, OcrResult)
    assert result.extracted_text == "STUB_OCR_TEXT"
    assert result.confidence == 0.99
    assert result.lang_detected == ("heb",)
    assert result.bbox_count == 1
    assert result.image_unreadable is False
    assert result.backend == "stub"


@pytest.mark.asyncio
async def test_backend_name(stub: StubOcrBackend) -> None:
    assert stub.backend_name == "stub"


@pytest.mark.asyncio
async def test_health_ok(stub: StubOcrBackend) -> None:
    state, detail = await stub.health()
    assert state == HealthState.OK
    assert isinstance(detail, str)


@pytest.mark.asyncio
async def test_never_raises_on_empty_bytes(stub: StubOcrBackend) -> None:
    result = await stub.process(b"")
    assert isinstance(result, OcrResult)


@pytest.mark.asyncio
async def test_never_raises_on_garbage_bytes(stub: StubOcrBackend) -> None:
    result = await stub.process(bytes(range(16)))
    assert isinstance(result, OcrResult)


@pytest.mark.asyncio
async def test_mime_type_ignored(stub: StubOcrBackend) -> None:
    """StubOcrBackend always returns the same result regardless of mime_type."""
    r1 = await stub.process(b"x", mime_type="image/jpeg")
    r2 = await stub.process(b"x", mime_type="image/png")
    assert r1.extracted_text == r2.extracted_text
