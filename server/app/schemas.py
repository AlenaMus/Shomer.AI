from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

Category = Literal["abusive", "hate", "violence", "pornographic", "non_offensive"]
Severity = Literal["low", "medium", "high", "critical"]
AlertSource = Literal["frontline_direct", "context_agent", "fallback_review"]


class ClassifyRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000, description="Hebrew text to classify")
    child_id: str | None = Field(
        None,
        max_length=128,
        description=(
            "Optional opaque child identifier (no PII). When present, the "
            "message is persisted to the conversations table keyed by this id "
            "so the Context Agent's read_history tool returns real multi-turn "
            "context. Does NOT affect the frontline classifier or its text input."
        ),
    )
    message_id: str | None = Field(
        None,
        max_length=128,
        description="Optional client-supplied message id; used for alert idempotency.",
    )


class ClassifyResponse(BaseModel):
    is_offensive: bool
    category: Category
    confidence: float = Field(..., ge=0.0, le=1.0)
    model: str
    latency_ms: int


class ClassifyImageResponse(BaseModel):
    """Response from ``POST /classify-image``.

    Looser than :class:`ClassifyResponse`: ``category`` is a free-form string
    because Phase 1 stub uses ``"stub"`` and Phase 2 backends may emit
    categories outside the strict ``Category`` enum (e.g. ``"no_text"``).
    ``extracted_text``, ``backend``, ``strategy`` are diagnostic fields that
    let the client and the architecture study see what actually happened.
    """

    is_offensive: bool
    category: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    model: str
    latency_ms: int
    extracted_text: str = ""
    backend: str
    strategy: str


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    ollama_reachable: bool
    model: str


class ModelInfoResponse(BaseModel):
    model: str
    base: str | None = None
    labels: list[Category] = ["abusive", "hate", "violence", "pornographic", "non_offensive"]


# ---------------------------------------------------------------------------
# Internal pipeline value types (frozen dataclasses).
#
# These types flow BETWEEN modules. Per docs/design/README.md, modules import
# these value types directly from schemas — but they do NOT import concrete
# adapter classes from other modules. Adapters are constructed only in
# server/app/main.py lifespan(), via Protocols.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ClassificationResult:
    """Output of TextClassifier.classify() — classifier LLD §2.2."""

    label: Category
    confidence: float            # CALIBRATED P(predicted_class), 0.0–1.0
    is_offensive: bool           # True iff label != "non_offensive"
    model_version: str           # e.g. "v1.0-standin" / "v1.1-dictabert"
    latency_ms: float
    is_borderline: bool          # True when confidence ∈ [borderline_low, borderline_high]
    raw_confidence: float        # pre-calibration softmax, for diagnostics
    error: bool = False          # True if model crashed → triage routes to REVIEW_NEEDED


@dataclass(frozen=True)
class OcrResult:
    """Output of OcrBackend.process() — ocr LLD §5."""

    extracted_text: str
    confidence: float                  # mean per-word OCR confidence, 0.0–1.0
    lang_detected: tuple[str, ...]     # e.g. ("heb",) or ("heb", "eng")
    bbox_count: int
    image_unreadable: bool = False
    backend: str = "tesseract"


class TriageDecision(str, Enum):
    """Output of TriageEngine.decide() — triage LLD §2."""

    SILENT = "silent"                  # confidently non-offensive
    ALERT_DIRECT = "alert_direct"      # confidently offensive
    ESCALATE_TO_CA = "escalate_to_ca"  # borderline → Context Agent
    REVIEW_NEEDED = "review_needed"    # classifier error / invalid input


@dataclass(frozen=True)
class ContextDecision:
    """Output of ContextReasoner.evaluate() — context_agent LLD §2."""

    is_real_threat: bool
    severity: str                  # "low" | "medium" | "high"
    explanation: str               # one-sentence Hebrew rationale for the parent
    review_flag: bool = False      # True iff both LLMs unreachable → human review
    tokens_input: int = 0
    tokens_output: int = 0
    cost_usd: float = 0.0
    model_used: str | None = None  # "gpt-4o-mini" | "haiku-4.5" | "mock" | None
    reasoning_trace: str = ""      # full chain-of-thought, for audit_log
    tools_called: tuple[str, ...] = ()
    latency_ms: float = 0.0


class HealthState(str, Enum):
    """Per-module health.  /health endpoint aggregates these via ModuleHealth."""

    OK = "ok"
    DEGRADED = "degraded"
    DOWN = "down"


@dataclass(frozen=True)
class ModuleHealth:
    """Health report for one module — used by the server /health rollup."""

    module: str
    state: HealthState
    detail: str = ""               # one-line free-form (e.g. "Ollama unreachable")


# ---------------------------------------------------------------------------
# Alerts module — NotificationChannel request/result (alerts LLD §2).
#
# ``parent_fcm_token`` and ``child_name`` are optional with empty defaults so
# the default ``LogNotifier`` path works without Firebase setup; the
# (backlog) ``FcmNotifier`` requires both to be populated.
# ---------------------------------------------------------------------------


class AlertRequest(BaseModel):
    child_id: str = Field(..., description="Opaque child identifier (no PII)")
    message_id: str = Field(..., description="Unique id of the classified message")
    label: Category
    severity: Severity
    explanation: str = Field(..., max_length=280, description="1-sentence parent explanation")
    quote: str = Field("", max_length=200, description="Truncated message excerpt (no full text)")
    source: AlertSource
    trace_id: str = Field(..., description="Propagated for end-to-end correlation")
    parent_fcm_token: str = Field("", description="FCM token (required only for FcmNotifier)")
    child_name: str = Field("", max_length=50, description="Display name only — no other PII")


class AlertResult(BaseModel):
    alert_id: str                          # idempotency key: sha256(child:msg:label)[:16]
    sent: bool
    queued: bool = False                   # True when channel was down; queued for retry
    rate_limited: bool = False             # True when suppressed by the per-child rate limiter
    channel: str = "log"                   # "log" | "fcm" | "stub" | ...
    fcm_message_id: str | None = None      # delivery-assigned id on success (None for LogNotifier)
    latency_ms: int = 0
    error: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now())
