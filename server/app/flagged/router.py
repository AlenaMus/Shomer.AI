"""Parent review/react router — S4 parent API.

Exposes:
    GET  /v1/parent/alerts              — list flagged events (all the parent's children)
    GET  /v1/parent/alerts/{flag_id}    — single event detail
    POST /v1/parent/alerts/{flag_id}/react — acknowledge · label · severity
    GET  /v1/parent/labels/export       — export parent-labeled events (training bridge)

Auth:
    All endpoints require a parent token.  ``DeviceAuthMiddleware`` resolves the
    Bearer token → ``request.state.device_context``.  Each handler calls
    ``_require_parent`` which raises 401 (missing) or 403 (wrong role).

Authorization:
    Resource-level ownership check ("does this parent own this child/flag?") lives
    HERE, consistent with the S2 pattern.  Middleware stays content-blind.

Design notes:
    - Routers depend on ``app.state.flagged`` (FlaggedEventStore Protocol) and
      ``app.state.identity`` (IdentityStore Protocol).  No concrete adapters here.
    - The ``severity`` react action uses the new ``set_parent_severity`` method
      added to the Protocol in S4.
    - ``GET /v1/parent/labels/export`` returns only events where
      ``parent_label is not null``.  PII-scrub / retention (S5) must be applied
      before any real data export.

Reference: linked-yawning-sifakis.md §S4 "Parent review/react".
"""

from __future__ import annotations

from typing import Literal

import structlog
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from ..schemas import Severity

log = structlog.get_logger("shomer.parent.review")

router = APIRouter(prefix="/v1/parent", tags=["parent-review"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class FlaggedEventOut(BaseModel):
    """Wire-format representation of a FlaggedEvent for parent API consumers.

    Maps the frozen ``FlaggedEvent`` dataclass to a Pydantic response model.
    All fields the dashboard needs are included; ``parent_label``,
    ``parent_severity``, and ``acknowledged_at`` are nullable.

    ``confidence`` is the classifier confidence (0.0–1.0) persisted when the
    event was recorded.  It is ``None`` for events recorded before this field
    was added (graceful degradation).
    """

    flag_id: str
    child_id: str
    created_at: float
    app_package: str
    direction: str
    label: str
    severity: str
    quote: str
    explanation: str
    source: str
    status: str
    confidence: float | None = None
    parent_label: str | None = None
    parent_severity: str | None = None
    acknowledged_at: float | None = None


class FlaggedEventDetailOut(FlaggedEventOut):
    """Extended detail model for GET /v1/parent/alerts/{flag_id}.

    Adds Context-Agent fields that are only available on the per-event detail
    view (joined from ``agent_traces`` by ``trace_id``).  All CA fields are
    ``None`` when no CA ran for this event.
    """

    # Context-Agent detail (null when CA did not run)
    context_used: bool | None = None        # True if CA called read_history
    is_real_threat: bool | None = None      # CA's verdict
    ca_severity: str | None = None          # CA's severity assessment
    ca_reasoning: str | None = None         # CA's explanation / reasoning_trace
    ca_model: str | None = None             # model_used by the CA


class ReactRequest(BaseModel):
    """Body for POST /v1/parent/alerts/{flag_id}/react.

    Exactly one action per call.  Validation rules:
      - ``"label"`` requires ``label`` field (422 otherwise).
      - ``"severity"`` requires ``severity`` field (422 otherwise).
      - ``"acknowledge"`` ignores ``label`` / ``severity``.
    """

    action: Literal["acknowledge", "label", "severity"]
    label: Literal["offensive", "not_offensive"] | None = Field(
        default=None,
        description="Human verdict ('label' action only). Stored as DictaBERT training data.",
    )
    severity: Severity | None = Field(
        default=None,
        description="Parent severity override ('severity' action only).",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_parent(request: Request):
    """Extract DeviceContext; raise 401/403 if missing or not parent role."""
    ctx = getattr(request.state, "device_context", None)
    if ctx is None:
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid Authorization header",
        )
    if ctx.role != "parent":
        raise HTTPException(
            status_code=403,
            detail="Parent credentials required",
        )
    return ctx


def _event_to_out(event) -> FlaggedEventOut:
    """Convert a FlaggedEvent dataclass to the wire-format response model."""
    return FlaggedEventOut(
        flag_id=event.flag_id,
        child_id=event.child_id,
        created_at=event.created_at,
        app_package=event.app_package,
        direction=event.direction,
        label=event.label,
        severity=event.severity,
        quote=event.quote,
        explanation=event.explanation,
        source=event.source,
        status=event.status,
        confidence=event.confidence,
        parent_label=event.parent_label,
        parent_severity=event.parent_severity,
        acknowledged_at=event.acknowledged_at,
    )


def _event_to_detail(event, ca_row: dict | None) -> FlaggedEventDetailOut:
    """Convert a FlaggedEvent to the extended detail model including CA fields."""
    base = _event_to_out(event)
    detail = FlaggedEventDetailOut(**base.model_dump())

    if ca_row is not None:
        import json as _json

        tools_raw = ca_row.get("tools_called_json") or "[]"
        try:
            tools: list = _json.loads(tools_raw)
        except Exception:  # noqa: BLE001
            tools = []

        tool_names = [
            t.get("name") if isinstance(t, dict) else str(t) for t in tools
        ]
        detail.context_used = "read_history" in tool_names
        detail.is_real_threat = bool(ca_row.get("is_real_threat"))
        detail.ca_severity = ca_row.get("severity")
        # Prefer reasoning_trace when non-empty; fall back to explanation.
        reasoning = (ca_row.get("reasoning_trace") or "").strip()
        explanation = (ca_row.get("explanation") or "").strip()
        detail.ca_reasoning = reasoning if reasoning else explanation or None
        detail.ca_model = ca_row.get("model_used")

    return detail


async def _owned_child_ids(request: Request, parent_id: str) -> set[str]:
    """Return the set of child_ids owned by this parent (empty if none)."""
    identity = request.app.state.identity
    children = await identity.list_children(parent_id)
    return {c.child_id for c in children}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/alerts",
    response_model=list[FlaggedEventOut],
    summary="List flagged events for the authenticated parent's children",
)
async def list_alerts(
    request: Request,
    child_id: str | None = Query(
        default=None,
        description="Filter to a specific child_id. If omitted, aggregates across all children.",
    ),
    since: float | None = Query(
        default=None,
        description="Only return events with created_at >= since (epoch seconds).",
    ),
    status: str | None = Query(
        default=None,
        description="Filter by FlaggedStatus (alerted|review_needed|acknowledged|labeled).",
    ),
    include_acked: bool = Query(
        default=False,
        description="When true, include acknowledged/labeled events.",
    ),
    limit: int = Query(
        default=50,
        ge=1,
        le=200,
        description="Maximum number of events to return (capped at 200).",
    ),
) -> list[FlaggedEventOut]:
    """Return flagged events for the parent's children, newest-first.

    If ``child_id`` is specified, only that child's events are returned (403
    if the child is not owned by this parent).  If omitted, all children's
    events are aggregated, sorted newest-first, and capped at ``limit``.

    The optional ``status`` query parameter post-filters by FlaggedStatus after
    fetching (not pushed to the store query — keeps the store interface minimal).
    """
    ctx = _require_parent(request)
    flagged = request.app.state.flagged

    owned_ids = await _owned_child_ids(request, ctx.parent_id)

    if child_id is not None:
        # Single-child view: verify ownership first.
        if child_id not in owned_ids:
            raise HTTPException(
                status_code=403,
                detail=f"child_id '{child_id}' is not owned by this parent",
            )
        target_ids = [child_id]
    else:
        target_ids = list(owned_ids)

    # Fetch from each child; merge newest-first.
    # Bug A fix: push the ``status`` filter directly to the store query so
    # acknowledged/labeled events are fetched correctly.  When ``status`` is
    # provided, the store-level ``include_acked`` flag is forced to True to
    # avoid the acknowledged/labeled exclusion clause silently hiding those
    # rows (the status-exact-match clause in the store takes over).
    effective_include_acked = include_acked or (status is not None)

    all_events = []
    for cid in target_ids:
        events = await flagged.list_for_child(
            cid,
            since=since,
            limit=limit,
            include_acked=effective_include_acked,
            status=status,
        )
        all_events.extend(events)

    # Sort merged list newest-first, then cap.
    all_events.sort(key=lambda e: e.created_at, reverse=True)
    all_events = all_events[:limit]

    log.info(
        "parent.alerts.listed",
        parent_id=ctx.parent_id,
        child_ids=target_ids,
        count=len(all_events),
    )
    return [_event_to_out(e) for e in all_events]


@router.get(
    "/alerts/{flag_id}",
    response_model=FlaggedEventDetailOut,
    summary="Get a single flagged event by flag_id (includes CA reasoning when available)",
)
async def get_alert(flag_id: str, request: Request) -> FlaggedEventDetailOut:
    """Return a single flagged event with optional Context-Agent detail.

    Returns 404 if the flag_id does not exist OR if it belongs to a child not
    owned by this parent (ownership-blind 404 to avoid enumeration attacks).

    The ``context_used``, ``is_real_threat``, ``ca_severity``, ``ca_reasoning``,
    and ``ca_model`` fields are populated when the Context Agent ran for this
    event (joined from ``agent_traces`` via ``trace_id``).  They are ``None``
    for frontline-only events.
    """
    ctx = _require_parent(request)
    flagged = request.app.state.flagged

    event = await flagged.get(flag_id)
    if event is None:
        raise HTTPException(status_code=404, detail=f"flag_id '{flag_id}' not found")

    # Verify ownership.
    owned_ids = await _owned_child_ids(request, ctx.parent_id)
    if event.child_id not in owned_ids:
        # Return 404 rather than 403 to avoid enumerating flag IDs across parents.
        raise HTTPException(status_code=404, detail=f"flag_id '{flag_id}' not found")

    # Bug C fix: join the CA trace from the audit store (best-effort — if
    # the audit store doesn't have ``read_agent_trace_for``, degrade to None).
    ca_row: dict | None = None
    audit_store = getattr(request.app.state, "audit_store", None)
    if audit_store is not None and hasattr(audit_store, "read_agent_trace_for"):
        try:
            ca_row = await audit_store.read_agent_trace_for(event.trace_id)
        except Exception as exc:  # noqa: BLE001 — best-effort
            log.warning(
                "parent.alert.ca_trace_lookup_failed",
                flag_id=flag_id,
                trace_id=event.trace_id,
                error=str(exc),
            )

    log.info(
        "parent.alert.retrieved",
        parent_id=ctx.parent_id,
        flag_id=flag_id,
        child_id=event.child_id,
        has_ca_trace=ca_row is not None,
    )
    return _event_to_detail(event, ca_row)


@router.post(
    "/alerts/{flag_id}/react",
    response_model=FlaggedEventOut,
    summary="Apply a parent reaction to a flagged event",
)
async def react_to_alert(
    flag_id: str,
    body: ReactRequest,
    request: Request,
) -> FlaggedEventOut:
    """Apply a parent reaction to a flagged event.

    Actions:
      - ``acknowledge`` — mark event seen/handled; sets status "acknowledged".
      - ``label``       — requires ``label`` field; stores human verdict in
                          ``parent_label``; sets status "labeled".  This label
                          becomes DictaBERT training data (see ai-researcher-developer).
      - ``severity``    — requires ``severity`` field; stores the parent's
                          perceived severity in ``parent_severity``; sets status
                          "labeled".

    Returns the updated FlaggedEventOut on success.
    Returns 404 if flag not found or not owned by this parent.
    Returns 422 if the action/field combination is invalid.
    """
    ctx = _require_parent(request)
    flagged = request.app.state.flagged

    # Validate action-specific required fields BEFORE touching the store.
    if body.action == "label" and body.label is None:
        raise HTTPException(
            status_code=422,
            detail="'label' action requires the 'label' field to be set",
        )
    if body.action == "severity" and body.severity is None:
        raise HTTPException(
            status_code=422,
            detail="'severity' action requires the 'severity' field to be set",
        )

    # Fetch + verify ownership.
    event = await flagged.get(flag_id)
    if event is None:
        raise HTTPException(status_code=404, detail=f"flag_id '{flag_id}' not found")

    owned_ids = await _owned_child_ids(request, ctx.parent_id)
    if event.child_id not in owned_ids:
        raise HTTPException(status_code=404, detail=f"flag_id '{flag_id}' not found")

    # Dispatch the mutation.
    if body.action == "acknowledge":
        updated = await flagged.acknowledge(flag_id, ctx.parent_id)
    elif body.action == "label":
        updated = await flagged.set_parent_label(
            flag_id,
            label=body.label,
            severity=body.severity,
        )
    else:  # "severity"
        updated = await flagged.set_parent_severity(flag_id, severity=body.severity)

    if not updated:
        # Should not happen since we just fetched the event, but be defensive.
        raise HTTPException(
            status_code=409,
            detail=f"flag_id '{flag_id}' could not be updated (concurrent modification?)",
        )

    # Return the fresh state.
    refreshed = await flagged.get(flag_id)
    if refreshed is None:  # Paranoid guard; practically unreachable.
        raise HTTPException(status_code=500, detail="Failed to retrieve updated event")

    log.info(
        "parent.alert.reacted",
        parent_id=ctx.parent_id,
        flag_id=flag_id,
        action=body.action,
        label=body.label,
        severity=body.severity,
        new_status=refreshed.status,
    )
    return _event_to_out(refreshed)


@router.get(
    "/labels/export",
    response_model=list[dict],
    summary="Export parent-labeled events as training data (dev / ai-researcher-developer bridge)",
)
async def export_labels(request: Request) -> list[dict]:
    """Return all events where the parent has applied a human verdict label.

    The returned records contain the fields needed by the DictaBERT training
    pipeline:
        quote           — truncated message text (≤200 chars)
        label           — system classifier label
        parent_label    — parent human verdict ("offensive" | "not_offensive")
        severity        — system severity
        parent_severity — parent severity override (if set)
        app_package     — source app
        direction       — "inbound" | "outbound"
        created_at      — epoch seconds

    NOTE: PII-scrub (G-06) and retention policies (S5) apply before any real
    data export.  This endpoint is intended for internal/dev use to bridge to
    the ai-researcher-developer owner of the training pipeline.  Do not expose
    to untrusted clients without S5 hardening.
    """
    ctx = _require_parent(request)
    flagged = request.app.state.flagged

    owned_ids = await _owned_child_ids(request, ctx.parent_id)

    results = []
    for cid in owned_ids:
        # include_acked=True to capture labeled events (status="labeled").
        events = await flagged.list_for_child(cid, limit=1000, include_acked=True)
        for e in events:
            if e.parent_label is not None:
                results.append(
                    {
                        "quote": e.quote,
                        "label": e.label,
                        "parent_label": e.parent_label,
                        "severity": e.severity,
                        "parent_severity": e.parent_severity,
                        "app_package": e.app_package,
                        "direction": e.direction,
                        "created_at": e.created_at,
                    }
                )

    log.info(
        "parent.labels.exported",
        parent_id=ctx.parent_id,
        count=len(results),
    )
    return results


# ---------------------------------------------------------------------------
# Registration function
# ---------------------------------------------------------------------------


def register_parent_review(app) -> None:
    """Register the parent review/react router on the FastAPI app.

    Called from ``main.py`` after ``register_gateway()`` so Gatekeeper
    middleware wraps these endpoints too.
    """
    app.include_router(router)
