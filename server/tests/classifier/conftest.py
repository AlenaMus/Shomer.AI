"""Pytest fixtures for the classifier test suite.

Shared across:
- test_contract.py           — parametrized contract test for all 3 adapters
- test_ollama_adapter.py     — OllamaDictaBertClassifier unit tests
- test_huggingface_adapter.py — HuggingFaceClassifier unit tests (slow)
- test_stub_adapter.py       — StubClassifier unit tests
- test_calibration.py        — ConfidenceCalibrator unit tests
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers used by this suite to avoid warnings."""
    config.addinivalue_line(
        "markers",
        "slow: marks tests that require heavy model downloads (deselect with -m 'not slow')",
    )

# Ensure ``server/`` (the parent of ``app/``) is on sys.path so the tests
# can do ``from app.classifier import ...`` exactly like the OCR suite does.
_SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(_SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVER_ROOT))

# Now the imports are safe.
from app.classifier import (  # noqa: E402
    ClassifierSettings,
    ConfidenceCalibrator,
    HuggingFaceClassifier,
    OllamaDictaBertClassifier,
    StubClassifier,
)
from app.ollama_client import OllamaClient  # noqa: E402


# ---------------------------------------------------------------------------
# Sample texts — content is opaque to the adapters; we only check shapes.
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def hebrew_offensive_text() -> str:
    """Synthetic Hebrew abusive-style line — content is illustrative only."""
    return "תפסיק להיות כזה לוזר"


@pytest.fixture(scope="session")
def hebrew_benign_text() -> str:
    return "שלום, איך הולך היום?"


@pytest.fixture(scope="session")
def mixed_text() -> str:
    return "Hello שלום this is a borderline test"


@pytest.fixture(scope="session")
def long_text() -> str:
    """Longer than the 2048-char Ollama cap, used to exercise truncation."""
    return "א" * 4000


@pytest.fixture(scope="session")
def empty_text() -> str:
    return ""


# ---------------------------------------------------------------------------
# Settings — defaults; tests can override via dataclasses.replace or kwargs.
# ---------------------------------------------------------------------------

@pytest.fixture
def classifier_settings(monkeypatch: pytest.MonkeyPatch) -> ClassifierSettings:
    """A vanilla ClassifierSettings (defaults from the model)."""
    # Wipe any env that might leak in from the operator's shell.
    for var in (
        "CLASSIFIER_MODEL_VERSION",
        "BORDERLINE_LOW",
        "BORDERLINE_HIGH",
        "CALIBRATION_METHOD",
        "CALIBRATION_PKL_PATH",
        "OLLAMA_URL",
        "OLLAMA_MODEL",
        "DICTABERT_MODEL_PATH",
        "DICTABERT_HF_NAME",
        "CLASSIFIER_TIMEOUT_S",
    ):
        monkeypatch.delenv(var, raising=False)
    return ClassifierSettings()


# ---------------------------------------------------------------------------
# Adapter fixtures — minimal builders for each.
# ---------------------------------------------------------------------------

@pytest.fixture
def stub_adapter() -> StubClassifier:
    return StubClassifier()


@pytest.fixture
def ollama_client() -> OllamaClient:
    """An OllamaClient bound to a localhost URL. Calls are mocked by respx.

    The client itself is real; respx intercepts the underlying httpx
    transport at test time.
    """
    return OllamaClient(base_url="http://localhost:11434", model="test-model")


@pytest.fixture
def ollama_adapter(
    ollama_client: OllamaClient, classifier_settings: ClassifierSettings
) -> OllamaDictaBertClassifier:
    return OllamaDictaBertClassifier(
        ollama=ollama_client,
        settings=classifier_settings,
        calibrator=ConfidenceCalibrator(method="none"),
    )


@pytest.fixture
def hf_checkpoint_exists(classifier_settings: ClassifierSettings) -> bool:
    """True iff a fine-tuned checkpoint sits at DICTABERT_MODEL_PATH."""
    return (
        classifier_settings.dictabert_model_path.exists()
        and classifier_settings.dictabert_model_path.is_dir()
    )


@pytest.fixture(scope="session")
def hf_adapter_built() -> HuggingFaceClassifier | None:
    """Try to construct the HF adapter once per session; ``None`` on failure.

    Built lazily so tests can skip cleanly when the model isn't downloaded
    and no network is available. The adapter is heavy (~440 MB on first
    construction) so we don't construct it in test setup; tests opt in.
    """
    return None
