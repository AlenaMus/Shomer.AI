"""HTTP middleware: per-request audit logging.

Endpoints attach domain-specific details to ``request.state.audit`` (a dict
the middleware initialises to ``{}`` at the start of each request). The
middleware then merges that dict into the audit record's ``request`` field
when the response is finalised, so the JSONL line ends up with both the
generic transport details (method, path, status, latency) and the
endpoint-specific ones (e.g. the classified text, or the image's metadata).
"""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from .audit import write_audit

# Cap stored response bodies to keep individual JSONL lines small. The Phase 1
# responses are all <1 KB; this only matters once vision LLMs start emitting
# long analyses in Phase 2+.
_MAX_BODY_BYTES_FOR_AUDIT = 8192


class AuditLoggingMiddleware(BaseHTTPMiddleware):
    """Log one JSONL record per HTTP request and add ``X-Request-ID`` header."""

    async def dispatch(self, request: Request, call_next):
        request_id = str(uuid.uuid4())
        ts = datetime.now(timezone.utc)
        started = time.perf_counter()

        # Endpoints fill this with domain-specific details (request body summary).
        request.state.audit = {}

        response = await call_next(request)
        latency_ms = int((time.perf_counter() - started) * 1000)

        # Drain the streaming body so we can both log it and re-send it.
        # FastAPI/Starlette responses are async iterators that can only be
        # consumed once, so we have to rebuild a Response afterwards.
        body_bytes = b""
        async for chunk in response.body_iterator:
            body_bytes += chunk

        # BaseHTTPMiddleware wraps the upstream response in a _StreamingResponse
        # whose `media_type` is None; the actual content-type lives in headers.
        content_type = response.headers.get("content-type", "")
        body_for_audit = _parse_body_for_audit(body_bytes, content_type)

        record = {
            "ts": ts.isoformat().replace("+00:00", "Z"),
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "query": dict(request.query_params),
            "client": request.client.host if request.client else None,
            "request": getattr(request.state, "audit", {}) or {},
            "response": {
                "status": response.status_code,
                "body": body_for_audit,
            },
            "latency_ms": latency_ms,
        }
        write_audit(record)

        # Rebuild the response with the captured body + add the request id so
        # the client can quote it back in bug reports.
        new_headers = dict(response.headers)
        new_headers["x-request-id"] = request_id
        new_headers.pop("content-length", None)  # Response recomputes it
        return Response(
            content=body_bytes,
            status_code=response.status_code,
            headers=new_headers,
            media_type=response.media_type,
        )


def _parse_body_for_audit(body_bytes: bytes, media_type: str | None) -> Any:
    """Best-effort decode of a response body for audit storage.

    Tries JSON when the response says JSON; falls back to a UTF-8 string,
    truncated to keep audit lines manageable.
    """
    truncated = body_bytes[:_MAX_BODY_BYTES_FOR_AUDIT]
    if media_type and "application/json" in media_type:
        try:
            return json.loads(truncated.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            pass
    return truncated.decode("utf-8", errors="replace")
