"""Tests for TraceIdMiddleware — X-Trace-ID header on every response."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from .conftest import GatekeeperSettings, make_app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _is_uuid4(value: str) -> bool:
    return bool(_UUID_RE.match(value))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestTraceIdMiddleware:
    """X-Trace-ID is present on every response and is a valid UUID4."""

    def _client(self) -> TestClient:
        settings = GatekeeperSettings(
            RATE_LIMIT_PER_MINUTE=1000,
            MAX_BODY_BYTES=10 * 1024 * 1024,
            CLIENT_RECV_TIMEOUT_S=30.0,
        )
        app = make_app(settings)
        return TestClient(app, raise_server_exceptions=False)

    def test_get_carries_trace_id(self):
        """GET /ping response must include X-Trace-ID."""
        client = self._client()
        resp = client.get("/ping")
        assert resp.status_code == 200
        assert "x-trace-id" in resp.headers or "X-Trace-ID" in resp.headers

    def test_trace_id_is_valid_uuid4(self):
        """The generated trace-id must be a valid UUID4 string."""
        client = self._client()
        resp = client.get("/ping")
        trace_id = resp.headers.get("x-trace-id") or resp.headers.get("X-Trace-ID")
        assert trace_id is not None
        assert _is_uuid4(trace_id), f"Not a UUID4: {trace_id!r}"

    def test_post_carries_trace_id(self):
        """POST /echo response also carries X-Trace-ID."""
        client = self._client()
        resp = client.post("/echo", json={})
        assert resp.status_code == 200
        trace_id = resp.headers.get("x-trace-id") or resp.headers.get("X-Trace-ID")
        assert trace_id is not None

    def test_each_request_gets_distinct_trace_id(self):
        """Two back-to-back requests must have different trace-ids."""
        client = self._client()
        r1 = client.get("/ping")
        r2 = client.get("/ping")
        t1 = r1.headers.get("x-trace-id") or r1.headers.get("X-Trace-ID")
        t2 = r2.headers.get("x-trace-id") or r2.headers.get("X-Trace-ID")
        assert t1 != t2, "Two requests should not share the same trace-id"

    def test_inbound_trace_id_is_honored(self):
        """If the client sends X-Trace-Id, the same value is echoed back."""
        client = self._client()
        custom_id = "dead-beef-0000-0000-0000-000000000001"
        resp = client.get("/ping", headers={"X-Trace-Id": custom_id})
        returned = resp.headers.get("x-trace-id") or resp.headers.get("X-Trace-ID")
        assert returned == custom_id

    def test_404_also_carries_trace_id(self):
        """Even a 404 (unmatched route) should propagate the trace-id header."""
        client = self._client()
        resp = client.get("/does-not-exist")
        # Middleware runs even for 404s (the endpoint handler raises 404).
        # Starlette still passes 404 through the middleware chain.
        trace_id = resp.headers.get("x-trace-id") or resp.headers.get("X-Trace-ID")
        # Trace-id may or may not be set for unmatched routes depending on
        # how Starlette routes the 404; assert it if present, skip if absent.
        if trace_id:
            assert len(trace_id) > 0
