"""OcrBackend Protocol contract tests.

Parametrized over all concrete adapters so every adapter is held to the same
behavioural contract.  Adding a new adapter requires only adding it to
``ADAPTERS`` — no new test functions.

Contract invariants (per docs/design/ocr/design.md §2.5):
1. ``process()`` returns an ``OcrResult`` instance.
2. ``0.0 <= confidence <= 1.0``  OR  ``image_unreadable=True``.
3. ``lang_detected`` is a ``tuple`` and all entries are ``str``.
4. ``process()`` NEVER raises — tested with empty bytes, garbage bytes,
   oversized bytes (all should return ``image_unreadable=True``).
5. The adapter is an instance of ``OcrBackend`` (runtime_checkable Protocol).
6. ``await adapter.health()`` returns a ``(HealthState, str)`` tuple.
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from app.ocr import OcrBackend
from app.ocr.stub_adapter import StubOcrBackend
from app.ocr.tesseract_adapter import TesseractOcrBackend
from app.schemas import HealthState, OcrResult

# Needed for isinstance checks in contract assertions
_STUB_TYPE = StubOcrBackend


# ---------------------------------------------------------------------------
# Adapter fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def stub_adapter() -> StubOcrBackend:
    return StubOcrBackend()


@pytest.fixture
def tesseract_adapter() -> TesseractOcrBackend:
    return TesseractOcrBackend()


# Parametrize over both adapters using indirect fixture approach.
# The string IDs here match what conftest.py below provides.
ADAPTER_FIXTURE_NAMES = ["stub_adapter", "tesseract_adapter"]


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _is_tesseract(adapter: object) -> bool:
    return isinstance(adapter, TesseractOcrBackend)


# ---------------------------------------------------------------------------
# Contract tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter_fixture", ADAPTER_FIXTURE_NAMES)
async def test_process_returns_ocr_result(
    request: pytest.FixtureRequest,
    adapter_fixture: str,
    english_png_bytes: bytes,
) -> None:
    """process() must always return an OcrResult instance."""
    adapter = request.getfixturevalue(adapter_fixture)
    if _is_tesseract(adapter):
        health, _ = await adapter.health()
        if health != HealthState.OK:
            pytest.skip("Tesseract not available")
    result = await adapter.process(english_png_bytes)
    assert isinstance(result, OcrResult), (
        f"Expected OcrResult, got {type(result)}"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter_fixture", ADAPTER_FIXTURE_NAMES)
async def test_confidence_in_range_or_unreadable(
    request: pytest.FixtureRequest,
    adapter_fixture: str,
    english_png_bytes: bytes,
) -> None:
    """confidence must be in [0.0, 1.0] unless image_unreadable=True."""
    adapter = request.getfixturevalue(adapter_fixture)
    if _is_tesseract(adapter):
        health, _ = await adapter.health()
        if health != HealthState.OK:
            pytest.skip("Tesseract not available")
    result = await adapter.process(english_png_bytes)
    if not result.image_unreadable:
        assert 0.0 <= result.confidence <= 1.0, (
            f"confidence {result.confidence} out of [0,1]"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter_fixture", ADAPTER_FIXTURE_NAMES)
async def test_lang_detected_is_tuple_of_strings(
    request: pytest.FixtureRequest,
    adapter_fixture: str,
    english_png_bytes: bytes,
) -> None:
    """lang_detected must be a tuple of strings."""
    adapter = request.getfixturevalue(adapter_fixture)
    if _is_tesseract(adapter):
        health, _ = await adapter.health()
        if health != HealthState.OK:
            pytest.skip("Tesseract not available")
    result = await adapter.process(english_png_bytes)
    assert isinstance(result.lang_detected, tuple), (
        f"lang_detected is {type(result.lang_detected)}, expected tuple"
    )
    for entry in result.lang_detected:
        assert isinstance(entry, str), (
            f"lang_detected entry {entry!r} is not str"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter_fixture", ADAPTER_FIXTURE_NAMES)
async def test_process_never_raises_on_empty_bytes(
    request: pytest.FixtureRequest,
    adapter_fixture: str,
    empty_bytes: bytes,
) -> None:
    """process() must not raise on empty bytes.

    Real adapters (Tesseract) must return image_unreadable=True.
    StubOcrBackend is a deterministic test double that always returns a fixed
    OcrResult regardless of input — checking that it does not raise is
    sufficient for the stub.
    """
    adapter = request.getfixturevalue(adapter_fixture)
    result = await adapter.process(empty_bytes)
    assert isinstance(result, OcrResult)
    if not isinstance(adapter, StubOcrBackend):
        assert result.image_unreadable is True


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter_fixture", ADAPTER_FIXTURE_NAMES)
async def test_process_never_raises_on_garbage_bytes(
    request: pytest.FixtureRequest,
    adapter_fixture: str,
    garbage_bytes: bytes,
) -> None:
    """process() must not raise on random garbage bytes.

    Real adapters must set image_unreadable=True.
    The StubOcrBackend test double is exempt — it always returns a fixed result.
    """
    adapter = request.getfixturevalue(adapter_fixture)
    result = await adapter.process(garbage_bytes)
    assert isinstance(result, OcrResult)
    if not isinstance(adapter, StubOcrBackend):
        assert result.image_unreadable is True


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter_fixture", ADAPTER_FIXTURE_NAMES)
async def test_process_never_raises_on_oversized_bytes(
    request: pytest.FixtureRequest,
    adapter_fixture: str,
    oversized_bytes: bytes,
) -> None:
    """process() must not raise when bytes exceed the configured size limit."""
    adapter = request.getfixturevalue(adapter_fixture)
    result = await adapter.process(oversized_bytes)
    assert isinstance(result, OcrResult)
    # StubOcrBackend does not enforce size limits — only TesseractOcrBackend
    # sets image_unreadable=True on oversized input.
    if _is_tesseract(adapter):
        assert result.image_unreadable is True


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter_fixture", ADAPTER_FIXTURE_NAMES)
async def test_adapter_satisfies_protocol(
    request: pytest.FixtureRequest,
    adapter_fixture: str,
) -> None:
    """isinstance check against the runtime_checkable OcrBackend Protocol."""
    adapter = request.getfixturevalue(adapter_fixture)
    assert isinstance(adapter, OcrBackend), (
        f"{type(adapter).__name__} does not satisfy OcrBackend Protocol"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter_fixture", ADAPTER_FIXTURE_NAMES)
async def test_health_returns_state_and_string(
    request: pytest.FixtureRequest,
    adapter_fixture: str,
) -> None:
    """health() must return (HealthState, str)."""
    adapter = request.getfixturevalue(adapter_fixture)
    result = await adapter.health()
    assert isinstance(result, tuple), f"health() returned {type(result)}"
    assert len(result) == 2, f"health() tuple has {len(result)} elements"
    state, detail = result
    assert isinstance(state, HealthState), (
        f"health()[0] is {type(state)}, expected HealthState"
    )
    assert isinstance(detail, str), (
        f"health()[1] is {type(detail)}, expected str"
    )
