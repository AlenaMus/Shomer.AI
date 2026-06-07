"""Tests for slowapi rate limiting — 429 after exceeding the per-minute limit."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from .conftest import GatekeeperSettings, make_app


class TestRateLimit:
    """Verify that the (N+1)th request within the window gets a 429."""

    _LIMIT = 3  # use a small limit so tests don't send hundreds of requests

    def _client(self, limit: int = _LIMIT) -> TestClient:
        settings = GatekeeperSettings(
            RATE_LIMIT_PER_MINUTE=limit,
            MAX_BODY_BYTES=10 * 1024 * 1024,
            CLIENT_RECV_TIMEOUT_S=30.0,
        )
        app = make_app(settings)
        # raise_server_exceptions=False so 429 comes back as a response
        return TestClient(app, raise_server_exceptions=False)

    def test_requests_within_limit_succeed(self):
        """All N requests within the limit should return 200."""
        client = self._client()
        for i in range(self._LIMIT):
            resp = client.get("/ping")
            assert resp.status_code == 200, f"Request {i+1} should pass"

    def test_request_over_limit_returns_429(self):
        """The (N+1)th request must return 429."""
        client = self._client()
        for _ in range(self._LIMIT):
            client.get("/ping")
        resp = client.get("/ping")
        assert resp.status_code == 429

    def test_429_body_is_structured_json(self):
        """The 429 body follows the contract: error, detail, retry_after_seconds, trace_id."""
        client = self._client()
        for _ in range(self._LIMIT):
            client.get("/ping")
        resp = client.get("/ping")
        assert resp.status_code == 429
        body = resp.json()
        assert body["error"] == "rate_limit_exceeded"
        assert "detail" in body
        assert "retry_after_seconds" in body
        assert isinstance(body["retry_after_seconds"], int)
        assert "trace_id" in body

    def test_429_carries_retry_after_header(self):
        """The 429 response must include the Retry-After header."""
        client = self._client()
        for _ in range(self._LIMIT):
            client.get("/ping")
        resp = client.get("/ping")
        assert resp.status_code == 429
        assert "retry-after" in resp.headers or "Retry-After" in resp.headers

    def test_429_carries_x_trace_id_header(self):
        """The 429 response must include the X-Trace-ID header."""
        client = self._client()
        for _ in range(self._LIMIT):
            client.get("/ping")
        resp = client.get("/ping")
        assert resp.status_code == 429
        trace_id = resp.headers.get("x-trace-id") or resp.headers.get("X-Trace-ID")
        assert trace_id is not None and len(trace_id) > 0

    def test_429_trace_id_is_non_empty_string(self):
        """trace_id in the 429 body is a non-empty string."""
        client = self._client()
        for _ in range(self._LIMIT):
            client.get("/ping")
        resp = client.get("/ping")
        body = resp.json()
        assert isinstance(body["trace_id"], str)
        assert len(body["trace_id"]) > 0

    def test_limit_of_one_blocks_second_request(self):
        """Edge case: limit=1 allows the first request and blocks the second."""
        client = self._client(limit=1)
        r1 = client.get("/ping")
        r2 = client.get("/ping")
        assert r1.status_code == 200
        assert r2.status_code == 429
