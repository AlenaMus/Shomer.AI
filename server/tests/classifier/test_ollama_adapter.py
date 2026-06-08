"""Unit tests for OllamaDictaBertClassifier.

Mocks ``OllamaClient``'s HTTP transport via ``respx``.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from app.classifier import (
    ClassifierSettings,
    ConfidenceCalibrator,
    OllamaDictaBertClassifier,
    TextClassifier,
)
from app.ollama_client import OllamaClient
from app.schemas import ClassificationResult, HealthState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ollama_response(label: str, confidence: float, is_offensive: bool | None = None):
    body = {
        "category": label,
        "confidence": confidence,
    }
    if is_offensive is not None:
        body["is_offensive"] = is_offensive
    return httpx.Response(200, json={"response": json.dumps(body)})


def _make_adapter(
    *,
    settings: ClassifierSettings | None = None,
    calibrator: ConfidenceCalibrator | None = None,
) -> OllamaDictaBertClassifier:
    settings = settings or ClassifierSettings()
    return OllamaDictaBertClassifier(
        ollama=OllamaClient(base_url="http://localhost:11434", model="t"),
        settings=settings,
        calibrator=calibrator or ConfidenceCalibrator(method="none"),
    )


# ---------------------------------------------------------------------------
# Protocol smoke
# ---------------------------------------------------------------------------


def test_isinstance_protocol() -> None:
    assert isinstance(_make_adapter(), TextClassifier)


def test_model_version_default() -> None:
    # Pass explicit settings so the test is independent of the active .env
    # (CLASSIFIER_MODEL_VERSION may be set to v1.1-dictabert in production).
    settings = ClassifierSettings(CLASSIFIER_MODEL_VERSION="v1.0-standin")
    assert _make_adapter(settings=settings).model_version == "v1.0-standin"


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_classify_abusive_confident() -> None:
    # Pass explicit settings so the test is independent of the active .env.
    settings = ClassifierSettings(CLASSIFIER_MODEL_VERSION="v1.0-standin")
    adapter = _make_adapter(settings=settings)
    async with respx.mock(assert_all_called=True) as router:
        router.post("http://localhost:11434/api/generate").mock(
            return_value=_ollama_response("abusive", 0.88)
        )
        result = await adapter.classify("תפסיק להיות כזה לוזר")

    assert isinstance(result, ClassificationResult)
    assert result.label == "abusive"
    assert result.confidence == pytest.approx(0.88)
    assert result.raw_confidence == pytest.approx(0.88)
    assert result.is_offensive is True
    assert result.is_borderline is False  # 0.88 > 0.7
    assert result.error is False
    assert result.model_version == "v1.0-standin"
    assert result.latency_ms >= 0.0


@pytest.mark.asyncio
async def test_classify_borderline_confidence_marks_borderline() -> None:
    adapter = _make_adapter()
    async with respx.mock(assert_all_called=True) as router:
        router.post("http://localhost:11434/api/generate").mock(
            return_value=_ollama_response("abusive", 0.55)
        )
        result = await adapter.classify("borderline")

    assert result.is_borderline is True
    assert result.confidence == pytest.approx(0.55)
    assert result.error is False


@pytest.mark.asyncio
async def test_classify_non_offensive_is_not_offensive() -> None:
    adapter = _make_adapter()
    async with respx.mock(assert_all_called=True) as router:
        router.post("http://localhost:11434/api/generate").mock(
            return_value=_ollama_response("non_offensive", 0.92)
        )
        result = await adapter.classify("שלום, איך הולך?")

    assert result.label == "non_offensive"
    assert result.is_offensive is False


# ---------------------------------------------------------------------------
# Legacy label normalization — review.md G-02
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_legacy_hyphenated_label_normalized_to_underscore() -> None:
    """``"none-offensive"`` (legacy hyphen) must surface as ``"non_offensive"``.

    Per LLD §5.2 / review.md G-02 the parse_model_output() defensive path is
    retained for malformed inputs; we exercise it here.
    """
    adapter = _make_adapter()
    async with respx.mock(assert_all_called=True) as router:
        router.post("http://localhost:11434/api/generate").mock(
            return_value=httpx.Response(
                200,
                json={
                    "response": json.dumps(
                        {"category": "none-offensive", "confidence": 0.9}
                    )
                },
            )
        )
        result = await adapter.classify("שלום")

    assert result.label == "non_offensive"
    assert result.is_offensive is False


# ---------------------------------------------------------------------------
# Failure modes — never raise
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ollama_connect_error_returns_review_result() -> None:
    adapter = _make_adapter()
    async with respx.mock(assert_all_called=True) as router:
        router.post("http://localhost:11434/api/generate").mock(
            side_effect=httpx.ConnectError("simulated")
        )
        result = await adapter.classify("שלום")

    assert result.error is True
    assert result.label == "non_offensive"
    assert result.confidence == 0.5
    assert result.raw_confidence == 0.5


@pytest.mark.asyncio
async def test_ollama_timeout_returns_review_result() -> None:
    adapter = _make_adapter()
    async with respx.mock(assert_all_called=True) as router:
        router.post("http://localhost:11434/api/generate").mock(
            side_effect=httpx.ReadTimeout("simulated")
        )
        result = await adapter.classify("שלום")

    assert result.error is True
    assert result.label == "non_offensive"


@pytest.mark.asyncio
async def test_ollama_http_500_returns_review_result() -> None:
    adapter = _make_adapter()
    async with respx.mock(assert_all_called=True) as router:
        router.post("http://localhost:11434/api/generate").mock(
            return_value=httpx.Response(500, text="boom")
        )
        result = await adapter.classify("שלום")

    assert result.error is True
    assert result.label == "non_offensive"


@pytest.mark.asyncio
async def test_malformed_json_returns_review_result() -> None:
    """Ollama returns a non-JSON body — parser fails — fallback."""
    adapter = _make_adapter()
    async with respx.mock(assert_all_called=True) as router:
        router.post("http://localhost:11434/api/generate").mock(
            return_value=httpx.Response(
                200, json={"response": "this is not json at all"}
            )
        )
        result = await adapter.classify("שלום")

    assert result.error is True


@pytest.mark.asyncio
async def test_empty_text_returns_review_result() -> None:
    adapter = _make_adapter()
    # No transport call expected — adapter rejects empty input before HTTP.
    async with respx.mock(assert_all_called=False):
        result = await adapter.classify("")
    assert result.error is True
    assert result.label == "non_offensive"


@pytest.mark.asyncio
async def test_whitespace_only_returns_review_result() -> None:
    adapter = _make_adapter()
    async with respx.mock(assert_all_called=False):
        result = await adapter.classify("   \n\t")
    assert result.error is True


# ---------------------------------------------------------------------------
# Truncation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_long_text_is_truncated_and_classified() -> None:
    adapter = _make_adapter()
    async with respx.mock(assert_all_called=True) as router:
        route = router.post("http://localhost:11434/api/generate").mock(
            return_value=_ollama_response("abusive", 0.8)
        )
        result = await adapter.classify("א" * 4000)

    assert result.error is False
    assert result.label == "abusive"
    # Confirm the prompt sent to Ollama contains a truncated body (< original).
    sent_payload = json.loads(route.calls[0].request.content)
    assert len(sent_payload["prompt"]) < 4000 + 100  # rough upper bound


# ---------------------------------------------------------------------------
# Calibration interaction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_calibration_none_returns_raw_conf_unchanged() -> None:
    """``method='none'`` passes raw_confidence through verbatim."""
    adapter = _make_adapter(calibrator=ConfidenceCalibrator(method="none"))
    async with respx.mock(assert_all_called=True) as router:
        router.post("http://localhost:11434/api/generate").mock(
            return_value=_ollama_response("abusive", 0.73)
        )
        result = await adapter.classify("שלום")

    assert result.confidence == result.raw_confidence == pytest.approx(0.73)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_ok_when_ollama_reachable() -> None:
    adapter = _make_adapter()
    async with respx.mock(assert_all_called=True) as router:
        router.get("http://localhost:11434/api/tags").mock(
            return_value=httpx.Response(200, json={"models": []})
        )
        state, detail = await adapter.health()
    assert state == HealthState.OK
    assert "reachable" in detail.lower()


@pytest.mark.asyncio
async def test_health_down_when_ollama_unreachable() -> None:
    adapter = _make_adapter()
    async with respx.mock(assert_all_called=True) as router:
        router.get("http://localhost:11434/api/tags").mock(
            side_effect=httpx.ConnectError("nope")
        )
        state, detail = await adapter.health()
    assert state == HealthState.DOWN
    assert "unreachable" in detail.lower()
