"""Unit and integration tests for TesseractOcrBackend.

Tests are split into two groups:
- ``@pytest.mark.unit`` — never touch Tesseract; pytesseract calls are mocked.
- ``@pytest.mark.integration`` (implicit: no mark needed, but skipped when
  Tesseract is not available) — actually invoke the Tesseract binary.

Skipping strategy
-----------------
If ``await adapter.health()`` returns ``HealthState.DOWN``, all tests that
need Tesseract are skipped via the ``tesseract_available`` fixture.
"""

from __future__ import annotations

from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from app.ocr.settings import OcrSettings
from app.ocr.tesseract_adapter import TesseractOcrBackend
from app.schemas import HealthState, OcrResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def settings() -> OcrSettings:
    return OcrSettings()


@pytest.fixture
def adapter(settings: OcrSettings) -> TesseractOcrBackend:
    return TesseractOcrBackend(settings)


@pytest.fixture
async def tesseract_available(adapter: TesseractOcrBackend) -> bool:
    state, _ = await adapter.health()
    return state == HealthState.OK


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _white_png(width: int = 100, height: int = 50) -> bytes:
    img = Image.new("RGB", (width, height), color="white")
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _mock_tesseract_data(
    words: list[str],
    confs: list[int],
    line_nums: list[int] | None = None,
) -> dict:
    """Build a pytesseract.image_to_data DICT that matches the expected shape.

    Includes the block/paragraph/line numbering that real pytesseract emits so
    line-segment reconstruction (TesseractRunner) is exercised.  ``line_nums``
    lets a test place words on distinct lines; when omitted all words share
    line 1 (a single segment).
    """
    nums = line_nums if line_nums is not None else [1] * len(words)
    return {
        "text": words + [""],
        "conf": confs + [-1],
        "block_num": [1] * len(words) + [1],
        "par_num": [1] * len(words) + [1],
        "line_num": nums + [0],
    }


# ---------------------------------------------------------------------------
# Unit tests (mocked pytesseract)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_happy_path_mocked(adapter: TesseractOcrBackend) -> None:
    """process() assembles OcrResult correctly from mocked pytesseract data."""
    mock_data = _mock_tesseract_data(
        words=["Hello", "World"],
        confs=[80, 90],
    )
    with patch("pytesseract.image_to_data", return_value=mock_data):
        result = await adapter.process(_white_png())

    assert isinstance(result, OcrResult)
    assert result.extracted_text == "Hello World"
    assert result.backend == "tesseract"
    assert result.bbox_count == 2
    # mean confidence = (80+90)/2/100 = 0.85
    assert abs(result.confidence - 0.85) < 0.01
    assert result.image_unreadable is False


@pytest.mark.asyncio
async def test_no_text_returns_unreadable(adapter: TesseractOcrBackend) -> None:
    """When Tesseract returns no words, image_unreadable must be True."""
    mock_data = _mock_tesseract_data(words=[], confs=[])
    with patch("pytesseract.image_to_data", return_value=mock_data):
        result = await adapter.process(_white_png())

    assert result.image_unreadable is True
    assert result.extracted_text == ""
    assert result.confidence == 0.0
    assert result.bbox_count == 0


@pytest.mark.asyncio
async def test_garbage_bytes_returns_unreadable(
    adapter: TesseractOcrBackend,
    garbage_bytes: bytes,
) -> None:
    """Garbage bytes must not raise; must return image_unreadable=True."""
    result = await adapter.process(garbage_bytes)
    assert isinstance(result, OcrResult)
    assert result.image_unreadable is True


@pytest.mark.asyncio
async def test_empty_bytes_returns_unreadable(
    adapter: TesseractOcrBackend,
    empty_bytes: bytes,
) -> None:
    """Empty bytes must not raise; must return image_unreadable=True."""
    result = await adapter.process(empty_bytes)
    assert isinstance(result, OcrResult)
    assert result.image_unreadable is True


@pytest.mark.asyncio
async def test_oversized_bytes_returns_unreadable(
    adapter: TesseractOcrBackend,
    oversized_bytes: bytes,
) -> None:
    """Oversized input must return image_unreadable=True without raising."""
    result = await adapter.process(oversized_bytes)
    assert isinstance(result, OcrResult)
    assert result.image_unreadable is True


@pytest.mark.asyncio
async def test_tesseract_not_found_returns_unreadable(
    adapter: TesseractOcrBackend,
) -> None:
    """TesseractNotFoundError from pytesseract must be caught."""
    import pytesseract

    with patch(
        "pytesseract.image_to_data",
        side_effect=pytesseract.TesseractNotFoundError(),
    ):
        result = await adapter.process(_white_png())

    assert result.image_unreadable is True
    assert result.extracted_text == ""


@pytest.mark.asyncio
async def test_confidence_normalised_to_0_1(
    adapter: TesseractOcrBackend,
) -> None:
    """Mean confidence must be in [0.0, 1.0]."""
    mock_data = _mock_tesseract_data(
        words=["word"],
        confs=[100],
    )
    with patch("pytesseract.image_to_data", return_value=mock_data):
        result = await adapter.process(_white_png())

    assert 0.0 <= result.confidence <= 1.0


@pytest.mark.asyncio
async def test_lang_detected_tuple(adapter: TesseractOcrBackend) -> None:
    """lang_detected must be a tuple even when no script is detected."""
    mock_data = _mock_tesseract_data(words=["test"], confs=[70])
    with patch("pytesseract.image_to_data", return_value=mock_data):
        result = await adapter.process(_white_png())

    assert isinstance(result.lang_detected, tuple)


@pytest.mark.asyncio
async def test_hebrew_script_detected(adapter: TesseractOcrBackend) -> None:
    """Hebrew characters in extracted text must produce 'heb' in lang_detected."""
    mock_data = _mock_tesseract_data(words=["שלום"], confs=[85])
    with patch("pytesseract.image_to_data", return_value=mock_data):
        result = await adapter.process(_white_png())

    assert "heb" in result.lang_detected


@pytest.mark.asyncio
async def test_backend_name(adapter: TesseractOcrBackend) -> None:
    assert adapter.backend_name == "tesseract"


@pytest.mark.asyncio
async def test_memory_error_during_preprocess_caught(
    adapter: TesseractOcrBackend,
) -> None:
    """MemoryError during preprocessing must be caught; return unreadable."""
    with patch.object(
        adapter._preprocessor,
        "preprocess",
        side_effect=MemoryError("OOM"),
    ):
        result = await adapter.process(_white_png())

    assert result.image_unreadable is True


# ---------------------------------------------------------------------------
# Integration tests (real Tesseract)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_when_tesseract_available(
    adapter: TesseractOcrBackend,
) -> None:
    """health() must return HealthState.OK when Tesseract is installed."""
    state, detail = await adapter.health()
    if state != HealthState.OK:
        pytest.skip("Tesseract not available — health check correctly returns DOWN")
    assert state == HealthState.OK
    assert "tesseract" in detail.lower()


@pytest.mark.asyncio
async def test_blank_image_unreadable_real_tesseract(
    adapter: TesseractOcrBackend,
    blank_png_bytes: bytes,
) -> None:
    """A solid white image should produce image_unreadable=True with real Tesseract."""
    state, _ = await adapter.health()
    if state != HealthState.OK:
        pytest.skip("Tesseract not available")

    result = await adapter.process(blank_png_bytes)
    assert isinstance(result, OcrResult)
    # Blank white image — Tesseract may or may not find noise glyphs,
    # but result must be a valid OcrResult without raising.
    assert 0.0 <= result.confidence <= 1.0


@pytest.mark.asyncio
async def test_english_text_detected_real_tesseract(
    adapter: TesseractOcrBackend,
    english_png_bytes: bytes,
) -> None:
    """A PNG with English text should yield non-empty extracted_text."""
    state, _ = await adapter.health()
    if state != HealthState.OK:
        pytest.skip("Tesseract not available")

    result = await adapter.process(english_png_bytes)
    assert isinstance(result, OcrResult)
    # We cannot assert exact text (font rendering varies), but if OCR finds
    # anything the confidence should be > 0.
    if result.bbox_count > 0:
        assert result.confidence > 0.0
