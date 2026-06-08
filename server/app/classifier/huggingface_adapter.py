"""HuggingFaceClassifier — direct DictaBERT inference via ``transformers``.

Reference: docs/design/classifier/design.md §2.5 ("HuggingFaceClassifier"),
§3.4 (export path), §7.1 (latency target).

Two construction paths:

- If ``DICTABERT_MODEL_PATH`` exists on disk, load the fine-tuned checkpoint
  using the custom ``DictaBertWithMlpHead`` class from
  ``classifier.dictabert_model``.  The checkpoint has ``model_type =
  "dictabert_mlp"`` in its config.json — attempting to load it via
  ``AutoModelForSequenceClassification`` raises an unknown-model-type error.
  ``model_version`` = ``"v1.1-dictabert"``.

- Otherwise, fall back to the HF base model (``dicta-il/dictabert``) with a
  RANDOMLY-INITIALISED 5-label classification head loaded via
  ``AutoModelForSequenceClassification``.  ``model_version`` =
  ``"v1.1-dictabert-base-untrained"`` so the audit log captures this state.
  Confidence will be ~0.2 / class until the fine-tune lands.

Inference runs on CPU (the server box has no dedicated inference GPU); the
forward pass is wrapped in ``torch.no_grad()`` and the heavy call is pushed
to a thread via ``asyncio.to_thread`` so it doesn't block the FastAPI loop.

Calibration note (D10 checkpoint — training/outputs/dictabert-offensive/checkpoint-best/):
  The D10 checkpoint was trained and evaluated with isotonic calibration
  (ECE_before=0.248, ECE_after=0.033) but the fitted calibrators were NOT
  saved alongside the checkpoint — they were reporting-only.  The adapter
  therefore serves raw softmax probabilities, which are known to be
  over-confident (ECE ~0.25 without correction).

  Practical impact on triage routing (G-03 rule):
  - Raw softmax can push predicted-class probabilities toward 0.95–0.99 for
    high-confidence inputs.
  - The triage engine converts them correctly via
    ``prob_offensive = conf if is_offensive else 1 - conf`` before thresholding.
  - The TriageSettings thresholds were set conservatively (violence always
    escalates to CA; alert_direct fires at prob_offensive >= 0.65 — see
    TriageSettings.alert_direct_threshold) so a few extra high-confidence
    predictions do not cause false-positive alerts in practice.

  To apply post-hoc calibration, fit an sklearn IsotonicRegression or
  temperature scalar on the validation set, pickle it to
  ``CALIBRATION_PKL_PATH`` (default: server/models/calibrator.pkl), and set
  ``CALIBRATION_METHOD=isotonic`` (or ``temperature``) in server/.env.
  The ConfidenceCalibrator wraps this transparently with no code changes.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, cast

from ..schemas import Category, ClassificationResult, HealthState
from .calibration import ConfidenceCalibrator
from .logging import bind_context
from .metrics import record_classification, record_error
from .settings import ClassifierSettings

# Suppress noisy transformers 5.x startup messages emitted through Python
# logging (not transformers' own print-based logger):
# - "model of type dictabert_mlp to instantiate model of type ''" — benign; we
#   load via the concrete class, not Auto classes.
# - "use_return_dict is deprecated" — config field renamed in transformers 5;
#   the checkpoint was saved by transformers 5 so this is training-time noise.
# The "[transformers] The following layers were not sharded" message is emitted
# via a direct print() in transformers 5.x and cannot be suppressed through
# Python logging — it is cosmetic startup noise only, not an error.
logging.getLogger("transformers.modeling_utils").setLevel(logging.ERROR)
logging.getLogger("transformers.configuration_utils").setLevel(logging.ERROR)
logging.getLogger("transformers.modeling_utils_new").setLevel(logging.ERROR)

# Hard input cap for chars; the tokenizer's 512 token cap is the real one.
_MAX_INPUT_CHARS = 4096

# Canonical 5-label order — matches docs/design/classifier/design.md §5.2 and
# training/outputs/dictabert-offensive/checkpoint-best/config.json id2label.
# Used only for the base-untrained fallback path; the checkpoint path reads
# id2label from the loaded model's config (authoritative per task spec).
_LABEL_ORDER: tuple[Category, ...] = (
    "non_offensive",
    "abusive",
    "hate",
    "violence",
    "pornographic",
)

_ID2LABEL_FALLBACK: dict[int, str] = {i: lbl for i, lbl in enumerate(_LABEL_ORDER)}
_LABEL2ID_FALLBACK: dict[str, int] = {lbl: i for i, lbl in enumerate(_LABEL_ORDER)}


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

        if self._source == "checkpoint":
            # The fine-tuned checkpoint has model_type="dictabert_mlp" and was
            # saved with the custom DictaBertWithMlpHead class.
            # AutoModelForSequenceClassification cannot resolve this model_type —
            # we must call from_pretrained on the concrete class directly.
            # No AutoClass registration is required when loading this way.
            from .dictabert_model import DictaBertWithMlpHead

            self._model = DictaBertWithMlpHead.from_pretrained(load_from)
            # Read id2label from the checkpoint's config — this is authoritative.
            # Keys are int (id) → str (label).  The checkpoint's config.json
            # stores them as string keys so we normalise to int here.
            self._id2label: dict[int, str] = {
                int(k): v
                for k, v in self._model.config.id2label.items()
            }
        else:
            # Base-only path: randomly-initialized head, standard AutoModel load.
            self._model = AutoModelForSequenceClassification.from_pretrained(
                load_from,
                num_labels=len(_LABEL_ORDER),
                id2label=_ID2LABEL_FALLBACK,
                label2id=_LABEL2ID_FALLBACK,
                ignore_mismatched_sizes=True,
            )
            self._id2label = _ID2LABEL_FALLBACK

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
        # Use the instance-level id2label that was read from the checkpoint
        # config at construction time (authoritative source of label order).
        label = cast(Category, self._id2label.get(pred_idx, "non_offensive"))

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

        ``max_length`` must match the value used during training (96 for the
        D10 checkpoint).  Using a larger value (e.g. 512) is functionally safe
        because the position embeddings support up to 512 tokens, but it
        produces different length distributions than training and wastes ~5×
        compute for Hebrew chat inputs that are almost always under 50 tokens.
        """
        torch = self._torch
        inputs = self._tokenizer(
            text,
            truncation=True,
            max_length=self._settings.dictabert_max_length,
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
