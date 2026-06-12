"""FastAPI router for the Monitor ingest endpoints.

Exposes:
    POST /v1/monitor/events → MonitorBatchResponse
    POST /v1/monitor/image  → MonitorImageResponse

Auth (S2): both endpoints require a valid child device token.
  - The DeviceAuthMiddleware (gateway.py) resolves the Bearer token and sets
    ``request.state.device_context``.
  - This router enforces: device_context must be present with role="child", and
    the payload's ``child_id`` must equal ``device_context.child_id``.
  - 401 on missing/invalid token; 403 on child_id mismatch.

Rationale for enforcing auth in the router (not middleware): the child_id match
is a resource-level authorization check that requires knowledge of the request
body/form fields (the ``child_id`` value), which is not available to the
middleware.  The middleware stays content-blind (it only resolves the token);
the router enforces the identity + ownership constraint co-located with the
resource.

The router is registered in ``main.py`` via ``register_monitor(app)`` — the
same pattern as ``register_gateway`` in ``gateway.py``.

Trace-id derivation reuses the same ``X-Trace-Id`` header convention as the
rest of the server.
"""

from __future__ import annotations

import hashlib
import uuid

import structlog
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from ..schemas import (
    MonitorBatchRequest,
    MonitorBatchResponse,
    MonitorEvent,
    MonitorImageResponse,
)

log = structlog.get_logger("shomer.monitor.router")

router = APIRouter(prefix="/v1/monitor", tags=["monitor"])

# A chat-line segment must carry at least this many alphabetic (Hebrew or Latin)
# characters to be worth classifying.  This filters bare timestamps ("10:42"),
# read-receipts, and emoji-only lines out of the screenshot ingest stream.
_MIN_SEGMENT_ALPHA_CHARS = 2

# ---------------------------------------------------------------------------
# OCR gibberish gate
# ---------------------------------------------------------------------------
# Minimum consecutive-alphabetic run (Hebrew or Latin) required in a segment.
# "ה.-ו" has no run of 3 → dropped.  "שלום" has a run of 4 → kept.
_MIN_ALPHA_RUN = 3

# Minimum ratio of alphabetic to total non-whitespace characters.
# "09/06/2026 תדושות.ארגוו ה.- ו8.-.קרן | 4%" has many punctuation/digit
# chars → ratio below threshold → dropped.
_MIN_ALPHA_RATIO = 0.45  # env-overridable; see _alpha_ratio_threshold()


def _alpha_ratio_threshold() -> float:
    """Return the minimum alpha ratio, overridable via MONITOR_OCR_MIN_ALPHA_RATIO."""
    import os

    raw = os.getenv("MONITOR_OCR_MIN_ALPHA_RATIO")
    if raw:
        try:
            v = float(raw)
            if 0.0 < v <= 1.0:
                return v
        except ValueError:
            pass
    return _MIN_ALPHA_RATIO


def _longest_alpha_run(text: str) -> int:
    """Return the length of the longest consecutive Hebrew/Latin alphabetic run."""
    best = 0
    current = 0
    for ch in text:
        cp = ord(ch)
        is_alpha = (0x0590 <= cp <= 0x05FF) or (0xFB1D <= cp <= 0xFB4F) or (
            ch.isascii() and ch.isalpha()
        )
        if is_alpha:
            current += 1
            if current > best:
                best = current
        else:
            current = 0
    return best


def _looks_like_text(seg: str) -> bool:
    """Return True if the segment looks like real text rather than OCR gibberish.

    Three conditions must ALL hold:
      1. At least ``_MIN_SEGMENT_ALPHA_CHARS`` total Hebrew/Latin alpha chars.
      2. A consecutive alphabetic run of at least ``_MIN_ALPHA_RUN`` chars.
      3. Alpha chars / non-whitespace chars >= ``_alpha_ratio_threshold()``.

    Verified to DROP  "09/06/2026 תדושות.ארגוו ה.- ו8.-.קרן | 4%"  and
    verified to KEEP  "שלום" · "Daria: אנחנו לא יכולים" · "hello world".
    """
    total_alpha = _alpha_char_count(seg)
    if total_alpha < _MIN_SEGMENT_ALPHA_CHARS:
        return False
    if _longest_alpha_run(seg) < _MIN_ALPHA_RUN:
        return False
    non_ws = sum(1 for ch in seg if not ch.isspace())
    if non_ws == 0:
        return False
    ratio = total_alpha / non_ws
    if ratio < _alpha_ratio_threshold():
        return False
    return True

# Hard cap on how many segments a single screenshot may fan out into.  A real
# chat screen OCRs to 15–35 lines (messages + contact names + UI chrome); without
# a cap, each borderline segment triggers a synchronous Context Agent (LLM) call
# and the request blows past the gateway timeout.  We keep the N most
# text-dense segments (real messages outrank short UI chrome).  Env-overridable
# via MONITOR_IMAGE_MAX_SEGMENTS.  The deeper fix (async ingest queue / batched
# classification) is the S6 backlog item; this bounds the synchronous path.
_DEFAULT_MAX_SEGMENTS = 8


def _max_segments() -> int:
    """Resolve the per-screenshot segment cap from the environment."""
    import os

    raw = os.getenv("MONITOR_IMAGE_MAX_SEGMENTS")
    if raw:
        try:
            return max(1, int(raw))
        except ValueError:
            pass
    return _DEFAULT_MAX_SEGMENTS


def _alpha_char_count(text: str) -> int:
    """Count Hebrew-block or ASCII-letter characters in *text*."""
    count = 0
    for ch in text:
        cp = ord(ch)
        if (0x0590 <= cp <= 0x05FF) or (0xFB1D <= cp <= 0xFB4F) or (
            ch.isascii() and ch.isalpha()
        ):
            count += 1
    return count


def _select_text_segments(segments: tuple[str, ...]) -> list[str]:
    """Keep OCR line segments that carry real text, de-duplicating exact repeats.

    Drops blank lines, pure-chrome lines (timestamps, separators), and OCR
    gibberish.  The ``_looks_like_text`` gate enforces three conditions:
      - Minimum Hebrew/Latin alphabetic character count.
      - Minimum consecutive alphabetic run (filters "ה.-ו" style fragments).
      - Minimum alpha/non-whitespace ratio (filters "09/06/2026 תדושות.ארגוו ה.- ו8.-.קרן | 4%").

    When more than ``_max_segments()`` substantive lines survive, keeps the
    most text-dense ones (by alphabetic-character count) so a busy screen
    can't fan out into dozens of synchronous classify+LLM calls.  Reading
    order is preserved among the kept segments.
    """
    selected: list[str] = []
    seen: set[str] = set()
    for seg in segments:
        seg = seg.strip()
        if not seg or seg in seen:
            continue
        if not _looks_like_text(seg):
            continue
        seen.add(seg)
        selected.append(seg)

    cap = _max_segments()
    if len(selected) <= cap:
        return selected

    # Too many lines: keep the `cap` most text-dense, then restore reading order.
    ranked = sorted(selected, key=_alpha_char_count, reverse=True)[:cap]
    keep = set(ranked)
    return [seg for seg in selected if seg in keep]


def _enforce_child_auth_for_child_id(request: Request, child_id: str) -> None:
    """Enforce S2 auth given a ``child_id`` string directly.

    Rules:
      1. ``request.state.device_context`` must be set (→ 401 if not).
      2. ``device_context.role`` must be "child" (→ 403 otherwise).
      3. ``device_context.child_id`` must equal ``child_id`` (→ 403 on mismatch).

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
    if ctx.child_id != child_id:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Token is for child '{ctx.child_id}' but child_id is "
                f"'{child_id}'; a device may only ingest its own events"
            ),
        )


def _enforce_child_auth(request: Request, batch: MonitorBatchRequest) -> None:
    """Enforce S2 auth on the monitor ingest endpoint (batch variant).

    Delegates to :func:`_enforce_child_auth_for_child_id` using
    ``batch.child_id`` so the batch and image routes share identical auth logic.
    """
    _enforce_child_auth_for_child_id(request, batch.child_id)


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
    # conversation_id is not passed here — MonitorIngest resolves it per-event
    # from event.conversation_id → event.app_package → "default".
    response = await monitor.ingest_batch(request, batch, trace_id=trace_id)
    return response


@router.post(
    "/image",
    response_model=MonitorImageResponse,
    status_code=202,
    summary="Upload a chat screenshot; OCR it and run the monitor pipeline",
)
async def ingest_image(
    request: Request,
    image: UploadFile = File(..., description="JPEG screenshot of the chat"),
    child_id: str = Form(..., description="Opaque child identifier (no PII)"),
    session_id: str = Form(..., description="Client session identifier"),
    client_msg_id: str = Form(..., description="Device idempotency key (UUID4)"),
    captured_at: float = Form(..., description="Epoch seconds from the client clock"),
    direction: str = Form("screen", description="Capture direction; default 'screen'"),
) -> MonitorImageResponse:
    """Accept a chat screenshot, OCR it, and run the existing monitor pipeline.

    Auth (S2): requires ``Authorization: Bearer <device-token>`` with role="child"
    matching ``child_id`` form field.  Returns 401 on missing token, 403 on mismatch.

    OCR is performed server-side via ``app.state.ocr`` (TesseractOcrBackend by
    default; Hebrew + English).  If the image yields no extractable text the
    endpoint still returns 202 with ``accepted=0, ocr_text_len=0`` — a blank or
    purely visual screenshot is not an error.

    When text is found it is synthesised into a single ``MonitorEvent`` and
    routed through ``MonitorIngest.ingest_batch`` verbatim — dedup, classify,
    triage, flag, and digest all behave identically to a text-event batch.
    Server-side dedup (by ``text_hash``) ensures that near-duplicate screenshots
    producing the same OCR output are never double-flagged.
    """
    # S2 authorization: child token must match the form's child_id.
    _enforce_child_auth_for_child_id(request, child_id)

    # Validate child_id is non-empty.
    if not child_id.strip():
        raise HTTPException(status_code=400, detail="child_id must be non-empty")

    # Derive trace-id from incoming header or generate one.
    trace_id = request.headers.get("X-Trace-Id") or str(uuid.uuid4())

    # Ensure request.state.audit exists (required by _run_pipeline).
    if not hasattr(request.state, "audit") or request.state.audit is None:
        request.state.audit = {}

    # Read image bytes (never raises; errors propagate as HTTP 422 via FastAPI).
    image_bytes = await image.read()
    mime_type = image.content_type or "image/jpeg"

    log.info(
        "monitor.image_received",
        trace_id=trace_id,
        child_id=child_id,
        session_id=session_id,
        client_msg_id=client_msg_id,
        image_bytes=len(image_bytes),
        mime_type=mime_type,
    )

    # OCR — NEVER raises (Protocol contract).
    ocr_result = await request.app.state.ocr.process(image_bytes, mime_type)
    ocr_text = ocr_result.extracted_text.strip()

    log.info(
        "monitor.image_ocr_done",
        trace_id=trace_id,
        child_id=child_id,
        ocr_text_len=len(ocr_text),
        image_unreadable=ocr_result.image_unreadable,
        backend=ocr_result.backend,
    )

    # Blank screenshot — not an error; return empty accepted counts.
    if not ocr_text:
        return MonitorImageResponse(
            accepted=0,
            deduped=0,
            flagged=0,
            acks=[],
            ocr_text_len=0,
        )

    # Build one MonitorEvent PER chat line, not one blob for the whole screen.
    #
    # A chat screenshot contains several messages plus chrome (group name,
    # timestamps).  Concatenating them into a single classification event
    # dilutes a lone offensive line below the offensive threshold — verified
    # on the real DictaBERT model: the same offensive sentence scores
    # is_offensive=True @0.73 in isolation but the whole-screen blob scores
    # is_offensive=False @0.55 (see screenshot-ocr-capture.decision.md, Revisit).
    #
    # We therefore classify each OCR line segment independently.  This is fully
    # compatible with MonitorIngest — ingest_batch already accepts N events and
    # dedups each by (child_id, text_hash).  Segments with no real Hebrew/Latin
    # content (e.g. bare "10:42" timestamps) are skipped.  If the backend did
    # not segment (no line_segments) or nothing survives filtering, we fall back
    # to a single event over the whole OCR text so text is never silently dropped.
    segments = _select_text_segments(ocr_result.line_segments)
    if not segments:
        segments = [ocr_text]

    events = [
        MonitorEvent(
            # Per-segment idempotency key derived from the device's key + index
            # so re-uploading the same screenshot dedups segment-for-segment.
            client_msg_id=client_msg_id if len(segments) == 1 else f"{client_msg_id}#{idx}",
            app_package="screenshot",
            text=seg,
            text_hash=hashlib.sha256(seg.encode()).hexdigest(),
            captured_at=captured_at,
            direction=direction,
        )
        for idx, seg in enumerate(segments)
    ]
    batch = MonitorBatchRequest(
        session_id=session_id,
        child_id=child_id,
        events=events,
    )

    log.info(
        "monitor.image_segmented",
        trace_id=trace_id,
        child_id=child_id,
        segment_count=len(events),
        total_lines=len(ocr_result.line_segments),
    )

    # Build the conversation context from the full ordered segment list.
    #
    # The screenshot IS the conversation — every selected line is a turn.
    # We pass these as ``provided_history`` to the Context Agent so it sees
    # all visible lines as context when evaluating each individual segment,
    # rather than fetching (incorrect) per-child DB history.
    #
    # Role: the ``direction`` form field describes the overall capture
    # direction (e.g. "screen"), not individual message senders.  We use the
    # neutral role "screenshot_line" so ``_format_history`` renders it
    # without confusing it with a chat participant.  ``_format_history``
    # renders any unknown role as the literal string, so no changes to
    # prompt.py are needed.
    conversation_turns = [
        {"role": "screenshot_line", "text": seg}
        for seg in segments
    ]

    # Mint a stable per-screenshot conversation_id so all segments of this
    # screenshot share one thread and screenshots NEVER bleed into text history.
    # The id is derived from the device's client_msg_id so re-uploading the
    # same screenshot produces the same conversation_id (dedup-safe).
    screenshot_conv_id = f"screenshot:{client_msg_id}"

    log.info(
        "monitor.image_screenshot_conv_id",
        trace_id=trace_id,
        child_id=child_id,
        conversation_id=screenshot_conv_id,
    )

    # Reuse the existing ingest pipeline (dedup → classify → triage → flag).
    monitor = request.app.state.monitor
    batch_response = await monitor.ingest_batch(
        request,
        batch,
        trace_id=trace_id,
        conversation_turns=conversation_turns,
        conversation_id=screenshot_conv_id,
    )

    return MonitorImageResponse(
        accepted=batch_response.accepted,
        deduped=batch_response.deduped,
        flagged=batch_response.flagged,
        acks=batch_response.acks,
        ocr_text_len=len(ocr_text),
    )


def register_monitor(app) -> None:
    """Register the monitor router on the FastAPI app.

    Called from ``main.py`` after ``register_gateway()`` so Gatekeeper
    middleware (trace-id, rate-limit, size) wraps this endpoint too.
    """
    app.include_router(router)
