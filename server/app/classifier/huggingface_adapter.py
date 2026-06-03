"""HuggingFaceClassifier — direct DictaBERT inference via ``transformers``.

Reference: docs/design/classifier/design.md §2.5 ("HuggingFaceClassifier"),
§3.4 (export path), §7.1 (latency target).

Two construction paths:

- If ``DICTABERT_MODEL_PATH`` exists on disk, load the fine-tuned
  classification checkpoint from there. ``model_version`` = ``"v1.1-dictabert"``.
- Otherwise, fall back to the HF base model (``dicta-il/dictabert``) with a
  RANDOMLY-INITIALISED 5-label classification head. ``model_version`` =
  ``"v1.1-dictabert-base-untrained"`` so the audit log captures this state.
  Confidence will be ~0.2 / class until the Meeting-5 fine-tune lands.

Inference runs on CPU (the server box has no dedicated inference GPU); the
forward pass is wrapped in ``torch.no_grad()`` and the heavy call is pushed
to a thread via ``asyncio.to_thread`` so it doesn't block the FastAPI loop.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, cast

from ..schemas import Category, ClassificationResult, HealthState
from .calibration import ConfidenceCalibrator
from .logging import bind_context
from .metrics import record_classification, record_error
from .settings import ClassifierSettings

# Hard input cap for chars; the tokenizer's 512 token cap is the real one.
_MAX_INPUT_CHARS = 4096

# Canonical 5-label order — matches docs/design/classifier/design.md §5.2.
# Index 0 must be "non_offensive" so that label_ids that the random head
# happens to emit for "all-zero" inputs land on the safe class.
_LABEL_ORDER: tuple[Category, ...] = (
    "non_offensive",
    "abusive",
    "hate",
    "violence",
    "pornographic",
)

_ID2LABEL: dict[int, str] = {i: lbl for i, lbl in enumerate(_LABEL_ORDER)}
_LABEL2ID: dict[str, int] = {lbl: i for i, lbl in enumerate(_LABEL_ORDER)}


class HuggingFaceClassifier:
    """Direct ``transformers``-based classifier using DictaBERT.

    Constructed once at server startup; thread-safe for concurrent ``classify()``
    calls because the underlying ``model.eval()`` forward pass is read-only
    and ``torch`` releases the GIL during the matmul. Concurrent calls share
    the same model weights.
    """

    def __init__(
        self,
        settings: ClassifierSettings,
        calibrator: ConfidenceCalibrator | None = None,
    ) -> None:
        # Import torch / transformers lazily so the rest of the package can be
        # imported (e.g. by Protocol-only consumers) on systems where ML deps
        # aren't installed.
        import torch  # noqa: F401 — imported for side-effects + later use
        from transformers import (  # type: ignore[import-untyped]
            AutoModelForSequenceClassification,
            AutoTokenizer,
        )

        self._settings = settings
        self._calibrator = calibrator or ConfidenceCalibrator(method="none")
        self._torch = torch

        ckpt_path = settings.dictabert_model_path
        if ckpt_path.exists() and ckpt_path.is_dir():
            self._source = "checkpoint"
            self._model_version = "v1.1-dictabert"
            load_from = str(ckpt_path)
        else:
            self._source = "hf-base-untrained"
            self._model_version = "v1.1-dictabert-base-untrained"
            load_from = settings.dictabert_hf_name

        # First call triggers download / first-use cache hydration.
        self._tokenizer = AutoTokenizer.from_pretrained(load_from)
        self._model = AutoModelForSequenceClassification.from_pretrained(
            load_from,
            num_labels=len(_LABEL_ORDER),
            id2label=_ID2LABEL,
            label2id=_LABEL2ID,
            ignore_mismatched_sizes=True,
        )
        self._model.eval()
        # Force CPU — server box is inference-only.
        self._device = torch.device("cpu")
        self._model.to(self._device)

    # ------------------------------------------------------------------
    # Protocol surface
    # ------------------------------------------------------------------
    @property
    def model_version(self) -> str:
        return self._model_version

    async def health(self) -> tuple[HealthState, str]:
        """Run a tiny forward pass to confirm the model is alive on CPU."""
        try:
            await asyncio.to_thread(self._forward_logits, "שלום")
        except Exception as exc:  # noqa: BLE001
            return HealthState.DOWN, (
                f"DictaBERT forward pass failed: {type(exc).__name__}: {exc}"
            )
        state = (
            HealthState.OK
            if self._source == "checkpoint"
            else HealthState.DEGRADED
        )
        detail = (
            f"DictaBERT loaded from {self._source}; model_version={self._model_version}"
        )
        return state, detail

    async def classify(self, text: str) -> ClassificationResult:
        """Tokenise + forward pass + softmax. Never raises on model failure."""
        logger = bind_context(model_version=self._model_version)
        t0 = time.perf_counter()

        if not isinstance(text, str) or not text.strip():
            return self._error_result(
                logger=logger,
                error_type="empty_text",
                detail="empty or non-string input",
                t0=t0,
            )

        text = self._maybe_truncate(text, logger=logger)

        try:
            # Push the (potentially) blocking PyTorch call to a worker thread.
            logits = await asyncio.to_thread(self._forward_logits, text)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - defensive
            return self._error_result(
                logger=logger,
                error_type="huggingface_inference_failed",
                detail=f"{type(exc).__name__}: {exc}",
                t0=t0,
            )

        # ---- Softmax → predicted class ------------------------------
        probs = self._softmax_1d(logits)
        pred_idx = int(probs.argmax())
        raw_conf = float(probs[pred_idx])
        label = cast(Category, _ID2LABEL.get(pred_idx, "non_offensive"))

        cal_conf = self._calibrator.transform(raw_conf)
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

        event = (
            "classification_borderline" if is_borderline else "classification_complete"
        )
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
            adapter="huggingface",
            source=self._source,
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
    def _forward_logits(self, text: str) -> Any:
        """Synchronous forward pass — call from a worker thread.

        Returns a 1-D tensor of length ``len(_LABEL_ORDER)``.
        """
        torch = self._torch
        inputs = self._tokenizer(
            text,
            truncation=True,
            max_length=512,
            return_tensors="pt",
        )
        inputs = {k: v.to(self._device) for k, v in inputs.items()}
        with torch.no_grad():
            outputs = self._model(**inputs)
        # ``logits`` shape: (1, num_labels) — squeeze to 1-D.
        return outputs.logits.squeeze(0).detach()

    def _softmax_1d(self, logits: Any) -> Any:
        torch = self._torch
        return torch.softmax(logits, dim=-1)

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
        latency_ms = (time.perf_counter() - t0) * 1000.0
        is_borderline = (
            self._settings.borderline_low <= 0.5 <= self._settings.borderline_high
        )
        logger.warning(
            "classification_error",
            error=error_type,
            error_detail=detail,
            fallback="non_offensive_0.5_review_flag",
            latency_ms=latency_ms,
            adapter="huggingface",
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
