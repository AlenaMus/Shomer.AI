"""TextClassifier Protocol contract tests.

Reference: docs/design/classifier/design.md §2.5, docs/design/README.md §5.

Parametrized over every concrete adapter so every adapter is held to the
same behavioural contract. Adding a new adapter requires only adding it
to ``ADAPTERS`` — no new test functions.

Contract invariants (every adapter MUST satisfy):
1. ``classify()`` returns a ``ClassificationResult``.
2. ``label`` is in the 5-value Category set.
3. ``0.0 <= confidence <= 1.0``.
4. ``is_offensive == (label != "non_offensive")``.
5. ``is_borderline == (BORDERLINE_LOW <= confidence <= BORDERLINE_HIGH)``.
6. ``classify()`` NEVER raises — feeding bad input returns ``error=True``.
7. The adapter satisfies ``isinstance(adapter, TextClassifier)`` (runtime check).
8. ``await adapter.health()`` returns a ``(HealthState, str)`` tuple.
"""

from __future__ import annotations

from pathlib import Path
from typing import get_args

import httpx
import pytest
import respx

from app.classifier import (
    ClassifierSettings,
    ConfidenceCalibrator,
    HuggingFaceClassifier,
    OllamaDictaBertClassifier,
    StubClassifier,
    TextClassifier,
)
from app.ollama_client import OllamaClient
from app.schemas import Category, ClassificationResult, HealthState


VALID_LABELS = set(get_args(Category))


# ---------------------------------------------------------------------------
# Adapter builders — each returns a TextClassifier-compatible instance,
# plus a callable that exercises the happy path (mocking transport if needed).
# ---------------------------------------------------------------------------


def _build_stub() -> StubClassifier:
    return StubClassifier()


def _build_ollama() -> OllamaDictaBertClassifier:
    return OllamaDictaBertClassifier(
        ollama=OllamaClient(base_url="http://localhost:11434", model="t"),
        settings=ClassifierSettings(),
        calibrator=ConfidenceCalibrator(method="none"),
    )


def _hf_can_construct() -> bool:
    """Skip the HF case unless a fine-tuned checkpoint is present."""
    settings = ClassifierSettings()
    return Path(settings.dictabert_model_path).exists()


@pytest.fixture(
    params=["stub", "ollama"]
    + (["huggingface"] if _hf_can_construct() else [])
)
def adapter_name(request: pytest.FixtureRequest) -> str:
    return request.param


@pytest.fixture
def adapter(adapter_name: str) -> TextClassifier:
    if adapter_name == "stub":
        return _build_stub()
    if adapter_name == "ollama":
        return _build_ollama()
    if adapter_name == "huggingface":
        return HuggingFaceClassifier(ClassifierSettings())
    raise ValueError(f"unknown adapter {adapter_name!r}")


# ---------------------------------------------------------------------------
# Happy-path helpers — each adapter has a different way of being "happy".
# ---------------------------------------------------------------------------


def _mock_ollama_ok(label: str = "abusive", confidence: float = 0.88):
    """Wire respx to return a well-formed Ollama JSON reply."""
    import json as _json

    route = respx.post("http://localhost:11434/api/generate")
    route.mock(
        return_value=httpx.Response(
            200,
            json={
                "response": _json.dumps(
                    {
                        "category": label,
                        "is_offensive": label != "non_offensive",
                        "confidence": confidence,
                    }
                )
            },
        )
    )
    return route


# ---------------------------------------------------------------------------
# Contract tests
# ---------------------------------------------------------------------------


def test_runtime_checkable(adapter: TextClassifier) -> None:
    """Every adapter satisfies ``isinstance(adapter, TextClassifier)``."""
    assert isinstance(adapter, TextClassifier), (
        f"{type(adapter).__name__} is not a TextClassifier"
    )


def test_model_version_nonempty(adapter: TextClassifier) -> None:
    assert isinstance(adapter.model_version, str)
    assert adapter.model_version


@pytest.mark.asyncio
async def test_health_returns_tuple(adapter: TextClassifier) -> None:
    """``await adapter.health()`` returns ``(HealthState, str)``."""
    # Ollama adapter may probe the real server which isn't running in CI.
    # That is fine — we only assert the SHAPE, not the value.
    if isinstance(adapter, OllamaDictaBertClassifier):
        # Stub the transport so we don't depend on local Ollama for the contract.
        async with respx.mock(assert_all_called=False) as router:
            router.get("http://localhost:11434/api/tags").mock(
                return_value=httpx.Response(200, json={"models": []})
            )
            state, detail = await adapter.health()
    else:
        state, detail = await adapter.health()
    assert isinstance(state, HealthState)
    assert isinstance(detail, str)


@pytest.mark.asyncio
async def test_classify_happy_path(
    adapter: TextClassifier, adapter_name: str
) -> None:
    """Happy-path classification yields a valid ClassificationResult."""
    if adapter_name == "ollama":
        async with respx.mock(assert_all_called=False):
            _mock_ollama_ok(label="abusive", confidence=0.88)
            result = await adapter.classify("שלום")
    else:
        result = await adapter.classify("שלום")

    assert isinstance(result, ClassificationResult)
    assert result.label in VALID_LABELS
    assert 0.0 <= result.confidence <= 1.0
    assert 0.0 <= result.raw_confidence <= 1.0


@pytest.mark.asyncio
async def test_is_offensive_derivation(
    adapter: TextClassifier, adapter_name: str
) -> None:
    """``is_offensive`` is always ``label != "non_offensive"``."""
    if adapter_name == "ollama":
        async with respx.mock(assert_all_called=False):
            _mock_ollama_ok(label="non_offensive", confidence=0.9)
            result = await adapter.classify("שלום")
    else:
        result = await adapter.classify("שלום")

    assert result.is_offensive == (result.label != "non_offensive")


@pytest.mark.asyncio
async def test_is_borderline_derivation(
    adapter: TextClassifier, adapter_name: str
) -> None:
    """``is_borderline`` is consistent with ``confidence`` vs the thresholds.

    Default settings: low=0.3, high=0.7. We don't know what the adapter
    will *actually* return for arbitrary input, but whatever it returns
    must satisfy the derivation rule.
    """
    settings = ClassifierSettings()
    if adapter_name == "ollama":
        async with respx.mock(assert_all_called=False):
            _mock_ollama_ok(label="abusive", confidence=0.55)
            result = await adapter.classify("borderline test")
    else:
        result = await adapter.classify("שלום")

    expected = settings.borderline_low <= result.confidence <= settings.borderline_high
    assert result.is_borderline == expected


@pytest.mark.asyncio
async def test_classify_never_raises_on_bad_input(
    adapter: TextClassifier, adapter_name: str
) -> None:
    """Deliberately bad input returns ``error=True`` instead of raising.

    Per the Protocol contract, the only "input" guaranteed not to raise is
    the textual one. We exercise: empty string, whitespace-only, None.
    """
    bad_inputs = ["", "   ", None]
    for bad in bad_inputs:
        # The Protocol takes a str, so for None we have to bypass typing.
        result = await adapter.classify(bad)  # type: ignore[arg-type]
        assert isinstance(result, ClassificationResult)
        # The stub doesn't care about input — it's the documented exception:
        # it always returns a fixed result. Every other adapter must mark errors.
        if adapter_name == "stub":
            continue
        if bad in ("", "   ", None):
            assert result.error is True
            assert result.label == "non_offensive"
            assert result.confidence == 0.5


@pytest.mark.asyncio
async def test_classify_never_raises_on_transport_failure(
    adapter: TextClassifier, adapter_name: str
) -> None:
    """Backend exploding mid-call yields ``error=True`` — not an exception.

    For Stub there's nothing to break, so it's trivially OK.
    For HuggingFace the model is in-process; we cannot kill it cleanly in
    a portable test so we skip it (covered elsewhere).
    For Ollama we mock a ConnectError.
    """
    if adapter_name == "stub":
        result = await adapter.classify("שלום")
        assert result.error is False
        return
    if adapter_name == "huggingface":
        pytest.skip("transport-failure injection is adapter-specific")
        return

    async with respx.mock(assert_all_called=False):
        respx.post("http://localhost:11434/api/generate").mock(
            side_effect=httpx.ConnectError("simulated")
        )
        result = await adapter.classify("שלום")

    assert isinstance(result, ClassificationResult)
    assert result.error is True
    assert result.label == "non_offensive"
    assert result.confidence == 0.5
