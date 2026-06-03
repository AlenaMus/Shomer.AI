"""Unit tests for HuggingFaceClassifier.

Most tests in this module require the DictaBERT model to be downloaded
(either as a local fine-tune checkpoint at ``DICTABERT_MODEL_PATH`` or via
a first-time HuggingFace download of ``dicta-il/dictabert``). They are
marked ``@pytest.mark.slow`` and skipped automatically when nothing is
available locally.

The contract test (``test_contract.py``) is the primary correctness gate;
this file adds adapter-specific edge cases.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.classifier import (
    ClassifierSettings,
    ConfidenceCalibrator,
    HuggingFaceClassifier,
    TextClassifier,
)
from app.schemas import ClassificationResult, HealthState


# ---------------------------------------------------------------------------
# Availability gate
# ---------------------------------------------------------------------------


def _checkpoint_path() -> Path:
    return ClassifierSettings().dictabert_model_path


def _local_checkpoint_exists() -> bool:
    p = _checkpoint_path()
    return p.exists() and p.is_dir()


def _hf_cached_dictabert() -> bool:
    """Heuristic: has DictaBERT been downloaded into the HF cache?

    We don't want to hammer the network during a "fast" test run. If the
    user has already pulled the model down (e.g. for an earlier session),
    we'll happily run the tests; otherwise we skip with a clear reason.
    """
    try:
        from huggingface_hub import try_to_load_from_cache  # type: ignore[import-untyped]
    except ImportError:
        return False
    cached = try_to_load_from_cache("dicta-il/dictabert", "config.json")
    return cached is not None and cached is not False


def _hf_available() -> bool:
    return _local_checkpoint_exists() or _hf_cached_dictabert()


pytestmark_slow = pytest.mark.slow


# ---------------------------------------------------------------------------
# Cheap construction-time tests — no inference
# ---------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.skipif(
    not _hf_available(),
    reason="DictaBERT not locally available (no checkpoint and not in HF cache)",
)
def test_construction_picks_correct_model_version() -> None:
    settings = ClassifierSettings()
    adapter = HuggingFaceClassifier(settings)
    expected = (
        "v1.1-dictabert"
        if _local_checkpoint_exists()
        else "v1.1-dictabert-base-untrained"
    )
    assert adapter.model_version == expected


@pytest.mark.slow
@pytest.mark.skipif(
    not _hf_available(),
    reason="DictaBERT not locally available",
)
def test_isinstance_protocol() -> None:
    adapter = HuggingFaceClassifier(ClassifierSettings())
    assert isinstance(adapter, TextClassifier)


# ---------------------------------------------------------------------------
# Inference path
# ---------------------------------------------------------------------------


@pytest.mark.slow
@pytest.mark.asyncio
@pytest.mark.skipif(
    not _hf_available(),
    reason="DictaBERT not locally available",
)
async def test_classify_hebrew_text_returns_valid_result() -> None:
    adapter = HuggingFaceClassifier(ClassifierSettings())
    result = await adapter.classify("שלום עולם")

    assert isinstance(result, ClassificationResult)
    assert result.label in {
        "abusive",
        "hate",
        "violence",
        "pornographic",
        "non_offensive",
    }
    assert 0.0 <= result.confidence <= 1.0
    assert 0.0 <= result.raw_confidence <= 1.0
    assert result.error is False
    assert result.is_offensive == (result.label != "non_offensive")


@pytest.mark.slow
@pytest.mark.asyncio
@pytest.mark.skipif(
    not _hf_available(),
    reason="DictaBERT not locally available",
)
async def test_classify_empty_text_returns_review_result() -> None:
    adapter = HuggingFaceClassifier(ClassifierSettings())
    result = await adapter.classify("")
    assert result.error is True
    assert result.label == "non_offensive"
    assert result.confidence == 0.5


@pytest.mark.slow
@pytest.mark.asyncio
@pytest.mark.skipif(
    not _hf_available(),
    reason="DictaBERT not locally available",
)
async def test_health_returns_known_state() -> None:
    adapter = HuggingFaceClassifier(ClassifierSettings())
    state, detail = await adapter.health()
    assert state in {HealthState.OK, HealthState.DEGRADED}
    assert isinstance(detail, str) and detail


# ---------------------------------------------------------------------------
# Fast checks that don't need the model
# ---------------------------------------------------------------------------


def test_module_imports_without_construction() -> None:
    """Importing the adapter class must NOT trigger a model download."""
    # The import already happened at the top of this file. If that had
    # required the model, the test session would have failed during
    # collection. This test exists to document the invariant.
    from app.classifier.huggingface_adapter import HuggingFaceClassifier as Cls

    assert Cls is HuggingFaceClassifier
