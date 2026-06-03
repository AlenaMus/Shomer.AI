"""FastAPI composition root for Shomer.AI server.

This is the ONLY place concrete adapters are constructed. Every other module
depends on Protocols (``TextClassifier``, ``OcrBackend``, ``ContextReasoner``,
``AuditStore``) — swapping an adapter is a one-line change in ``lifespan()``
below, per docs/design/README.md §4 (composition-root pattern).

See docs/design/server/design.md for the full integration view.

Endpoints are backwards-compatible with the legacy v0.3 server: the request
and response shapes for ``/classify``, ``/classify-image``, ``/health`` and
``/model/info`` are unchanged. The ``?strategy=`` query param on
``/classify-image`` is accepted but ignored (Architecture B is OCR-only).
"""

from __future__ import annotations

import hashlib
import os
import time
import uuid
from contextlib import asynccontextmanager

import structlog
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware

# Module Protocols (the only cross-module imports allowed outside lifespan()).
from .audit_log import AuditStore
from .classifier import TextClassifier
from .context_agent import ContextReasoner
from .middleware import AuditLoggingMiddleware
from .ocr import OcrBackend
from .schemas import (
    ClassificationResult,
    ClassifyImageResponse,
    ClassifyRequest,
    ClassifyResponse,
    ContextDecision,
    HealthResponse,
    HealthState,
    ModelInfoResponse,
    OcrResult,
    TriageDecision,
)

load_dotenv()

log = structlog.get_logger("shomer.server")


# ---------------------------------------------------------------------------
# Composition root — concrete adapter selection. Each helper imports its
# concrete classes lazily so module load doesn't fail when a heavy dep
# (transformers, openai, anthropic) is missing.
# ---------------------------------------------------------------------------


def _build_classifier() -> TextClassifier:
    """Pick a classifier adapter based on ``CLASSIFIER_MODEL_VERSION``."""
    from .classifier.huggingface_adapter import HuggingFaceClassifier
    from .classifier.ollama_adapter import OllamaDictaBertClassifier
    from .classifier.settings import ClassifierSettings
    from .ollama_client import OllamaClient

    settings = ClassifierSettings()

    if settings.model_version == "v1.1-dictabert":
        log.info(
            "classifier_select",
            adapter="HuggingFaceClassifier",
            model_path=str(settings.dictabert_model_path),
            hf_name=settings.dictabert_hf_name,
            version=settings.model_version,
        )
        return HuggingFaceClassifier(settings)

    log.info(
        "classifier_select",
        adapter="OllamaDictaBertClassifier",
        model=settings.ollama_model,
        version=settings.model_version,
    )
    ollama = OllamaClient(
        settings.ollama_url,
        settings.ollama_model,
        settings.classifier_timeout_s,
    )
    return OllamaDictaBertClassifier(ollama, settings)


def _build_ocr() -> OcrBackend:
    """Pick an OCR adapter based on ``OCR_BACKEND``."""
    from .ocr.settings import OcrSettings
    from .ocr.stub_adapter import StubOcrBackend
    from .ocr.tesseract_adapter import TesseractOcrBackend

    settings = OcrSettings()
    if settings.ocr_backend == "stub":
        log.info("ocr_select", adapter="StubOcrBackend")
        return StubOcrBackend()

    log.info(
        "ocr_select",
        adapter="TesseractOcrBackend",
        lang=settings.ocr_lang,
        cmd=settings.tesseract_cmd,
    )
    return TesseractOcrBackend(settings)


def _build_llm_clients(settings):
    """Pick LLM client adapters based on which API keys are configured.

    Returns ``(primary, fallback)``. Falls back to MockLlmClient when keys are
    missing — useful for local dev. Logs WARNING when this happens so it's
    obvious from the boot log.
    """
    from .context_agent.clients.mock_client import MockLlmClient

    has_openai = bool(
        settings.openai_api_key
        and settings.openai_api_key.get_secret_value().strip()
    )
    has_anthropic = bool(
        settings.anthropic_api_key
        and settings.anthropic_api_key.get_secret_value().strip()
    )

    if has_openai and has_anthropic:
        from .context_agent.clients.anthropic_client import AnthropicClient
        from .context_agent.clients.openai_client import OpenAiClient

        return (OpenAiClient(settings), AnthropicClient(settings))

    if has_openai:
        from .context_agent.clients.openai_client import OpenAiClient

        log.warning("anthropic_key_missing", note="using Mock as fallback LLM")
        return (OpenAiClient(settings), MockLlmClient())

    if has_anthropic:
        from .context_agent.clients.anthropic_client import AnthropicClient

        log.warning("openai_key_missing", note="using Anthropic as primary")
        return (AnthropicClient(settings), MockLlmClient())

    log.warning(
        "no_llm_keys_configured",
        note="using MockLlmClient only — set OPENAI_API_KEY and/or "
        "ANTHROPIC_API_KEY in server/.env to enable real LLMs",
    )
    return (MockLlmClient(), MockLlmClient())


def _build_context_agent(audit: AuditStore) -> ContextReasoner | None:
    """Build the Context Agent if ``CONTEXT_AGENT_ENABLED=true``."""
    from .context_agent.settings import ContextAgentSettings

    settings = ContextAgentSettings()
    if not settings.context_agent_enabled:
        log.info("context_agent_disabled")
        return None

    from .context_agent.agent import LlmContextAgent
    from .context_agent.llm_router import LlmRouter
    from .context_agent.token_manager import InMemoryTokenManager
    from .context_agent.tools.check_age import CheckAgeAppropriatenessTool
    from .context_agent.tools.lookup_slang import LookupSlangTool
    from .context_agent.tools.read_history import ReadHistoryTool

    primary, fallback = _build_llm_clients(settings)
    token_manager = InMemoryTokenManager(settings)
    router = LlmRouter(primary, fallback, token_manager, settings)

    tools = [
        ReadHistoryTool(
            audit_store=audit,
            default_turns=settings.context_agent_history_turns,
        ),
        LookupSlangTool(),
        CheckAgeAppropriatenessTool(),
    ]

    log.info(
        "context_agent_select",
        primary=primary.model_name,
        fallback=fallback.model_name,
    )
    return LlmContextAgent(router, tools, settings)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Construct all adapters once; store via Protocol-typed references."""
    # AuditStore — in-memory stop-gap until SqliteAuditStore (AUDIT-SCHEMA-01).
    from .audit_log.in_memory_adapter import InMemoryAuditStore

    app.state.audit_store: AuditStore = InMemoryAuditStore()
    app.state.classifier: TextClassifier = _build_classifier()
    app.state.ocr: OcrBackend = _build_ocr()
    app.state.context_agent: ContextReasoner | None = _build_context_agent(
        app.state.audit_store
    )

    log.info(
        "server_ready",
        classifier=app.state.classifier.model_version,
        ocr=app.state.ocr.backend_name,
        context_agent_enabled=app.state.context_agent is not None,
        version="0.5.0-modular",
    )

    yield

    log.info("server_shutdown")


app = FastAPI(
    title="Shomer.AI Server",
    version="0.5.0-modular",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
app.add_middleware(AuditLoggingMiddleware)


# ---------------------------------------------------------------------------
# Triage — the deterministic decision gate per docs/design/triage/design.md §3
# (the G-03 fix: normalize confidence to ``prob_offensive`` before threshold
# routing, so ``is_offensive=False, confidence=0.92`` correctly routes to
# SILENT not ALERT_DIRECT).
# ---------------------------------------------------------------------------


def _triage(
    result: ClassificationResult,
    context_agent_enabled: bool,
) -> TriageDecision:
    if result.error:
        return TriageDecision.REVIEW_NEEDED

    # Step A — normalize to P(offensive).
    prob_offensive = (
        result.confidence if result.is_offensive else 1.0 - result.confidence
    )

    # Step B — threshold routing.
    borderline_low = float(os.environ.get("BORDERLINE_LOW", "0.3"))
    borderline_high = float(os.environ.get("BORDERLINE_HIGH", "0.7"))
    baseline_threshold = float(os.environ.get("TRIAGE_BASELINE_THRESHOLD", "0.5"))

    if prob_offensive <= borderline_low:
        return TriageDecision.SILENT
    if prob_offensive >= borderline_high:
        return TriageDecision.ALERT_DIRECT

    if not context_agent_enabled:
        return (
            TriageDecision.ALERT_DIRECT
            if prob_offensive >= baseline_threshold
            else TriageDecision.SILENT
        )

    return TriageDecision.ESCALATE_TO_CA


# ---------------------------------------------------------------------------
# Request-state audit dict — set by AuditLoggingMiddleware; defensive init
# for paths that bypass middleware (tests, error handlers).
# ---------------------------------------------------------------------------


def _ensure_request_audit(request: Request) -> None:
    if not hasattr(request.state, "audit") or request.state.audit is None:
        request.state.audit = {}


def _trace_id(request: Request) -> str:
    return request.headers.get("X-Trace-Id") or str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Aggregated health rollup across modules.

    Backwards-compatible response: ``ollama_reachable`` is True iff the
    classifier's underlying transport is healthy (Ollama for the v1.0
    stand-in adapter; the HuggingFace adapter reports DEGRADED when no
    fine-tuned checkpoint is loaded — still True for the field).
    """
    classifier_state, classifier_detail = await app.state.classifier.health()
    ocr_state, _ = await app.state.ocr.health()
    audit_state, _ = await app.state.audit_store.health()

    overall_ok = HealthState.OK in {classifier_state}  # classifier is the gate
    return HealthResponse(
        status="ok" if classifier_state == HealthState.OK else "degraded",
        ollama_reachable=classifier_state == HealthState.OK,
        model=app.state.classifier.model_version,
    )


@app.get("/model/info", response_model=ModelInfoResponse)
async def model_info() -> ModelInfoResponse:
    return ModelInfoResponse(
        model=app.state.classifier.model_version,
        labels=["abusive", "hate", "violence", "pornographic", "non_offensive"],
    )


@app.post("/classify", response_model=ClassifyResponse)
async def classify(req: ClassifyRequest, request: Request) -> ClassifyResponse:
    """Classify a Hebrew text through the modular pipeline.

    Flow: TextClassifier → Triage → (optional) ContextReasoner → AuditStore.
    NEVER raises — the classifier adapters' contract is to return
    ``error=True`` instead of raising, and the pipeline does the rest.
    """
    _ensure_request_audit(request)
    request.state.audit["text"] = req.text

    started = time.perf_counter()
    trace_id = _trace_id(request)

    # 1. Frontline classifier
    result: ClassificationResult = await app.state.classifier.classify(req.text)

    # 2. Triage
    context_agent_enabled = app.state.context_agent is not None
    triage_decision = _triage(result, context_agent_enabled)
    frontline_only_decision = triage_decision  # snapshot BEFORE CA runs

    # 3. Context Agent (only on borderline)
    if (
        triage_decision == TriageDecision.ESCALATE_TO_CA
        and context_agent_enabled
    ):
        ctx_decision: ContextDecision = await app.state.context_agent.evaluate(
            req.text, result, child_id=None
        )
        if ctx_decision.review_flag:
            triage_decision = TriageDecision.REVIEW_NEEDED
        elif ctx_decision.is_real_threat:
            triage_decision = TriageDecision.ALERT_DIRECT
        else:
            triage_decision = TriageDecision.SILENT
        request.state.audit["context_agent"] = {
            "model_used": ctx_decision.model_used,
            "is_real_threat": ctx_decision.is_real_threat,
            "tokens_total": ctx_decision.tokens_input + ctx_decision.tokens_output,
            "cost_usd": ctx_decision.cost_usd,
        }

    # 4. Record (in-memory until SqliteAuditStore lands).
    await app.state.audit_store.record_classification(
        trace_id=trace_id,
        request_text=req.text,
        classifier_result=result,
        triage_decision=triage_decision,
        context_agent_enabled=context_agent_enabled,
        frontline_only_decision=str(frontline_only_decision.value),
    )

    latency_ms = int((time.perf_counter() - started) * 1000)
    request.state.audit["triage_decision"] = triage_decision.value
    request.state.audit["classifier_model"] = result.model_version

    return ClassifyResponse(
        is_offensive=result.is_offensive,
        category=result.label,
        confidence=result.confidence,
        model=result.model_version,
        latency_ms=latency_ms,
    )


@app.post("/classify-image", response_model=ClassifyImageResponse)
async def classify_image(
    request: Request,
    image: UploadFile = File(...),
    strategy: str | None = None,  # accepted for back-compat; Architecture B uses OCR only.
) -> ClassifyImageResponse:
    """Classify an uploaded image: OCR extraction → text classifier pipeline.

    The ``?strategy=`` query param is silently accepted but ignored — the
    locked Architecture B path is OCR-only (no vision LLM, per PRD §11.1).
    """
    _ensure_request_audit(request)
    started = time.perf_counter()

    image_bytes = await image.read()
    request.state.audit["image"] = {
        "filename": image.filename,
        "content_type": image.content_type,
        "bytes": len(image_bytes),
    }
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Empty image upload")

    trace_id = _trace_id(request)

    # 1. OCR extraction (NEVER raises per OcrBackend contract).
    ocr_result: OcrResult = await app.state.ocr.process(
        image_bytes,
        mime_type=image.content_type or "image/jpeg",
    )

    # 2. If unreadable, return early — safe default.
    if ocr_result.image_unreadable or not ocr_result.extracted_text.strip():
        latency_ms = int((time.perf_counter() - started) * 1000)
        await app.state.audit_store.record_classification(
            trace_id=trace_id,
            request_text="",
            classifier_result=ClassificationResult(
                label="non_offensive",
                confidence=0.5,
                is_offensive=False,
                model_version="ocr_unreadable",
                latency_ms=0.0,
                is_borderline=True,
                raw_confidence=0.5,
                error=True,
            ),
            triage_decision=TriageDecision.REVIEW_NEEDED,
            context_agent_enabled=app.state.context_agent is not None,
            input_type="image",
            ocr_extracted_text=ocr_result.extracted_text,
            image_hash=hashlib.sha256(image_bytes).hexdigest()[:16],
        )
        return ClassifyImageResponse(
            is_offensive=False,
            category="non_offensive",
            confidence=0.5,
            model=app.state.classifier.model_version,
            latency_ms=latency_ms,
            extracted_text=ocr_result.extracted_text,
            backend=ocr_result.backend,
            strategy="ocr_only",
        )

    # 3. Classify the extracted text through the same pipeline as /classify.
    result: ClassificationResult = await app.state.classifier.classify(
        ocr_result.extracted_text
    )

    context_agent_enabled = app.state.context_agent is not None
    triage_decision = _triage(result, context_agent_enabled)
    frontline_only_decision = triage_decision

    if (
        triage_decision == TriageDecision.ESCALATE_TO_CA
        and context_agent_enabled
    ):
        ctx_decision: ContextDecision = await app.state.context_agent.evaluate(
            ocr_result.extracted_text, result, child_id=None
        )
        if ctx_decision.review_flag:
            triage_decision = TriageDecision.REVIEW_NEEDED
        elif ctx_decision.is_real_threat:
            triage_decision = TriageDecision.ALERT_DIRECT
        else:
            triage_decision = TriageDecision.SILENT

    await app.state.audit_store.record_classification(
        trace_id=trace_id,
        request_text=ocr_result.extracted_text,
        classifier_result=result,
        triage_decision=triage_decision,
        context_agent_enabled=context_agent_enabled,
        frontline_only_decision=str(frontline_only_decision.value),
        input_type="image",
        ocr_extracted_text=ocr_result.extracted_text,
        image_hash=hashlib.sha256(image_bytes).hexdigest()[:16],
    )

    latency_ms = int((time.perf_counter() - started) * 1000)
    return ClassifyImageResponse(
        is_offensive=result.is_offensive,
        category=result.label,
        confidence=result.confidence,
        model=result.model_version,
        latency_ms=latency_ms,
        extracted_text=ocr_result.extracted_text,
        backend=ocr_result.backend,
        strategy="ocr_only",
    )
