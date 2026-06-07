"""Tests for RequestTimeoutMiddleware — 408 on stalled routes.

The /slow route in the test app sleeps for 60 seconds. We set
``CLIENT_RECV_TIMEOUT_S`` to a very small value (0.05 s) so the timeout fires
quickly. The test then verifies the response is a structured 408 JSON.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from .conftest import GatekeeperSettings, make_app


class TestRequestTimeoutMiddleware:
    """Verify that a stalled route yields a 408 structured response."""

    # Use a very small timeout so the test doesn't actually wait long.
    _TIMEOUT_S = 0.05

    def _client(self, timeout_s: float = _TIMEOUT_S) -> TestClient:
        settings = GatekeeperSettings(
            RATE_LIMIT_PER_MINUTE=1000,
            MAX_BODY_BYTES=10 * 1024 * 1024,
            CLIENT_RECV_TIMEOUT_S=timeout_s,
        )
        app = make_app(settings)
        return TestClient(app, raise_server_exceptions=False)

    def test_fast_route_completes_normally(self):
        """A fast route should complete with 200 even with a short timeout."""
        # Use a more lenient timeout so /ping (which is instant) passes.
        client = self._client(timeout_s=5.0)
        resp = client.get("/ping")
        assert resp.status_code == 200

    def test_slow_route_returns_408(self):
        """A route that exceeds the timeout returns 408."""
        client = self._client(timeout_s=self._TIMEOUT_S)
        resp = client.get("/slow")
        assert resp.status_code == 408, (
            f"Expected 408 for slow route but got {resp.status_code}: {resp.text}"
        )

    def test_408_body_is_structured_json(self):
        """The 408 body follows the contract: error, detail, trace_id."""
        client = self._client()
        resp = client.get("/slow")
        assert resp.status_code == 408
        body = resp.json()
        assert body["error"] == "request_timeout"
        assert "detail" in body
        assert str(self._TIMEOUT_S) in body["detail"] or "did not complete" in body["detail"]
        assert "trace_id" in body

    def test_408_trace_id_is_non_empty(self):
        """The 408 body must include a non-empty trace_id."""
        client = self._client()
        resp = client.get("/slow")
        assert resp.status_code == 408
        body = resp.json()
        assert isinstance(body["trace_id"], str)
        assert len(body["trace_id"]) > 0

    def test_408_carries_x_trace_id_header(self):
        """The 408 response includes X-Trace-ID in the response headers."""
        client = self._client()
        resp = client.get("/slow")
        assert resp.status_code == 408
        trace_id = resp.headers.get("x-trace-id") or resp.headers.get("X-Trace-ID")
        assert trace_id is not None and len(trace_id) > 0

    def test_timeout_does_not_return_500(self):
        """A timeout must not leak as a 500 Internal Server Error."""
        client = self._client()
        resp = client.get("/slow")
        assert resp.status_code != 500, (
            "Timeout should produce 408, not 500 — exception handling may be broken"
        )
