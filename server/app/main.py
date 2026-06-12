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

import asyncio
import hashlib
import sys
import time
import uuid
from contextlib import asynccontextmanager

# Force UTF-8 stdio so structlog's console renderer never raises
# UnicodeEncodeError on Hebrew log fields (e.g. an alert's quote/explanation).
# Without this, a Windows cp1252 console aborts the alert-send log line — which
# in turn drops the alert's audit record. Belt-and-suspenders for PYTHONUTF8.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001 — never block startup on this
            pass

import structlog
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware

# Module Protocols (the only cross-module imports allowed outside lifespan()).
from .alerts import NotificationChannel, derive_severity
from .audit_log import AuditStore
from .classifier import TextClassifier
from .context_agent import ContextReasoner
from .dedup import DedupStore
from .digest import DigestScheduler, DigestStore, register_digest
from .flagged import FlaggedEventStore, register_parent_review
from .gateway import GatekeeperSettings, register_gateway
from .identity import IdentityStore, register_identity
from .middleware import AuditLoggingMiddleware
from .monitor import MonitorIngest, register_monitor
from .ocr import OcrBackend
from .triage import TriageEngine
from .schemas import (
    AlertRequest,
    AlertResult,
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

    def _key(secret) -> str:
        return secret.get_secret_value().strip() if secret else ""

    gemini_key = _key(getattr(settings, "gemini_api_key", None))
    openai_key = _key(settings.openai_api_key)
    anthropic_key = _key(settings.anthropic_api_key)

    # Candidate adapters in priority order. The FIRST configured key becomes the
    # primary, the SECOND the fallback; Mock fills any empty slot. Each client
    # takes the raw API-key STRING (not the settings object).
    candidates: list[tuple[str, object]] = []
    if gemini_key:
        from .context_agent.clients.gemini_client import GeminiClient

        candidates.append(("gemini", GeminiClient(gemini_key, settings.gemini_model)))
    if openai_key:
        from .context_agent.clients.openai_client import OpenAiClient

        candidates.append(("openai", OpenAiClient(openai_key)))
    if anthropic_key:
        from .context_agent.clients.anthropic_client import AnthropicClient

        candidates.append(("anthropic", AnthropicClient(anthropic_key)))

    if not candidates:
        log.warning(
            "no_llm_keys_configured",
            note="using MockLlmClient only — set GEMINI_API_KEY, OPENAI_API_KEY "
            "and/or ANTHROPIC_API_KEY in server/.env to enable real LLMs",
        )
        return (MockLlmClient(), MockLlmClient())

    primary = candidates[0][1]
    fallback = candidates[1][1] if len(candidates) > 1 else MockLlmClient()
    log.info(
        "llm_clients_selected",
        primary=candidates[0][0],
        fallback=(candidates[1][0] if len(candidates) > 1 else "mock"),
    )
    return (primary, fallback)


def _build_context_agent(audit: AuditStore) -> ContextReasoner | None:
    """Build the Context Agent if ``CONTEXT_AGENT_ENABLED=true``.

    ``LlmContextAgent`` constructs its own ``LlmRouter`` and tools internally
    (see context_agent/agent.py __init__). The composition root only selects
    the LLM client adapters and the token-budget guard, then hands them in
    along with the ``AuditStore`` Protocol.
    """
    from .context_agent.settings import ContextAgentSettings

    settings = ContextAgentSettings()
    if not settings.context_agent_enabled:
        log.info("context_agent_disabled")
        return None

    from .context_agent.agent import LlmContextAgent
    from .context_agent.token_manager import InMemoryTokenManager

    primary, fallback = _build_llm_clients(settings)
    token_manager = InMemoryTokenManager(
        token_prices_path=settings.token_prices_path,
        daily_token_budget=settings.context_agent_daily_token_budget,
        daily_usd_budget=settings.context_agent_daily_usd_budget,
    )

    log.info(
        "context_agent_select",
        primary=primary.model_name,
        fallback=fallback.model_name,
    )
    return LlmContextAgent(
        primary=primary,
        fallback=fallback,
        budget=token_manager,
        audit_store=audit,
        slang_lexicon_path=settings.slang_lexicon_path,
        timeout_s=settings.context_agent_timeout_s,
        max_history_turns=settings.context_agent_max_history_turns,
    )


async def _build_identity() -> "IdentityStore":
    """Build and initialize an IdentityStore adapter.

    Adapter selection is driven by ``IDENTITY_BACKEND`` env var:
      - "sqlite" (default) → SqliteIdentityStore (persistent, production)
      - "memory"           → InMemoryIdentityStore (tests, no I/O)
    """
    from .identity import IdentitySettings, InMemoryIdentityStore, SqliteIdentityStore

    settings = IdentitySettings()
    if settings.backend == "memory":
        store = InMemoryIdentityStore(
            pairing_code_ttl_s=settings.pairing_code_ttl_s,
        )
        log.info("identity_select", adapter="InMemoryIdentityStore")
    else:
        store = SqliteIdentityStore(
            db_path=settings.db_path,
            busy_timeout_ms=settings.busy_timeout_ms,
            device_token_ttl_days=settings.device_token_ttl_days,
            pairing_code_ttl_s=settings.pairing_code_ttl_s,
        )
        await store.initialize()
        log.info(
            "identity_select",
            adapter="SqliteIdentityStore",
            db=settings.db_path,
        )
    return store


async def _build_digest(
    flagged_store: "FlaggedEventStore",
    notifier: "NotificationChannel",
    identity: "IdentityStore",
) -> "tuple[DigestScheduler, DigestStore]":
    """Build DigestScheduler + DigestStore from env.

    Adapter selection driven by ``DIGEST_BACKEND``:
      - "asyncio" → AsyncioCronDigestScheduler (in-process cron, production)
      - "manual"  → ManualDigestRunner (on-demand, tests + external cron)

    Concrete adapters are imported lazily.  The composition root wires all
    collaborator callbacks here so ManualDigestRunner remains import-clean of
    identity/flagged concretes.
    """
    from .digest import (
        AsyncioCronDigestScheduler,
        DigestSettings,
        InMemoryDigestStore,
        ManualDigestRunner,
        SqliteDigestStore,
    )

    settings = DigestSettings()

    if not settings.enabled:
        log.info("digest_disabled")
        # Return stub objects that satisfy the Protocol shape for health checks.
        from .digest import InMemoryDigestStore

        return None, InMemoryDigestStore()

    # --- DigestStore ---
    digest_store: DigestStore
    if settings.backend == "asyncio":
        db_store = SqliteDigestStore(
            db_path=settings.db_path,
            busy_timeout_ms=settings.busy_timeout_ms,
        )
        await db_store.initialize()
        digest_store = db_store
        log.info("digest_store_select", adapter="SqliteDigestStore", db=settings.db_path)
    else:
        digest_store = InMemoryDigestStore()
        log.info("digest_store_select", adapter="InMemoryDigestStore")

    # --- Callbacks (injected so ManualDigestRunner stays import-clean) ---
    async def _parent_for_child(child_id: str) -> str | None:
        return await identity.parent_for_child(child_id)

    async def _fcm_token_for_parent(parent_id: str) -> str | None:
        return await identity.fcm_token_for_parent(parent_id)

    async def _active_child_ids(since: float) -> list[str]:
        return await flagged_store.child_ids_with_events_since(since)

    runner = ManualDigestRunner(
        flagged=flagged_store,
        digest_store=digest_store,
        channel=notifier,
        parent_for_child_fn=_parent_for_child,
        fcm_token_for_parent_fn=_fcm_token_for_parent,
        active_child_ids_fn=_active_child_ids,
        max_entries=settings.max_entries,
    )

    scheduler: DigestScheduler
    if settings.backend == "asyncio":
        scheduler = AsyncioCronDigestScheduler(runner=runner, hour=settings.hour)
        log.info("digest_scheduler_select", adapter="AsyncioCronDigestScheduler", hour=settings.hour)
    else:
        scheduler = runner
        log.info("digest_scheduler_select", adapter="ManualDigestRunner")

    return scheduler, digest_store


async def _build_monitor(app: FastAPI):
    """Build DedupStore, FlaggedEventStore, and MonitorIngest.

    Adapter selection is driven by ``DEDUP_BACKEND`` and ``FLAGGED_BACKEND``
    env vars, mirroring the ``_build_ocr`` pattern.  The SqliteFlaggedEventStore
    is initialized here (async) when selected.

    Returns (dedup, flagged, monitor_ingest) — all stored on app.state.
    """
    from .dedup import DedupSettings, InMemoryTtlDedupStore, NullDedupStore
    from .flagged import (
        FlaggedSettings,
        InMemoryFlaggedEventStore,
        SqliteFlaggedEventStore,
    )
    from .monitor import MonitorIngest

    dedup_settings = DedupSettings()
    if dedup_settings.backend == "null":
        dedup = NullDedupStore()
        log.info("dedup_select", adapter="NullDedupStore")
    else:
        dedup = InMemoryTtlDedupStore(max_per_child=dedup_settings.max_per_child)
        log.info(
            "dedup_select",
            adapter="InMemoryTtlDedupStore",
            max_per_child=dedup_settings.max_per_child,
            ttl_s=dedup_settings.ttl_s,
        )

    flagged_settings = FlaggedSettings()
    if flagged_settings.backend == "sqlite":
        flagged_store = SqliteFlaggedEventStore(
            db_path=flagged_settings.db_path,
            busy_timeout_ms=flagged_settings.busy_timeout_ms,
        )
        await flagged_store.initialize()
        log.info("flagged_select", adapter="SqliteFlaggedEventStore", db=flagged_settings.db_path)
    else:
        flagged_store = InMemoryFlaggedEventStore()
        log.info("flagged_select", adapter="InMemoryFlaggedEventStore")

    monitor = MonitorIngest(
        pipeline_fn=_run_pipeline,
        dedup=dedup,
        flagged=flagged_store,
        derive_severity=derive_severity,
        dedup_ttl_s=dedup_settings.ttl_s,
        # on_critical_flag is wired by lifespan() after digest scheduler is built.
        on_critical_flag=None,
    )
    return dedup, flagged_store, monitor


def _alert_status(res: AlertResult) -> str:
    """Map an ``AlertResult`` to the ``alerts.fcm_status`` enum string."""
    if res.sent:
        return "sent"
    if res.rate_limited:
        return "rate_limited"
    if res.queued:
        return "queued"
    return "failed"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Construct all adapters once; store via Protocol-typed references.

    This is the single composition root. Concrete adapters are built here and
    only here; every other line of code depends on Protocols
    (``TextClassifier``, ``OcrBackend``, ``TriageEngine``, ``ContextReasoner``,
    ``NotificationChannel``, ``AuditStore``).
    """
    # Concrete adapters — lazily imported so module load stays light.
    from .alerts import (
        AlertSettings,
        FcmNotifier,
        InMemoryAlertRateLimiter,
        LocalRetryQueue,
        LogNotifier,
        NtfyNotifier,
        StubNotifier,
    )
    from .audit_log import AuditSettings, RetentionSweeper, SqliteAuditStore
    from .triage import ThresholdTriageEngine, TriageSettings

    # --- Audit store: real SQLite persistence (replaces the InMemory stop-gap).
    audit_settings = AuditSettings()
    audit_store = SqliteAuditStore(
        db_path=audit_settings.db_path,
        conversation_window=audit_settings.conversation_window,
        busy_timeout_ms=audit_settings.busy_timeout_ms,
    )
    await audit_store.initialize()
    app.state.audit_store: AuditStore = audit_store

    # 7-day rolling retention sweep — the composition root owns the task.
    sweeper = RetentionSweeper(
        audit_store, retention_days=audit_settings.retention_days
    )
    app.state._retention_sweeper = sweeper
    app.state._retention_task = asyncio.create_task(sweeper.run())

    # --- Frontline classifier + OCR (UNCHANGED — Ollama stand-in by default).
    app.state.classifier: TextClassifier = _build_classifier()
    app.state.ocr: OcrBackend = _build_ocr()

    # --- Triage: the deterministic gate (was the inline _triage()).
    app.state.triage: TriageEngine = ThresholdTriageEngine(TriageSettings())

    # --- Alerts: channel chosen by ALERTS_CHANNEL (default "log").
    #     "ntfy" needs ALERTS_NTFY_TOPIC (free push via ntfy.sh, no account);
    #     "fcm" needs firebase-admin + FCM_SERVICE_ACCOUNT_PATH. Both degrade to
    #     a sent=False "not configured" result rather than crashing if unset.
    alert_settings = AlertSettings()
    rate_limiter = InMemoryAlertRateLimiter(
        max_alerts=alert_settings.rate_limit_max_alerts,
        window_seconds=alert_settings.rate_limit_window_seconds,
    )
    retry_queue = LocalRetryQueue(max_size=alert_settings.queue_max_size)

    async def _alert_audit_recorder(req: AlertRequest, res: AlertResult) -> None:
        """Persist every alert disposition to the audit store (best-effort)."""
        try:
            await audit_store.record_alert(
                alert_id=res.alert_id,
                trace_id=req.trace_id,
                child_id=req.child_id,
                label=req.label,
                severity=req.severity,
                quote_snippet=req.quote,
                explanation=req.explanation,
                fcm_status=_alert_status(res),
            )
        except Exception as exc:  # noqa: BLE001 — audit is best-effort
            log.warning("alert_audit_failed", error=str(exc))

    _alert_channel = alert_settings.channel.strip().lower()
    notifier: NotificationChannel
    if _alert_channel == "ntfy":
        notifier = NtfyNotifier(
            alert_settings, rate_limiter, retry_queue, _alert_audit_recorder
        )
    elif _alert_channel == "fcm":
        notifier = FcmNotifier(
            alert_settings, rate_limiter, retry_queue, _alert_audit_recorder
        )
    elif _alert_channel == "stub":
        notifier = StubNotifier()
    else:
        notifier = LogNotifier(
            alert_settings, rate_limiter, retry_queue, _alert_audit_recorder
        )
    app.state.notifier = notifier

    # --- Context Agent (borderline reasoning; reads conversation history).
    app.state.context_agent: ContextReasoner | None = _build_context_agent(
        audit_store
    )

    # --- Dedup store + FlaggedEventStore + MonitorIngest (S1 monitor path).
    app.state.dedup, app.state.flagged, app.state.monitor = await _build_monitor(app)

    # --- Identity store (S2 — child/parent identity + device-token auth).
    app.state.identity: IdentityStore = await _build_identity()

    # --- DigestScheduler + DigestStore (S3 — daily digest + FCM push).
    app.state.digest_scheduler, app.state.digest_store = await _build_digest(
        flagged_store=app.state.flagged,
        notifier=notifier,
        identity=app.state.identity,
    )

    # Wire the critical-immediate callback into MonitorIngest.
    # The callback is a closure over the digest scheduler + notifier — it fires
    # an immediate single-event push for critical/high severity alerted events,
    # bypassing the daily digest cadence.  MonitorIngest stays import-clean of
    # digest/identity concretes (only sees this Callable).
    from .digest.settings import DigestSettings as _DigestSettings

    _digest_settings = _DigestSettings()
    if _digest_settings.enabled and _digest_settings.critical_immediate:
        async def _on_critical_flag(flagged_event) -> None:
            """Immediate push for a critical/high severity alerted event."""
            parent_id = await app.state.identity.parent_for_child(flagged_event.child_id)
            if parent_id is None:
                return
            fcm_token = await app.state.identity.fcm_token_for_parent(parent_id)
            from .schemas import AlertRequest as _AlertRequest

            req = _AlertRequest(
                child_id=flagged_event.child_id,
                message_id=f"critical:{flagged_event.flag_id}",
                label=flagged_event.label,
                severity=flagged_event.severity,
                explanation=flagged_event.explanation[:280],
                quote=flagged_event.quote,
                source=flagged_event.source,
                trace_id=flagged_event.trace_id,
                parent_fcm_token=fcm_token or "",
            )
            try:
                result = await notifier.send_alert(req)
                log.info(
                    "digest.critical_immediate_sent",
                    flag_id=flagged_event.flag_id,
                    child_id=flagged_event.child_id,
                    severity=flagged_event.severity,
                    sent=result.sent,
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("digest.critical_immediate_failed", error=str(exc))

        app.state.monitor._on_critical_flag = _on_critical_flag
        log.info("digest.critical_immediate_enabled")

    # Start the asyncio cron scheduler background task if applicable.
    from .digest import AsyncioCronDigestScheduler as _AsyncioCronScheduler

    app.state._digest_task = None
    if isinstance(app.state.digest_scheduler, _AsyncioCronScheduler):
        app.state._digest_task = asyncio.create_task(app.state.digest_scheduler.run())
        log.info("digest_cron_task_started")

    log.info(
        "server_ready",
        classifier=app.state.classifier.model_version,
        ocr=app.state.ocr.backend_name,
        triage="ThresholdTriageEngine",
        notifier=app.state.notifier.__class__.__name__,
        context_agent_enabled=app.state.context_agent is not None,
        audit="SqliteAuditStore",
        monitor="MonitorIngest",
        dedup=app.state.dedup.__class__.__name__,
        flagged=app.state.flagged.__class__.__name__,
        identity=app.state.identity.__class__.__name__,
        digest=app.state.digest_scheduler.__class__.__name__ if app.state.digest_scheduler else "disabled",
        version="0.6.3-parent-review",
    )

    yield

    # --- Shutdown — stop the sweeper, close the DB connections cleanly.
    sweeper.stop()
    try:
        await app.state._retention_task
    except Exception as exc:  # noqa: BLE001
        log.warning("retention_task_shutdown_error", error=str(exc))

    # Stop the digest cron task if running.
    if app.state._digest_task is not None:
        if hasattr(app.state.digest_scheduler, "stop"):
            app.state.digest_scheduler.stop()
        try:
            await app.state._digest_task
        except Exception as exc:  # noqa: BLE001
            log.warning("digest_task_shutdown_error", error=str(exc))

    await audit_store.close()
    # Close the flagged store if it has a close() method (SqliteFlaggedEventStore does).
    if hasattr(app.state.flagged, "close"):
        try:
            await app.state.flagged.close()
        except Exception as exc:  # noqa: BLE001
            log.warning("flagged_store_close_error", error=str(exc))
    # Close the identity store (SqliteIdentityStore checkpoints WAL on close).
    if hasattr(app.state, "identity") and hasattr(app.state.identity, "close"):
        try:
            await app.state.identity.close()
        except Exception as exc:  # noqa: BLE001
            log.warning("identity_store_close_error", error=str(exc))
    # Close the digest store if it has a close() method (SqliteDigestStore does).
    if hasattr(app.state, "digest_store") and hasattr(app.state.digest_store, "close"):
        try:
            await app.state.digest_store.close()
        except Exception as exc:  # noqa: BLE001
            log.warning("digest_store_close_error", error=str(exc))
    log.info("server_shutdown")


app = FastAPI(
    title="Shomer.AI Server",
    version="0.5.0-modular",
    lifespan=lifespan,
)

# Middleware registration. Starlette applies these in REVERSE order (last added
# = outermost = first to run on the request path). Target request-path order:
#   Gatekeeper(timeout → size → trace → rate-limit → prometheus) → CORS → Audit
# so AuditLoggingMiddleware is added first (innermost), then CORS, then the
# Gatekeeper group last (outermost). See docs/design/gatekeeper/design.md §3.2.
app.add_middleware(AuditLoggingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
register_gateway(app, GatekeeperSettings.from_env())
register_monitor(app)
register_identity(app)
register_digest(app)
register_parent_review(app)


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
# Shared classification pipeline — used by /classify and /classify-image.
#
# Flow: TextClassifier → TriageEngine → (borderline) ContextReasoner →
# (ALERT_DIRECT) NotificationChannel → AuditStore (+ conversation turn).
# Every step is resilient: triage/alerts/CA never raise, and the audit writes
# are best-effort so a DB hiccup never 500s a classification.
# ---------------------------------------------------------------------------


async def _dispatch_alert(
    request: Request,
    text: str,
    result: ClassificationResult,
    ctx: ContextDecision | None,
    *,
    trace_id: str,
    child_id: str | None,
    message_id: str | None,
) -> None:
    """Build an ``AlertRequest`` and hand it to the NotificationChannel.

    The notifier records the disposition to the audit store via its injected
    recorder, and never raises — we still guard defensively.
    """
    if ctx is not None:
        explanation, source = ctx.explanation, "context_agent"
    else:
        explanation = f"זוהתה הודעה פוגענית מסוג {result.label}."
        source = "frontline_direct"

    alert_req = AlertRequest(
        child_id=child_id or "unknown",
        message_id=message_id or trace_id,
        label=result.label,
        severity=derive_severity(result.label, result.confidence),
        explanation=explanation[:280],
        quote=text[:200],
        source=source,
        trace_id=trace_id,
    )
    try:
        res = await request.app.state.notifier.send_alert(alert_req)
        request.state.audit["alert"] = {
            "alert_id": res.alert_id,
            "sent": res.sent,
            "channel": res.channel,
            "rate_limited": res.rate_limited,
        }
    except Exception as exc:  # noqa: BLE001 — alerting is best-effort
        log.warning("alert_dispatch_failed", trace_id=trace_id, error=str(exc))


async def _persist_turn(
    request: Request,
    child_id: str,
    text: str,
    conversation_id: str = "default",
) -> None:
    """Persist the child's message so the Context Agent's read_history works.

    Scoped to ``(child_id, conversation_id)`` so different chat threads never
    bleed into each other's history.
    """
    store = request.app.state.audit_store
    try:
        prev = await store.read_conversation_history(
            child_id, last_n_turns=1, conversation_id=conversation_id
        )
        next_index = (prev[-1].turn_index + 1) if prev else 0
        await store.record_conversation_turn(
            child_id=child_id,
            turn_index=next_index,
            role="child_outbound",
            text=text,
            conversation_id=conversation_id,
        )
    except Exception as exc:  # noqa: BLE001 — best-effort
        log.warning("conversation_persist_failed", error=str(exc))


async def _run_pipeline(
    request: Request,
    text: str,
    *,
    trace_id: str,
    child_id: str | None,
    message_id: str | None,
    input_type: str = "text",
    ocr_extracted_text: str | None = None,
    image_hash: str | None = None,
    conversation_turns: list[dict] | None = None,
    conversation_id: str = "default",
) -> tuple[ClassificationResult, TriageDecision, ContextDecision | None]:
    """Run the full text pipeline; return (classifier result, final decision).

    ``conversation_id`` scopes the conversation history lookup to a single chat
    thread.  When ``conversation_turns`` is None AND the caller is a text-event
    monitor event with a ``child_id``, this function fetches the scoped history
    from the audit store and passes it as ``provided_history`` to the Context
    Agent — so the CA NEVER uses its unscoped ``read_history`` tool for monitor
    events (which caused the Daria cross-thread bleed bug).
    """
    app = request.app

    # 1. Frontline classifier (UNCHANGED — Ollama stand-in by default).
    result: ClassificationResult = await app.state.classifier.classify(text)

    # 2. Triage (deterministic gate; the G-03 normalization lives in the engine).
    context_agent_enabled = app.state.context_agent is not None
    triage_decision = app.state.triage.decide(result, context_agent_enabled)
    frontline_only_decision = triage_decision  # snapshot BEFORE the CA runs

    # 3. Resolve history for the Context Agent.
    #
    # For TEXT monitor events (conversation_turns is None) with a child_id, we
    # fetch the scoped conversation history from the audit store and pass it as
    # provided_history.  This prevents the CA from using its unscoped
    # read_history tool which would see the child's ENTIRE message stream across
    # all chats — the root cause of the cross-thread false-alarm bug.
    #
    # For SCREENSHOT events, conversation_turns is already provided by the
    # router (the OCR segments serve as the context).  For /classify (no
    # child_id), we leave conversation_turns as-is (None → CA uses its tool).
    resolved_history: list[dict] | None = conversation_turns
    if resolved_history is None and child_id and input_type == "monitor":
        # Text monitor event: fetch scoped thread history.
        try:
            turns = await app.state.audit_store.read_conversation_history(
                child_id,
                last_n_turns=app.state.context_agent.max_history_turns
                if hasattr(app.state.context_agent, "max_history_turns")
                else 5,
                conversation_id=conversation_id,
            )
            resolved_history = [
                {"role": t.role, "text": t.text} for t in turns
            ]
        except Exception as exc:  # noqa: BLE001 — best-effort, CA runs with no history
            log.warning(
                "scoped_history_fetch_failed",
                child_id=child_id,
                conversation_id=conversation_id,
                error=str(exc),
            )
            resolved_history = []

    # 4. Context Agent — only on borderline (ESCALATE_TO_CA).
    ctx_decision: ContextDecision | None = None
    if (
        triage_decision == TriageDecision.ESCALATE_TO_CA
        and context_agent_enabled
    ):
        ctx_decision = await app.state.context_agent.evaluate(
            text, result, child_id=child_id, trace_id=trace_id,
            provided_history=resolved_history,
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

    # 5. Alert on a confirmed threat.
    if triage_decision == TriageDecision.ALERT_DIRECT:
        await _dispatch_alert(
            request,
            text,
            result,
            ctx_decision,
            trace_id=trace_id,
            child_id=child_id,
            message_id=message_id,
        )

    # 6. Record the decision + the CA reasoning trace (best-effort — a DB
    #    hiccup must never 500 a classification).
    try:
        classification_id = await app.state.audit_store.record_classification(
            trace_id=trace_id,
            request_text=text,
            classifier_result=result,
            triage_decision=triage_decision,
            context_agent_enabled=context_agent_enabled,
            frontline_only_decision=str(frontline_only_decision.value),
            child_id=child_id,
            message_id=message_id,
            input_type=input_type,
            ocr_extracted_text=ocr_extracted_text,
            image_hash=image_hash,
        )
        if ctx_decision is not None:
            await app.state.audit_store.record_agent_trace(
                classification_id=classification_id,
                trace_id=trace_id,
                agent_input={
                    "text": text,
                    "label": result.label,
                    "confidence": result.confidence,
                    "child_id": child_id,
                    "conversation_id": conversation_id,
                },
                decision=ctx_decision,
                tools_called=[
                    {"name": t} for t in ctx_decision.tools_called
                ],
            )
    except Exception as exc:  # noqa: BLE001 — audit is best-effort
        log.warning("audit_record_failed", trace_id=trace_id, error=str(exc))

    # 7. Persist conversation turn — only for single-text events (not screenshots).
    #    When ``conversation_turns`` is provided the text is an OCR segment from
    #    a screenshot; those segments must NOT be written to the per-child
    #    ``conversations`` table because:
    #      a) the screenshot already contains both sides of the conversation, so
    #         the wrong role would be persisted, and
    #      b) UI chrome lines (contact names, timestamps) would pollute history.
    #    Scoped by ``conversation_id`` so turns from different chat threads are
    #    kept separate (the fix for the cross-thread Daria bleed bug).
    if child_id and conversation_turns is None:
        await _persist_turn(request, child_id, text, conversation_id=conversation_id)

    request.state.audit["triage_decision"] = triage_decision.value
    request.state.audit["classifier_model"] = result.model_version
    return result, triage_decision, ctx_decision


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
    if req.child_id:
        request.state.audit["child_id"] = req.child_id

    started = time.perf_counter()
    trace_id = _trace_id(request)

    result, _, _ctx = await _run_pipeline(
        request,
        req.text,
        trace_id=trace_id,
        child_id=req.child_id,
        message_id=req.message_id,
    )

    latency_ms = int((time.perf_counter() - started) * 1000)
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
    child_id: str | None = Form(None),
    strategy: str | None = None,  # accepted for back-compat; Architecture B uses OCR only.
) -> ClassifyImageResponse:
    """Classify an uploaded image: OCR extraction → text classifier pipeline.

    The ``?strategy=`` query param is silently accepted but ignored — the
    locked Architecture B path is OCR-only (no vision LLM, per PRD §11.1).
    An optional ``child_id`` form field threads the OCR text into the same
    conversation-history persistence as /classify.
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
    image_hash = hashlib.sha256(image_bytes).hexdigest()[:16]

    # 1. OCR extraction (NEVER raises per OcrBackend contract).
    ocr_result: OcrResult = await app.state.ocr.process(
        image_bytes,
        mime_type=image.content_type or "image/jpeg",
    )

    # 2. If unreadable, return early — safe default (REVIEW_NEEDED, no alert).
    if ocr_result.image_unreadable or not ocr_result.extracted_text.strip():
        latency_ms = int((time.perf_counter() - started) * 1000)
        try:
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
                child_id=child_id,
                input_type="image",
                ocr_extracted_text=ocr_result.extracted_text,
                image_hash=image_hash,
            )
        except Exception as exc:  # noqa: BLE001 — audit is best-effort
            log.warning("audit_record_failed", trace_id=trace_id, error=str(exc))
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

    # 3. Run the OCR text through the same pipeline as /classify.
    result, _, _ctx = await _run_pipeline(
        request,
        ocr_result.extracted_text,
        trace_id=trace_id,
        child_id=child_id,
        message_id=None,
        input_type="image",
        ocr_extracted_text=ocr_result.extracted_text,
        image_hash=image_hash,
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
