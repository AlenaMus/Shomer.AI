"""FastAPI router for identity bootstrap + pairing endpoints.

Exposes:
    POST /v1/parent/register   — mint parent_id + parent token (MVP bootstrap, NO auth)
    POST /v1/parent/login      — exchange email+password for parent token
    POST /v1/parent/children   — issue a child record (parent-authed)
    POST /v1/parent/pairing-code — issue an OTP for a child device (parent-authed)
    POST /v1/pair              — child device redeems OTP → device token (UNAUTHED bootstrap)
    GET  /v1/parent/children   — list children (parent-authed)

Auth design:
  - ``/v1/parent/register``, ``/v1/parent/login``, and ``/v1/pair`` are on the
    Gatekeeper ALLOWLIST (they bootstrap auth, so they cannot require a token themselves).
  - Parent-authed endpoints extract ``Authorization: Bearer <parent_token>`` from
    the request state's ``device_context`` (populated by the auth middleware).  If
    the resolved DeviceContext has role != "parent", the handler returns 403.

Email identifier:
  - ``email`` (not ``username``) is the login credential.  Validated with a
    pragmatic regex; stored + compared lowercase.
  - Duplicate email → 409 ``{"detail": "email already registered"}``.
  - Bad login (unknown email or wrong password) → 401 ``{"detail": "invalid email
    or password"}`` — same body in both cases to prevent enumeration.

OTP email delivery (fire-and-forget):
  - ``POST /v1/parent/register`` (when child_name is given) and
    ``POST /v1/parent/pairing-code`` call ``app.state.mailer.send(...)`` if the
    parent has a stored email.  Email failure logs a warning but does NOT fail
    the request.
"""

from __future__ import annotations

import asyncio
import re

import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

log = structlog.get_logger("shomer.identity.router")

router = APIRouter(prefix="/v1", tags=["identity"])

# ---------------------------------------------------------------------------
# Email validation
# ---------------------------------------------------------------------------

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _validate_email(v: str) -> str:
    """Lower-case + pragmatic format check; raises ValueError on bad format."""
    v = v.strip().lower()
    if not _EMAIL_RE.match(v):
        raise ValueError("invalid email format")
    return v


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class ParentRegisterRequest(BaseModel):
    display_name: str = Field(default="", max_length=128)
    email: str | None = Field(default=None, max_length=256)
    password: str | None = Field(default=None, min_length=8, max_length=256)
    child_name: str | None = Field(
        default=None,
        max_length=128,
        description=(
            "Optional: if provided, a child record is issued and a pairing code "
            "emailed to the parent in a single request.  Requires email+password."
        ),
    )

    @field_validator("email")
    @classmethod
    def _email_format(cls, v: str | None) -> str | None:
        if v is not None:
            return _validate_email(v)
        return v


class ParentRegisterResponse(BaseModel):
    parent_id: str
    parent_token: str         # opaque; treat as a secret — do NOT log
    display_name: str = ""
    email: str | None = None  # echoed back when provided
    # Populated only when child_name was in the request:
    child_id: str | None = None
    pairing_code: str | None = None
    pairing_expires_in_s: int | None = None
    # NOTE: pairing_code is included in the response for MVP/demo convenience.
    # The email is the primary channel; the response copy lets the parent paste
    # the code manually during testing without needing to check their inbox.


class ParentLoginRequest(BaseModel):
    email: str = Field(..., max_length=256)
    password: str = Field(..., min_length=1, max_length=256)

    @field_validator("email")
    @classmethod
    def _email_format(cls, v: str) -> str:
        return _validate_email(v)


class ParentLoginResponse(BaseModel):
    parent_id: str
    parent_token: str
    display_name: str
    email: str


class IssueChildRequest(BaseModel):
    display_name: str = Field(..., max_length=128, description="Display name only — no PII")


class IssueChildResponse(BaseModel):
    child_id: str
    parent_id: str
    display_name: str
    created_at: float


class ChildInfo(BaseModel):
    child_id: str
    display_name: str
    created_at: float


class CreatePairingCodeRequest(BaseModel):
    child_id: str = Field(..., max_length=128)


class CreatePairingCodeResponse(BaseModel):
    code: str
    child_id: str
    expires_at: float


class RedeemPairingCodeRequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=8)
    device_fingerprint: str = Field(default="", max_length=256)


class RedeemPairingCodeResponse(BaseModel):
    device_token: str
    child_id: str
    role: str


class SetFcmTokenRequest(BaseModel):
    fcm_token: str = Field(..., min_length=1, max_length=512, description="FCM registration token")


class SetFcmTokenResponse(BaseModel):
    ok: bool


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


def _require_any_device_context(request: Request):
    """Extract DeviceContext from request.state; raise 401 if not authenticated."""
    ctx = getattr(request.state, "device_context", None)
    if ctx is None:
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    return ctx


def _pairing_code_email_body(code: str, child_name: str, expires_in_min: int) -> tuple[str, str]:
    """Return (subject, body) for the pairing-code OTP email (Hebrew + Shomer.AI Latin)."""
    subject = "Shomer.AI — קוד התאמה"
    body = (
        f"שלום,\n\n"
        f"להתחברות של מכשיר הילד/ה שלך ('{child_name}') לאפליקציית Shomer.AI,\n"
        f"הזן/י את הקוד הבא באפליקציית Shomer המותקנת על מכשיר הילד:\n\n"
        f"    {code}\n\n"
        f"הקוד תקף ל-{expires_in_min} דקות ולשימוש חד-פעמי בלבד.\n\n"
        f"אם לא ביקשת קוד זה, ניתן להתעלם מהמייל הזה.\n\n"
        f"Shomer.AI"
    )
    return subject, body


async def _fire_and_forget_email(
    request: Request,
    parent_id: str,
    subject: str,
    body: str,
) -> None:
    """Send an OTP email if the parent has a stored email — fire-and-forget.

    Failures are logged as warnings; they never propagate to the caller.
    """
    try:
        email_address = await request.app.state.identity.get_parent_email(parent_id)
        if not email_address:
            return
        mailer = getattr(request.app.state, "mailer", None)
        if mailer is None:
            log.warning("mailer.not_configured", parent_id=parent_id)
            return
        ok = await mailer.send(to=email_address, subject=subject, body=body)
        if not ok:
            log.warning("mailer.send_failed", parent_id=parent_id, subject=subject)
    except Exception as exc:  # noqa: BLE001 — email must never fail the request
        log.warning("mailer.error", parent_id=parent_id, error=str(exc))


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "/parent/register",
    response_model=ParentRegisterResponse,
    summary="Register a new parent account (MVP bootstrap — no prior auth needed)",
    status_code=201,
)
async def register_parent(body: ParentRegisterRequest, request: Request) -> ParentRegisterResponse:
    """Mint a parent_id and a long-lived parent token.

    This endpoint is on the auth-middleware ALLOWLIST (no token required).
    The returned ``parent_token`` is the opaque credential for all parent-authed
    endpoints.

    Optionally accepts ``email`` + ``password`` for web-login (the dashboard).
    If ``email`` is given, ``password`` is also required.
    Display-name-only registration (Android client) remains fully supported.

    Optional ``child_name``: if provided (requires email+password), a child record
    is also issued and a pairing code is generated in the same call.  The pairing
    code is included in the response AND emailed to the parent.
    """
    # Cross-field validation: email requires password (and vice-versa for child_name).
    if body.email is not None and not body.password:
        raise HTTPException(
            status_code=422,
            detail="password is required when email is provided",
        )
    if body.child_name is not None and body.email is None:
        raise HTTPException(
            status_code=422,
            detail="email+password are required when child_name is provided",
        )

    identity = request.app.state.identity
    try:
        parent_id, token = await identity.register_parent(
            display_name=body.display_name,
            email=body.email,
            password=body.password,
        )
    except ValueError as exc:
        if "email_taken" in str(exc):
            raise HTTPException(status_code=409, detail="email already registered")
        raise

    log.info(
        "identity.parent_registered_endpoint",
        parent_id=parent_id,
        token_prefix=token[:8],
        has_email=body.email is not None,
    )

    # Optional: issue child + pairing code in one call.
    child_id: str | None = None
    pairing_code: str | None = None
    pairing_expires_in_s: int | None = None

    if body.child_name is not None:
        child_record = await identity.issue_child(
            parent_id=parent_id,
            display_name=body.child_name,
        )
        child_id = child_record.child_id
        pc = await identity.create_pairing_code(
            parent_id=parent_id,
            child_id=child_id,
        )
        pairing_code = pc.code
        import time as _time
        pairing_expires_in_s = int(pc.expires_at - _time.time())
        log.info(
            "identity.register_with_child",
            parent_id=parent_id,
            child_id=child_id,
        )

        # Fire-and-forget OTP email (non-blocking; failure does NOT fail the response).
        from .settings import IdentitySettings as _ISettings
        _ttl_min = _ISettings().pairing_code_ttl_s // 60
        subject, email_body = _pairing_code_email_body(
            code=pc.code,
            child_name=body.child_name,
            expires_in_min=_ttl_min,
        )
        asyncio.create_task(
            _fire_and_forget_email(request, parent_id, subject, email_body)
        )

    return ParentRegisterResponse(
        parent_id=parent_id,
        parent_token=token,
        display_name=body.display_name,
        email=body.email,
        child_id=child_id,
        pairing_code=pairing_code,
        pairing_expires_in_s=pairing_expires_in_s,
    )


@router.post(
    "/parent/login",
    response_model=ParentLoginResponse,
    summary="Authenticate a parent with email + password",
)
async def login_parent(body: ParentLoginRequest, request: Request) -> ParentLoginResponse:
    """Exchange email + password for the parent's opaque token.

    Bad email OR bad password both return 401 with the same message to
    prevent user enumeration.  The returned ``parent_token`` is identical to
    the one returned at registration and works with all existing parent endpoints.

    This endpoint is on the auth-middleware ALLOWLIST (it issues auth, so it
    cannot require a token itself).
    """
    identity = request.app.state.identity
    auth = await identity.authenticate_parent_credentials(
        email=body.email,
        password=body.password,
    )
    if auth is None:
        raise HTTPException(status_code=401, detail="invalid email or password")
    log.info(
        "identity.parent_login_endpoint",
        parent_id=auth.parent_id,
        token_prefix=auth.parent_token[:8],
    )
    return ParentLoginResponse(
        parent_id=auth.parent_id,
        parent_token=auth.parent_token,
        display_name=auth.display_name,
        email=auth.email or body.email,
    )


@router.post(
    "/parent/children",
    response_model=IssueChildResponse,
    summary="Register a new child under the authenticated parent",
    status_code=201,
)
async def issue_child(body: IssueChildRequest, request: Request) -> IssueChildResponse:
    """Mint a new child_id linked to the authenticated parent.

    Requires a valid parent token in ``Authorization: Bearer <token>``.
    The returned ``child_id`` is an opaque UUID — no PII is stored in it.
    """
    ctx = _require_parent_context(request)
    identity = request.app.state.identity
    record = await identity.issue_child(
        parent_id=ctx.parent_id,
        display_name=body.display_name,
    )
    log.info(
        "identity.child_issued_endpoint",
        child_id=record.child_id,
        parent_id=ctx.parent_id,
    )
    return IssueChildResponse(
        child_id=record.child_id,
        parent_id=record.parent_id,
        display_name=record.display_name,
        created_at=record.created_at,
    )


@router.get(
    "/parent/children",
    response_model=list[ChildInfo],
    summary="List children registered under the authenticated parent",
)
async def list_children(request: Request) -> list[ChildInfo]:
    """Return all children registered under the authenticated parent."""
    ctx = _require_parent_context(request)
    identity = request.app.state.identity
    records = await identity.list_children(parent_id=ctx.parent_id)
    return [
        ChildInfo(
            child_id=r.child_id,
            display_name=r.display_name,
            created_at=r.created_at,
        )
        for r in records
    ]


@router.post(
    "/parent/pairing-code",
    response_model=CreatePairingCodeResponse,
    summary="Issue a short-lived OTP for a child device to redeem",
    status_code=201,
)
async def create_pairing_code(
    body: CreatePairingCodeRequest, request: Request
) -> CreatePairingCodeResponse:
    """Issue a 6-digit OTP that the child device uses to claim its device token.

    Requires a valid parent token.  The code is valid for ``IDENTITY_PAIRING_CODE_TTL_S``
    seconds (default 10 min) and is single-use.

    If the parent has a stored email, the OTP is also emailed (fire-and-forget).
    A mailer failure does NOT fail this request — only a warning is logged.
    """
    ctx = _require_parent_context(request)
    identity = request.app.state.identity

    # Verify the requested child belongs to this parent.
    children = await identity.list_children(parent_id=ctx.parent_id)
    known_ids = {c.child_id for c in children}
    if body.child_id not in known_ids:
        raise HTTPException(
            status_code=404,
            detail=f"child_id '{body.child_id}' not found under this parent",
        )

    pc = await identity.create_pairing_code(
        parent_id=ctx.parent_id,
        child_id=body.child_id,
    )
    log.info(
        "identity.pairing_code_issued_endpoint",
        child_id=pc.child_id,
        parent_id=ctx.parent_id,
    )

    # Fire-and-forget OTP email if the parent has a stored email.
    child_name = next((c.display_name for c in children if c.child_id == body.child_id), "")
    from .settings import IdentitySettings as _ISettings
    _ttl_min = _ISettings().pairing_code_ttl_s // 60
    subject, email_body = _pairing_code_email_body(
        code=pc.code,
        child_name=child_name,
        expires_in_min=_ttl_min,
    )
    asyncio.create_task(
        _fire_and_forget_email(request, ctx.parent_id, subject, email_body)
    )

    return CreatePairingCodeResponse(
        code=pc.code,
        child_id=pc.child_id,
        expires_at=pc.expires_at,
    )


@router.post(
    "/pair",
    response_model=RedeemPairingCodeResponse,
    summary="Child device redeems a pairing OTP to obtain a long-lived device token",
)
async def redeem_pairing_code(
    body: RedeemPairingCodeRequest, request: Request
) -> RedeemPairingCodeResponse:
    """Exchange a pairing OTP for a long-lived device token.

    This endpoint is on the auth-middleware ALLOWLIST (it bootstraps auth, so
    it cannot require a token itself).  On success, the device stores the
    returned ``device_token`` in encrypted storage and includes it as
    ``Authorization: Bearer <device_token>`` on all subsequent requests.
    """
    identity = request.app.state.identity
    ctx = await identity.redeem_pairing_code(
        code=body.code,
        device_fingerprint=body.device_fingerprint,
    )
    if ctx is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid, expired, or already-redeemed pairing code",
        )
    log.info(
        "identity.pair_endpoint_success",
        child_id=ctx.child_id,
        token_prefix=ctx.device_token[:8],
    )
    return RedeemPairingCodeResponse(
        device_token=ctx.device_token,
        child_id=ctx.child_id,
        role=ctx.role,
    )


@router.patch(
    "/device/fcm-token",
    response_model=SetFcmTokenResponse,
    summary="Register or update the FCM push token for the authenticated device (S3)",
)
async def set_fcm_token(body: SetFcmTokenRequest, request: Request) -> SetFcmTokenResponse:
    """Store or update the FCM registration token for the calling device.

    Requires a valid device token (Bearer header); works for both child and parent
    role devices.  For digest delivery, the PARENT device's FCM token is the
    relevant one — the parent device should call this after obtaining a push token
    from FCM (Android: ``FirebaseMessaging.getInstance().getToken()``).

    This endpoint is NOT on the auth allowlist — it requires a valid Bearer token.
    """
    ctx = _require_any_device_context(request)
    identity = request.app.state.identity

    ok = await identity.set_fcm_token(ctx.device_token, body.fcm_token)
    if not ok:
        raise HTTPException(status_code=404, detail="Device token not found")

    log.info(
        "identity.fcm_token_registered",
        child_id=ctx.child_id,
        parent_id=ctx.parent_id,
        role=ctx.role,
    )
    return SetFcmTokenResponse(ok=True)


# ---------------------------------------------------------------------------
# Registration function
# ---------------------------------------------------------------------------


def register_identity(app) -> None:
    """Register the identity router on the FastAPI app.

    Called from ``main.py`` after ``register_gateway()`` so Gatekeeper
    middleware wraps these endpoints too.
    """
    app.include_router(router)
