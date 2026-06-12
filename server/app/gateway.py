"""Gatekeeper / API Gateway — operational edge middleware for Shomer.AI.

This module is content-blind: it does NOT interpret message content, does NOT
call Ollama, and does NOT write to the Audit Log. It owns:
  - Rate limiting (slowapi, in-memory store, fail-open)
  - Trace-id injection (X-Trace-ID header, structlog contextvars)
  - Request size enforcement (413 on Content-Length > max_body_bytes)
  - Request timeout enforcement (408 on stalled client upload)
  - Prometheus metrics (/metrics endpoint via prometheus-fastapi-instrumentator)
  - Device/parent token auth (S2) — populates request.state.device_context

Public entry point: ``register_gateway(app, settings)`` — called once from
``main.py`` to install all middleware in the correct order.

Isolation contract (LLD §2.5):
  - MAY import: stdlib, fastapi, starlette, slowapi, structlog, prometheus_client,
    prometheus_fastapi_instrumentator, pydantic_settings.
  - MUST NOT import: classifier, ocr, triage, context_agent, alerts, audit_log,
    or server.app.main.
  - MAY read app.state.identity via the IdentityStore Protocol (never a concrete
    adapter). The identity module's protocol is a pure Protocol interface.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from typing import Awaitable, Callable, Protocol

import structlog
import structlog.contextvars
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from pydantic import Field
from pydantic_settings import BaseSettings
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

log = structlog.get_logger("shomer.gateway")

# ---------------------------------------------------------------------------
# Protocols (§2.5 — interface boundary)
# ---------------------------------------------------------------------------


class TraceIdGenerator(Protocol):
    """Produces a globally-unique trace id for each request."""

    def new_id(self) -> str: ...


class MetricsEmitter(Protocol):
    """Emits request lifecycle metrics."""

    def request_started(self, method: str, path: str) -> None: ...
    def request_completed(
        self, method: str, path: str, status: int, duration_s: float
    ) -> None: ...
    def rate_limit_hit(self, client_ip_hash: str, path: str) -> None: ...
    def payload_rejected(self, path: str) -> None: ...


class RateLimitStore(Protocol):
    """Backing store for the rate limiter — in-memory MVP; Redis in Phase 9."""

    async def is_allowed(self, key: str, max_per_window: int, window_s: int) -> bool: ...
    async def increment(self, key: str, window_s: int) -> int: ...


# ---------------------------------------------------------------------------
# Default adapters
# ---------------------------------------------------------------------------


class Uuid4TraceIdGenerator:
    """Default trace-id adapter — 128-bit random UUID4."""

    def new_id(self) -> str:
        return str(uuid.uuid4())


_default_trace_id_generator: TraceIdGenerator = Uuid4TraceIdGenerator()

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


class GatekeeperSettings(BaseSettings):
    """All Gatekeeper config, loaded from environment variables.

    Every field has a safe default so the gateway works with no .env file
    (useful for tests and local dev).
    """

    rate_limit_per_minute: int = Field(default=100, alias="RATE_LIMIT_PER_MINUTE")
    rate_limit_store_url: str = Field(default="", alias="RATE_LIMIT_STORE_URL")
    max_body_bytes: int = Field(default=10 * 1024 * 1024, alias="MAX_BODY_BYTES")  # 10 MB
    client_recv_timeout_s: float = Field(default=30.0, alias="CLIENT_RECV_TIMEOUT_S")
    metrics_endpoint: str = Field(default="/metrics", alias="METRICS_ENDPOINT")
    metrics_latency_buckets: str = Field(
        default="0.01,0.05,0.1,0.25,0.5,1.0,2.0,5.0",
        alias="METRICS_LATENCY_BUCKETS",
    )
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_format: str = Field(default="json", alias="LOG_FORMAT")

    model_config = {"populate_by_name": True, "extra": "ignore"}

    @classmethod
    def from_env(cls) -> "GatekeeperSettings":
        return cls()

    @property
    def latency_buckets(self) -> tuple[float, ...]:
        return tuple(float(b) for b in self.metrics_latency_buckets.split(","))


# ---------------------------------------------------------------------------
# Prometheus custom metrics — module-level singletons with duplicate-
# registration guard. The guard lets tests call register_gateway() multiple
# times (each test creates a fresh app) without hitting Duplicated timeseries.
# ---------------------------------------------------------------------------

from prometheus_client import Counter, Gauge, Histogram  # noqa: E402


def _make_counter(name: str, documentation: str, labelnames: list[str]) -> Counter:
    """Create or re-use a Counter, guarding against duplicate registration."""
    try:
        return Counter(name, documentation, labelnames)
    except ValueError:
        # Already registered in this process — return the existing one.
        from prometheus_client import REGISTRY

        return REGISTRY._names_to_collectors.get(  # type: ignore[attr-defined]
            name, Counter.__new__(Counter)
        )


def _make_histogram(
    name: str, documentation: str, labelnames: list[str], buckets: tuple[float, ...]
) -> Histogram:
    """Create or re-use a Histogram."""
    try:
        return Histogram(name, documentation, labelnames, buckets=buckets)
    except ValueError:
        from prometheus_client import REGISTRY

        return REGISTRY._names_to_collectors.get(  # type: ignore[attr-defined]
            name, Histogram.__new__(Histogram)
        )


def _make_gauge(name: str, documentation: str, labelnames: list[str]) -> Gauge:
    """Create or re-use a Gauge."""
    try:
        return Gauge(name, documentation, labelnames)
    except ValueError:
        from prometheus_client import REGISTRY

        return REGISTRY._names_to_collectors.get(  # type: ignore[attr-defined]
            name, Gauge.__new__(Gauge)
        )


# Module-level metric singletons (initialised on first import).
_RATE_LIMIT_COUNTER: Counter | None = None
_PAYLOAD_REJECTED_COUNTER: Counter | None = None
_GATEWAY_OVERHEAD_HISTOGRAM: Histogram | None = None
_ACTIVE_REQUESTS_GAUGE: Gauge | None = None

_LATENCY_BUCKETS_DEFAULT = (0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0)


def _init_custom_metrics(
    buckets: tuple[float, ...] = _LATENCY_BUCKETS_DEFAULT,
) -> None:
    """Initialise (or skip if already registered) the custom Gatekeeper metrics."""
    global _RATE_LIMIT_COUNTER, _PAYLOAD_REJECTED_COUNTER
    global _GATEWAY_OVERHEAD_HISTOGRAM, _ACTIVE_REQUESTS_GAUGE

    if _RATE_LIMIT_COUNTER is None:
        _RATE_LIMIT_COUNTER = _make_counter(
            "shomer_gateway_rate_limit_total",
            "Total requests rejected by rate limiter",
            ["client_ip_hash", "handler"],
        )
    if _PAYLOAD_REJECTED_COUNTER is None:
        _PAYLOAD_REJECTED_COUNTER = _make_counter(
            "shomer_gateway_payload_rejected_total",
            "Total requests rejected for payload size",
            ["handler"],
        )
    if _GATEWAY_OVERHEAD_HISTOGRAM is None:
        _GATEWAY_OVERHEAD_HISTOGRAM = _make_histogram(
            "shomer_gateway_overhead_seconds",
            "Gateway processing time excluding endpoint (seconds)",
            [],
            buckets,
        )
    if _ACTIVE_REQUESTS_GAUGE is None:
        _ACTIVE_REQUESTS_GAUGE = _make_gauge(
            "shomer_gateway_active_requests",
            "In-flight requests",
            ["handler"],
        )


# ---------------------------------------------------------------------------
# Middleware implementations
# ---------------------------------------------------------------------------


class TraceIdMiddleware(BaseHTTPMiddleware):
    """Generate an ``X-Trace-ID`` header for every request.

    Algorithm:
    1. Honor an inbound ``X-Trace-Id`` header if present (lets SDK forward its
       own correlation id).
    2. Generate a new UUID4 otherwise.
    3. Bind the trace_id to structlog contextvars so all downstream log lines
       are correlated automatically.
    4. Attach the header to the response before returning.
    5. Clear structlog contextvars when the response exits this middleware.
    """

    def __init__(
        self,
        app: ASGIApp,
        generator: TraceIdGenerator | None = None,
    ) -> None:
        super().__init__(app)
        self._generator = generator or _default_trace_id_generator

    async def dispatch(self, request: Request, call_next) -> Response:
        # Honor inbound trace-id (case-insensitive header lookup via Starlette).
        inbound = request.headers.get("X-Trace-Id") or request.headers.get("X-Trace-ID")
        trace_id = inbound if inbound else self._generator.new_id()

        # Attach to request state so endpoint handlers can read it.
        request.state.trace_id = trace_id

        # Bind to structlog — all downstream log calls inherit this context.
        structlog.contextvars.bind_contextvars(trace_id=trace_id)
        try:
            response = await call_next(request)
        except Exception:
            structlog.contextvars.clear_contextvars()
            raise
        finally:
            structlog.contextvars.clear_contextvars()

        response.headers["X-Trace-ID"] = trace_id
        return response


class RequestSizeMiddleware:
    """Reject requests whose ``Content-Length`` exceeds ``max_bytes`` with 413.

    This is a raw ASGI middleware (not BaseHTTPMiddleware) so it can return
    the 413 *before* the body is read — consistent with the LLD contract that
    says "without reading the body."

    Chunked uploads (no Content-Length header) are passed through with a
    warning log — enforcement of chunked body size is deferred to Phase 2+
    (see LLD §11 open question 5).
    """

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            headers = dict(scope.get("headers", []))
            content_length_raw = headers.get(b"content-length")
            if content_length_raw is not None:
                try:
                    content_length = int(content_length_raw)
                except ValueError:
                    content_length = 0

                if content_length > self.max_bytes:
                    # Retrieve trace_id from structlog context if available.
                    ctx = structlog.contextvars.get_contextvars()
                    trace_id = ctx.get("trace_id", str(uuid.uuid4()))

                    path = scope.get("path", "unknown")
                    log.warning(
                        "payload_rejected",
                        path=path,
                        size_bytes=content_length,
                        max_bytes=self.max_bytes,
                        trace_id=trace_id,
                    )

                    # Increment custom Prometheus counter if initialised.
                    if _PAYLOAD_REJECTED_COUNTER is not None:
                        try:
                            _PAYLOAD_REJECTED_COUNTER.labels(handler=path).inc()
                        except Exception:
                            pass

                    body = json.dumps(
                        {
                            "error": "payload_too_large",
                            "detail": f"Request body exceeds {self.max_bytes} bytes",
                            "max_bytes": self.max_bytes,
                            "trace_id": trace_id,
                        }
                    ).encode()
                    response = Response(
                        content=body,
                        status_code=413,
                        media_type="application/json",
                        headers={"X-Trace-ID": trace_id},
                    )
                    await response(scope, receive, send)
                    return
            else:
                # Chunked / unknown length — pass through with warning.
                path = scope.get("path", "unknown")
                log.warning(
                    "chunked_upload_no_size_check",
                    path=path,
                    note="Content-Length absent; size enforcement skipped for chunked upload",
                )

        await self.app(scope, receive, send)


class RequestTimeoutMiddleware(BaseHTTPMiddleware):
    """Kill stalled client connections with a 408 after ``timeout_s`` seconds.

    Uses ``asyncio.wait_for`` around ``call_next`` so the timeout fires if the
    downstream chain (including endpoint processing) does not complete in time.

    Note: the LLD (§11 open question 6) clarifies that ``CLIENT_RECV_TIMEOUT_S``
    governs client upload time, not classification time. The classification
    timeout is enforced separately by httpx inside the endpoint handlers.
    """

    def __init__(self, app: ASGIApp, timeout_s: float) -> None:
        super().__init__(app)
        self.timeout_s = timeout_s

    async def dispatch(self, request: Request, call_next) -> Response:
        ctx = structlog.contextvars.get_contextvars()
        trace_id = ctx.get(
            "trace_id",
            getattr(request.state, "trace_id", str(uuid.uuid4())),
        )
        try:
            response = await asyncio.wait_for(
                call_next(request), timeout=self.timeout_s
            )
            return response
        except asyncio.TimeoutError:
            log.warning(
                "request_timeout",
                path=request.url.path,
                timeout_s=self.timeout_s,
                trace_id=trace_id,
            )
            return JSONResponse(
                status_code=408,
                content={
                    "error": "request_timeout",
                    "detail": f"Client did not complete the request within {self.timeout_s}s",
                    "trace_id": trace_id,
                },
                headers={"X-Trace-ID": trace_id},
            )


# ---------------------------------------------------------------------------
# Rate limiter + custom middleware (fail-open aware)
# ---------------------------------------------------------------------------


def build_limiter(settings: GatekeeperSettings) -> Limiter:
    """Build a slowapi Limiter keyed on client IP.

    Fail-open semantics (LLD §8 + PRD §8.7): if the rate-limit store raises
    unexpectedly, requests are allowed through. We handle this in the custom
    ``RateLimitMiddleware`` below rather than relying on SlowAPIMiddleware's
    ``swallow_errors`` path (which has a bug where ``request.state.view_rate_limit``
    may be missing after a swallowed error, causing an AttributeError on
    header injection).

    The ``default_limits`` list is constructed from ``settings.rate_limit_per_minute``
    so tests can pass a small value to trigger 429s quickly.
    """
    limit_string = f"{settings.rate_limit_per_minute}/minute"
    return Limiter(
        key_func=get_remote_address,
        default_limits=[limit_string],
        swallow_errors=True,  # belt-and-suspenders; main guard is our try/except below
        headers_enabled=True,
    )


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Custom rate-limit middleware wrapping the slowapi Limiter.

    Unlike ``slowapi.middleware.SlowAPIMiddleware``, this implementation:
    - Catches ALL exceptions from the limiter (including RateLimitExceeded) and
      handles them explicitly.
    - Never crashes on a missing ``request.state.view_rate_limit`` attribute
      (the bug in SlowAPIMiddleware when swallow_errors fires).
    - Returns structured 429 JSON (matching §2.2 contract) with trace_id.
    - Fails open on any non-RateLimitExceeded exception (PRD §8.7).
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        limiter: Limiter | None = getattr(request.app.state, "limiter", None)
        if limiter is None or not limiter.enabled:
            return await call_next(request)

        try:
            # _check_request_limit raises RateLimitExceeded when the limit is hit.
            limiter._check_request_limit(request, endpoint_func=None, in_middleware=True)
        except RateLimitExceeded as exc:
            # Limit hit — return structured 429.
            return _rate_limit_handler(request, exc)
        except Exception:
            # Any other exception (storage outage, etc.) → fail-open: log + allow.
            log.warning(
                "rate_limit_store_error_fail_open",
                path=request.url.path,
                note="Rate limit check failed; allowing request (fail-open)",
            )
            return await call_next(request)

        return await call_next(request)


# ---------------------------------------------------------------------------
# Device / parent token auth middleware (S2)
# ---------------------------------------------------------------------------

# Paths that do NOT require a valid device token.  Includes:
#   - Health / metrics / docs — operational + monitoring
#   - Bootstrap / pairing endpoints — cannot require auth (they issue auth)
#   - Legacy single-shot endpoints — kept open for back-compat + dev tooling
#     (tightening them is out of S2 scope; document this if auditing)
_AUTH_ALLOWLIST: frozenset[str] = frozenset(
    {
        "/",
        "/health",
        "/metrics",
        "/docs",
        "/openapi.json",
        "/redoc",
        # Identity bootstrap (S2)
        "/v1/parent/register",
        "/v1/parent/login",
        "/v1/pair",
        # Legacy single-shot dev/back-compat endpoints — kept open
        "/classify",
        "/classify-image",
        "/model/info",
    }
)

# Path prefixes that are always public (static assets, root redirect).
# The DeviceAuthMiddleware checks this in addition to _AUTH_ALLOWLIST.
_AUTH_ALLOWLIST_PREFIXES: tuple[str, ...] = (
    "/dashboard",  # static web UI — public; data API calls carry their own token
)



class DeviceAuthMiddleware(BaseHTTPMiddleware):
    """Resolve ``Authorization: Bearer <token>`` → ``request.state.device_context``.

    Behavior:
      - Always sets ``request.state.device_context = None`` first.
      - If no ``app.state.identity`` is configured (e.g. pre-S2 tests), passes
        through silently (fail-open by design — existing tests must not break).
      - Reads the Bearer token; if missing, leaves device_context as None (the
        individual resource handler enforces whether auth is required).
      - On a recognized token, sets ``device_context`` to the resolved
        ``DeviceContext``.  The middleware does NOT return 401 by itself — the
        router enforces auth requirements per-resource (monitor endpoint enforces
        presence + child_id match; parent endpoints enforce role="parent").

    This middleware is content-blind: it imports the IdentityStore *Protocol*
    off ``app.state.identity``, never a concrete adapter.

    Position in the Gatekeeper stack: runs AFTER TraceIdMiddleware (so trace_id
    is already set) and BEFORE the rate limiter from the perspective of the
    request path — i.e., registered AFTER RateLimitMiddleware in add_middleware
    order (Starlette reverse registration).
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        # Default: no identity resolved.
        request.state.device_context = None

        # Skip if identity store is not configured (graceful degradation).
        identity = getattr(getattr(request.app, "state", None), "identity", None)
        if identity is None:
            return await call_next(request)

        # Skip allowlisted paths — they bootstrap auth or are public.
        path = request.url.path
        if path in _AUTH_ALLOWLIST:
            return await call_next(request)
        # Skip paths matching a public prefix (e.g. /dashboard/...).
        if any(path == prefix or path.startswith(prefix + "/") for prefix in _AUTH_ALLOWLIST_PREFIXES):
            return await call_next(request)

        # Extract Bearer token.
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return await call_next(request)

        raw_token = auth_header[len("Bearer "):].strip()
        if not raw_token:
            return await call_next(request)

        # Resolve: try device token first, then parent token.
        try:
            ctx = await identity.authenticate_device(raw_token)
            if ctx is None:
                ctx = await identity.authenticate_parent(raw_token)
            if ctx is not None:
                request.state.device_context = ctx
        except Exception as exc:  # noqa: BLE001 — auth is best-effort
            log.warning(
                "auth_middleware_error",
                path=path,
                error=str(exc),
                note="Continuing with no device_context (fail-open)",
            )

        return await call_next(request)


# ---------------------------------------------------------------------------
# Rate limit exception handler
# ---------------------------------------------------------------------------


def _rate_limit_handler(request: Request, exc: RateLimitExceeded) -> Response:
    """Return a structured 429 JSON response with ``trace_id`` and ``Retry-After``."""
    ctx = structlog.contextvars.get_contextvars()
    trace_id = ctx.get(
        "trace_id",
        getattr(request.state, "trace_id", str(uuid.uuid4())),
    )

    # Extract the limit string from the exception.
    limit_str = str(exc.detail) if exc.detail else "rate limit exceeded"

    # Compute retry_after: slowapi sets response headers via _inject_headers;
    # we derive it conservatively as 60 s (the window size) for the MVP.
    retry_after_seconds = 60

    # Log the rate-limit hit.
    client_ip = request.client.host if request.client else "unknown"
    client_ip_hash = hashlib.sha256(client_ip.encode()).hexdigest()[:16]

    log.warning(
        "rate_limit_exceeded",
        client_ip=client_ip,
        path=request.url.path,
        limit=limit_str,
        retry_after_s=retry_after_seconds,
        trace_id=trace_id,
    )

    # Increment custom counter if initialised.
    if _RATE_LIMIT_COUNTER is not None:
        try:
            _RATE_LIMIT_COUNTER.labels(
                client_ip_hash=client_ip_hash, handler=request.url.path
            ).inc()
        except Exception:
            pass

    return JSONResponse(
        status_code=429,
        content={
            "error": "rate_limit_exceeded",
            "detail": limit_str,
            "retry_after_seconds": retry_after_seconds,
            "trace_id": trace_id,
        },
        headers={
            "Retry-After": str(retry_after_seconds),
            "X-Trace-ID": trace_id,
        },
    )


# ---------------------------------------------------------------------------
# Prometheus instrumentator
# ---------------------------------------------------------------------------


def build_metrics_instrumentator(
    settings: GatekeeperSettings | None = None,
) -> "Instrumentator":  # type: ignore[name-defined]  # noqa: F821
    """Build a prometheus_fastapi_instrumentator Instrumentator.

    Uses a ``shomer_`` metric namespace prefix and the latency buckets from
    settings (or the defaults if settings is None).
    """
    from prometheus_fastapi_instrumentator import Instrumentator

    buckets = settings.latency_buckets if settings else _LATENCY_BUCKETS_DEFAULT

    return Instrumentator(
        should_group_status_codes=True,
        should_instrument_requests_inprogress=False,
    )


# ---------------------------------------------------------------------------
# register_gateway — single public entry point
# ---------------------------------------------------------------------------


def register_gateway(app: FastAPI, settings: GatekeeperSettings) -> None:
    """Install all Gatekeeper components in the correct order.

    Starlette's ``app.add_middleware()`` applies middleware in REVERSE
    registration order (last-added = outermost = first to run on request).
    So we register in reverse of the desired execution order:

    Desired execution order (request path):
        1. RequestTimeoutMiddleware   — outermost; kill stalled connections first
        2. RequestSizeMiddleware      — reject oversized bodies next
        3. TraceIdMiddleware          — inject trace-id before anything else logs
        4. slowapi rate-limit check   — reject over-limit (trace-id now available)
        5. Prometheus instrumentator  — measure everything that passes the gate
        (CORS and AuditLoggingMiddleware are registered in main.py, outside this fn)

    Registration order inside this function (first-added = innermost):
        1. Prometheus (innermost of gateway group)
        2. RateLimitMiddleware (custom, fail-open aware)
        3. TraceIdMiddleware
        4. RequestSizeMiddleware
        5. RequestTimeoutMiddleware (outermost of gateway group)
    """
    # Initialise custom Prometheus counters/histograms (duplicate-safe).
    _init_custom_metrics(settings.latency_buckets)

    # --- Step 1: Prometheus instrumentator (innermost of gateway group) ---
    # instrument() wraps the app; expose() adds the /metrics route.
    try:
        from prometheus_fastapi_instrumentator import Instrumentator

        instrumentator = Instrumentator(
            should_group_status_codes=True,
            should_instrument_requests_inprogress=False,
        )
        instrumentator.instrument(
            app,
            metric_namespace="shomer",
            latency_lowr_buckets=settings.latency_buckets,
            latency_highr_buckets=settings.latency_buckets,
        ).expose(app, endpoint=settings.metrics_endpoint)
    except Exception:
        log.error(
            "metrics_init_failed",
            note="Prometheus metrics disabled; /metrics endpoint will be absent",
        )

    # --- Step 2: rate limiter (custom middleware, fail-open aware) ---
    # We store the limiter on app.state so RateLimitMiddleware can access it.
    # The exception handler is registered for the case where endpoint-level
    # @limiter.limit decorators raise RateLimitExceeded (not used in MVP, but
    # correct to register for completeness).
    limiter = build_limiter(settings)
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)  # type: ignore[arg-type]
    app.add_middleware(RateLimitMiddleware)

    # --- Step 3: TraceIdMiddleware ---
    # Runs before SlowAPI on the request path so the 429 response carries trace_id.
    app.add_middleware(TraceIdMiddleware)

    # --- Step 3b: DeviceAuthMiddleware (S2) ---
    # Runs AFTER TraceIdMiddleware on the request path (trace_id is set when auth
    # resolves) but BEFORE the resource handler.  Registration order: added after
    # TraceIdMiddleware so it is further out in Starlette's reverse stack.
    #
    # Desired request-path execution order:
    #   Timeout → Size → TraceId → DeviceAuth → RateLimit → Prometheus → handler
    #
    # Registration order (first = innermost):
    #   Prometheus, RateLimit, TraceId, DeviceAuth (this step), Size, Timeout
    app.add_middleware(DeviceAuthMiddleware)

    # --- Step 4: RequestSizeMiddleware ---
    # Runs before TraceId on request path so it is outermost of those two.
    app.add_middleware(RequestSizeMiddleware, max_bytes=settings.max_body_bytes)

    # --- Step 5: RequestTimeoutMiddleware (outermost of gateway group) ---
    app.add_middleware(RequestTimeoutMiddleware, timeout_s=settings.client_recv_timeout_s)

    log.info(
        "gateway_registered",
        rate_limit=f"{settings.rate_limit_per_minute}/minute",
        max_body_bytes=settings.max_body_bytes,
        timeout_s=settings.client_recv_timeout_s,
        metrics_endpoint=settings.metrics_endpoint,
    )
