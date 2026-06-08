"""FastAPI router for the Monitor ingest endpoint.

Exposes:
    POST /v1/monitor/events → MonitorBatchResponse

Auth (S2): this endpoint requires a valid child device token.
  - The DeviceAuthMiddleware (gateway.py) resolves the Bearer token and sets
    ``request.state.device_context``.
  - This router enforces: device_context must be present with role="child", and
    ``batch.child_id`` must equal ``device_context.child_id``.
  - 401 on missing/invalid token; 403 on child_id mismatch.

Rationale for enforcing auth in the router (not middleware): the child_id match
is a resource-level authorization check that requires knowledge of the request
body (``batch.child_id``), which is not available to the middleware.  The
middleware stays content-blind (it only resolves the token); the router enforces
the identity + ownership constraint co-located with the resource.

The router is registered in ``main.py`` via ``register_monitor(app)`` — the
same pattern as ``register_gateway`` in ``gateway.py``.

Trace-id derivation reuses the same ``X-Trace-Id`` header convention as the
rest of the server.
"""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, HTTPException, Request

from ..schemas import MonitorBatchRequest, MonitorBatchResponse

log = structlog.get_logger("shomer.monitor.router")

router = APIRouter(prefix="/v1/monitor", tags=["monitor"])


def _enforce_child_auth(request: Request, batch: MonitorBatchRequest) -> None:
    """Enforce S2 auth on the monitor ingest endpoint.

    Rules:
      1. ``request.state.device_context`` must be set (→ 401 if not).
      2. ``device_context.role`` must be "child" (→ 403 otherwise).
      3. ``device_context.child_id`` must equal ``batch.child_id`` (→ 403 on mismatch).

    When no identity store is configured (``app.state.identity`` is None) the
    check is skipped — this preserves backward compatibility with tests that
    predate S2 and do not seed an identity store.
    """
    # If no identity store is wired, skip (graceful degradation for pre-S2 tests).
    identity = getattr(getattr(request.app, "state", None), "identity", None)
    if identity is None:
        return

    ctx = getattr(request.state, "device_context", None)
    if ctx is None:
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid Authorization header; device token required",
        )
    if ctx.role != "child":
        raise HTTPException(
            status_code=403,
            detail="Only child-role device tokens may post to this endpoint",
        )
    if ctx.child_id != batch.child_id:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Token is for child '{ctx.child_id}' but batch.child_id is "
                f"'{batch.child_id}'; a device may only ingest its own events"
            ),
        )


@router.post(
    "/events",
    response_model=MonitorBatchResponse,
    status_code=202,
    summary="Submit a batch of captured monitor events for classification",
)
async def ingest_events(
    batch: MonitorBatchRequest,
    request: Request,
) -> MonitorBatchResponse:
    """Accept a batch of child-device monitor events.

    Auth (S2): requires ``Authorization: Bearer <device-token>`` with role="child"
    matching ``batch.child_id``.  Returns 401 on missing token, 403 on mismatch.

    Each event is deduped by (child_id, text_hash), then run through the
    existing classification pipeline.  Offensive / borderline events are
    recorded to the FlaggedEventStore for parent review.

    Returns HTTP 202 (Accepted) — the server accepted the batch; processing
    is synchronous within this request but the result is advisory (the device
    does not need to retry based on individual ack statuses).
    """
    # S2 authorization: child token must match the batch's child_id.
    _enforce_child_auth(request, batch)

    # Validate child_id is non-empty (belt-and-suspenders; Pydantic validates
    # max_length, but an empty string after strip would slip through).
    if not batch.child_id.strip():
        raise HTTPException(status_code=400, detail="child_id must be non-empty")

    # Derive trace-id from incoming header or generate one.
    trace_id = request.headers.get("X-Trace-Id") or str(uuid.uuid4())

    # Ensure request.state.audit exists (required by _run_pipeline for audit dict).
    if not hasattr(request.state, "audit") or request.state.audit is None:
        request.state.audit = {}

    log.info(
        "monitor.batch_received",
        trace_id=trace_id,
        child_id=batch.child_id,
        session_id=batch.session_id,
        event_count=len(batch.events),
    )

    monitor = request.app.state.monitor
    response = await monitor.ingest_batch(request, batch, trace_id=trace_id)
    return response


def register_monitor(app) -> None:
    """Register the monitor router on the FastAPI app.

    Called from ``main.py`` after ``register_gateway()`` so Gatekeeper
    middleware (trace-id, rate-limit, size) wraps this endpoint too.
    """
    app.include_router(router)
