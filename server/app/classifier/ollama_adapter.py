"""OllamaDictaBertClassifier — wraps the legacy Ollama call path.

Reference: docs/design/classifier/design.md §2.5 ("OllamaDictaBertClassifier"),
§3.2 (key classes), §8 (failure modes).

This is the v1.0-standin adapter that keeps the existing Qwen-via-Ollama
pipeline working end-to-end while the real DictaBERT fine-tune is in flight.
It composes:

- ``OllamaClient``                   — shared HTTP client; supplied by main.py
- ``ConfidenceCalibrator``           — identity in v1.0; real after Meeting 5
- ``ClassifierSettings``             — borderline thresholds + model_version
- the existing ``build_user_prompt`` / ``parse_model_output`` helpers

The Protocol contract is strict: ``classify()`` NEVER raises. Every exception
is caught, logged, mapped to ``record_error(error_type)``, and a fallback
``ClassificationResult(error=True, label="non_offensive", confidence=0.5)``
is returned so the triage router can mark the request REVIEW_NEEDED.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import cast

import httpx

from ..ollama_client import OllamaClient
from ..prompt import build_user_prompt, parse_model_output
from ..schemas import Category, ClassificationResult, HealthState
from .calibration import ConfidenceCalibrator
from .logging import bind_context
from .metrics import record_classification, record_error
from .settings import ClassifierSettings

# Hard input cap. 512 BERT tokens ≈ 2048 chars for mixed Hebrew/English.
_MAX_INPUT_CHARS = 2048


class OllamaDictaBertClassifier:
    """Ollama-backed TextClassifier adapter.

    Composes an :class:`OllamaClient` + :class:`ConfidenceCalibrator`. The
    Ollama client is shared across the server (one HTTP connection pool)
    and is closed by main.py at shutdown — this adapter does NOT own it.
    """

    def __init__(
        self,
        ollama: OllamaClient,
        settings: ClassifierSettings,
        calibrator: ConfidenceCalibrator | None = None,
    ) -> None:
        self._ollama = ollama
        self._settings = settings
        self._calibrator = calibrator or ConfidenceCalibrator(method="none")
        self._model_version = settings.model_version

    # ------------------------------------------------------------------
    # Protocol surface
    # ------------------------------------------------------------------
    @property
    def model_version(self) -> str:
        return self._model_version

    async def health(self) -> tuple[HealthState, str]:
        """Probe Ollama. Maps to the standard HealthState tri-state."""
        try:
            ok = await self._ollama.is_alive()
        except Exception as exc:  # noqa: BLE001
            return HealthState.DOWN, f"ollama probe raised: {type(exc).__name__}"
        if ok:
            return HealthState.OK, f"ollama reachable; model={self._ollama.model}"
        return HealthState.DOWN, f"ollama unreachable at {self._ollama.base_url}"

    async def classify(self, text: str) -> ClassificationResult:
        """Run text through Ollama. Never raises — returns error result on failure."""
        logger = bind_context(model_version=self._model_version)
        t0 = time.perf_counter()

        # ---- Input validation ----------------------------------------
        if not isinstance(text, str) or not text.strip():
            return self._error_result(
                logger=logger,
                error_type="empty_text",
                detail="empty or non-string input",
                t0=t0,
            )

        text = self._maybe_truncate(text, logger=logger)
        prompt = build_user_prompt(text)

        # ---- Inference ----------------------------------------------
        try:
            raw = await self._ollama.generate_json(prompt)
        except httpx.ConnectError as exc:
            return self._error_result(
                logger=logger,
                error_type="ollama_unreachable",
                detail=f"ConnectError: {exc}",
                t0=t0,
            )
        except httpx.TimeoutException as exc:
            return self._error_result(
                logger=logger,
                error_type="ollama_timeout",
                detail=f"Timeout: {exc}",
                t0=t0,
            )
        except httpx.HTTPStatusError as exc:
            return self._error_result(
                logger=logger,
                error_type="ollama_http_error",
                detail=f"HTTP {exc.response.status_code}",
                t0=t0,
            )
        except asyncio.CancelledError:
            # Propagate cancellation — the contract bans "never raises" only
            # for *model* failure, not for the event loop tearing down.
            raise
        except Exception as exc:  # noqa: BLE001 - defensive catch-all
            return self._error_result(
                logger=logger,
                error_type="ollama_unknown",
                detail=f"{type(exc).__name__}: {exc}",
                t0=t0,
            )

        # ---- Parse --------------------------------------------------
        try:
            parsed = parse_model_output(raw)
        except (ValueError, json.JSONDecodeError) as exc:
            return self._error_result(
                logger=logger,
                error_type="malformed_json",
                detail=f"{type(exc).__name__}: {exc}",
                t0=t0,
            )

        # ---- Build result -------------------------------------------
        raw_conf = float(parsed["confidence"])
        cal_conf = self._calibrator.transform(raw_conf)
        label = cast(Category, parsed["category"])
        is_borderline = (
            self._settings.borderline_low <= cal_conf <= self._settings.borderline_high
        )
        latency_ms = (time.perf_counter() - t0) * 1000.0
        result = ClassificationResult(
            label=label,
            confidence=cal_conf,
            is_offensive=(label != "non_offensive"),
            model_version=self._model_version,
            latency_ms=latency_ms,
            is_borderline=is_borderline,
            raw_confidence=raw_conf,
            error=False,
        )

        # ---- Observability ------------------------------------------
        event = "classification_borderline" if is_borderline else "classification_complete"
        extra: dict = {}
        if is_borderline:
            extra["escalated_to"] = "context_agent"
        logger.info(
            event,
            label=result.label,
            confidence=result.confidence,
            raw_confidence=result.raw_confidence,
            is_borderline=result.is_borderline,
            latency_ms=result.latency_ms,
            adapter="ollama",
            **extra,
        )
        record_classification(
            label=result.label,
            model_version=result.model_version,
            confidence=result.confidence,
            raw_confidence=result.raw_confidence,
            latency_s=latency_ms / 1000.0,
            is_borderline=result.is_borderline,
            error=False,
            calibrated=self._calibrator.is_active,
        )
        return result

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _maybe_truncate(self, text: str, *, logger) -> str:
        if len(text) <= _MAX_INPUT_CHARS:
            return text
        logger.warning(
            "text_truncated",
            original_len=len(text),
            max_chars=_MAX_INPUT_CHARS,
        )
        return text[:_MAX_INPUT_CHARS]

    def _error_result(
        self,
        *,
        logger,
        error_type: str,
        detail: str,
        t0: float,
    ) -> ClassificationResult:
        """Build the standard error fallback and emit the error log + metric."""
        latency_ms = (time.perf_counter() - t0) * 1000.0
        # Calibrated 0.5 lands in the borderline zone with default thresholds —
        # downstream triage uses ``error=True`` (not is_borderline) to route to
        # REVIEW_NEEDED, so this is correct.
        is_borderline = (
            self._settings.borderline_low <= 0.5 <= self._settings.borderline_high
        )
        logger.warning(
            "classification_error",
            error=error_type,
            error_detail=detail,
            fallback="non_offensive_0.5_review_flag",
            latency_ms=latency_ms,
            adapter="ollama",
        )
        record_error(error_type)
        return ClassificationResult(
            label="non_offensive",
            confidence=0.5,
            is_offensive=False,
            model_version=self._model_version,
            latency_ms=latency_ms,
            is_borderline=is_borderline,
            raw_confidence=0.5,
            error=True,
        )
