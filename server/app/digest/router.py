"""FastAPI router for digest endpoints (S3).

Exposes:
    GET  /v1/parent/digests/{date}      — parent-authed; returns digests for that date
    POST /internal/digest/run           — force-trigger run_once (guarded by DIGEST_ALLOW_MANUAL_TRIGGER)

Auth design:
  - ``GET /v1/parent/digests/{date}`` requires a parent token (device_context.role == "parent").
    The parent may only read their own children's digests.
  - ``POST /internal/digest/run`` is NOT on the auth allowlist so it gets through
    the auth middleware; it is guarded internally by ``DIGEST_ALLOW_MANUAL_TRIGGER``.
    In production, set ``DIGEST_ALLOW_MANUAL_TRIGGER=false`` to disable it.

Reference: linked-yawning-sifakis.md §S3.
"""

from __future__ import annotations

import time

import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from .protocol import ChildDigest, DigestEntry
from .settings import DigestSettings

log = structlog.get_logger("shomer.digest.router")

router = APIRouter(prefix="/v1", tags=["digest"])
internal_router = APIRouter(prefix="/internal", tags=["internal"])


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class DigestEntryOut(BaseModel):
    flag_id: str
    app_package: str
    direction: str
    label: str
    severity: str
    quote: str
    status: str
    created_at: float


class ChildDigestOut(BaseModel):
    child_id: str
    parent_id: str
    date: str
    generated_at: float
    total_flagged: int
    review_needed: int
    by_severity: dict[str, int]
    by_label: dict[str, int]
    entries: list[DigestEntryOut]


class DigestRunResponse(BaseModel):
    digests_built: int
    child_ids: list[str]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_parent_context(request: Request):
    """Extract DeviceContext from request.state; raise 401/403 if not a parent."""
    ctx = getattr(request.state, "device_context", None)
    if ctx is None:
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    if ctx.role != "parent":
        raise HTTPException(status_code=403, detail="Parent credentials required")
    return ctx


def _to_out(digest: ChildDigest) -> ChildDigestOut:
    return ChildDigestOut(
        child_id=digest.child_id,
        parent_id=digest.parent_id,
        date=digest.date,
        generated_at=digest.generated_at,
        total_flagged=digest.total_flagged,
        review_needed=digest.review_needed,
        by_severity=digest.by_severity,
        by_label=digest.by_label,
        entries=[
            DigestEntryOut(
                flag_id=e.flag_id,
                app_package=e.app_package,
                direction=e.direction,
                label=e.label,
                severity=e.severity,
                quote=e.quote,
                status=e.status,
                created_at=e.created_at,
            )
            for e in digest.entries
        ],
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/parent/digests/{date}",
    response_model=list[ChildDigestOut],
    summary="Return the authenticated parent's children's digests for a given date",
)
async def get_digests(date: str, request: Request, child_id: str | None = None) -> list[ChildDigestOut]:
    """Return all built digests for the given date, filtered to the parent's own children.

    ``date`` must be ``"YYYY-MM-DD"`` (server-local date, matches the digest's
    ``date`` field).  If ``?child_id=`` is given, returns only that child's digest.
    Returns 404 if no digests are found.

    The parent can ONLY see their own children's digests (enforced by identity lookup).
    """
    ctx = _require_parent_context(request)
    identity = request.app.state.identity
    digest_store = request.app.state.digest_store

    # Enumerate the parent's children.
    children = await identity.list_children(parent_id=ctx.parent_id)
    child_ids = {c.child_id for c in children}

    if child_id is not None:
        # Scope to the requested child_id — reject if not owned by this parent.
        if child_id not in child_ids:
            raise HTTPException(
                status_code=403,
                detail=f"child_id '{child_id}' does not belong to this parent",
            )
        child_ids = {child_id}

    # Fetch digests for each child.
    results: list[ChildDigestOut] = []
    for cid in child_ids:
        digest = await digest_store.get(cid, date)
        if digest is not None:
            results.append(_to_out(digest))

    if not results:
        raise HTTPException(
            status_code=404,
            detail=f"No digests found for date '{date}' (parent {ctx.parent_id})",
        )

    return results


@internal_router.post(
    "/digest/run",
    response_model=DigestRunResponse,
    summary="Force-trigger a digest run (dev/demo only; disabled by DIGEST_ALLOW_MANUAL_TRIGGER=false)",
    status_code=200,
)
async def force_digest_run(request: Request) -> DigestRunResponse:
    """Force-trigger ``digest_scheduler.run_once(now=time.time())``.

    Guarded by ``DIGEST_ALLOW_MANUAL_TRIGGER`` (default True for MVP).
    Only callable when enabled; returns 403 otherwise.

    Useful for:
      - Integration tests (via TestClient)
      - Demo: seed events, call this, verify the parent receives a digest
    """
    settings = DigestSettings()
    if not settings.allow_manual_trigger:
        raise HTTPException(
            status_code=403,
            detail="Manual digest trigger is disabled (DIGEST_ALLOW_MANUAL_TRIGGER=false)",
        )

    scheduler = getattr(request.app.state, "digest_scheduler", None)
    if scheduler is None:
        raise HTTPException(
            status_code=503,
            detail="DigestScheduler is not configured (DIGEST_ENABLED=false?)",
        )

    now = time.time()
    try:
        digests = await scheduler.run_once(now=now)
    except Exception as exc:
        log.error("digest.force_run_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=f"Digest run failed: {exc}") from exc

    log.info(
        "digest.force_run_complete",
        now=now,
        digests_built=len(digests),
    )
    return DigestRunResponse(
        digests_built=len(digests),
        child_ids=[d.child_id for d in digests],
    )


# ---------------------------------------------------------------------------
# Registration function
# ---------------------------------------------------------------------------


def register_digest(app) -> None:
    """Register digest routers on the FastAPI app.

    Called from ``main.py`` after other routers are registered.
    ``/v1/parent/digests/{date}`` is NOT on the auth allowlist so it goes through
    DeviceAuthMiddleware (correct — it requires parent credentials).
    ``/internal/digest/run`` is NOT on the auth allowlist either — access is
    guarded by ``DIGEST_ALLOW_MANUAL_TRIGGER`` internally.
    """
    app.include_router(router)
    app.include_router(internal_router)
