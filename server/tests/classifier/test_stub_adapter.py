"""Unit tests for StubClassifier."""

from __future__ import annotations

import pytest

from app.classifier import StubClassifier, TextClassifier
from app.schemas import ClassificationResult, HealthState


@pytest.mark.asyncio
async def test_stub_is_text_classifier() -> None:
    stub = StubClassifier()
    assert isinstance(stub, TextClassifier)


@pytest.mark.asyncio
async def test_stub_model_version() -> None:
    stub = StubClassifier()
    assert stub.model_version == "stub"


@pytest.mark.asyncio
async def test_stub_health() -> None:
    stub = StubClassifier()
    state, detail = await stub.health()
    assert state == HealthState.OK
    assert isinstance(detail, str)
    assert detail  # non-empty


@pytest.mark.asyncio
async def test_stub_classify_returns_documented_result() -> None:
    stub = StubClassifier()
    result = await stub.classify("שלום עולם")
    assert isinstance(result, ClassificationResult)
    assert result.label == "non_offensive"
    assert result.confidence == 0.5
    assert result.is_offensive is False
    assert result.is_borderline is True  # 0.5 falls inside default [0.3, 0.7]
    assert result.raw_confidence == 0.5
    assert result.error is False
    assert result.model_version == "stub"
    assert result.latency_ms >= 0.0


@pytest.mark.asyncio
async def test_stub_classify_does_not_raise_on_empty_input() -> None:
    """Stub is the documented exception — it always returns a fixed result."""
    stub = StubClassifier()
    for s in ["", "   ", "x", "א" * 10_000]:
        result = await stub.classify(s)
        assert result.error is False
        assert result.label == "non_offensive"


@pytest.mark.asyncio
async def test_stub_classify_does_not_raise_on_none() -> None:
    """Type smuggling: None should still not propagate an exception."""
    stub = StubClassifier()
    result = await stub.classify(None)  # type: ignore[arg-type]
    assert isinstance(result, ClassificationResult)
