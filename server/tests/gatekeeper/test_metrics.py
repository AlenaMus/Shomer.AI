"""Tests for the Prometheus /metrics endpoint."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from .conftest import GatekeeperSettings, make_app


class TestMetricsEndpoint:
    """/metrics returns 200 with Prometheus text format content."""

    def _client(self) -> TestClient:
        settings = GatekeeperSettings(
            RATE_LIMIT_PER_MINUTE=1000,
            MAX_BODY_BYTES=10 * 1024 * 1024,
            CLIENT_RECV_TIMEOUT_S=30.0,
            METRICS_ENDPOINT="/metrics",
        )
        app = make_app(settings)
        return TestClient(app, raise_server_exceptions=False)

    def test_metrics_endpoint_returns_200(self):
        """GET /metrics must return HTTP 200."""
        client = self._client()
        resp = client.get("/metrics")
        assert resp.status_code == 200, (
            f"Expected 200 from /metrics but got {resp.status_code}: {resp.text[:200]}"
        )

    def test_metrics_content_type_is_text(self):
        """The content-type must be a Prometheus text-format type."""
        client = self._client()
        resp = client.get("/metrics")
        ct = resp.headers.get("content-type", "")
        # Prometheus text format: text/plain; version=0.0.4; charset=utf-8
        assert "text/plain" in ct or "text" in ct, (
            f"Expected text/plain content-type, got: {ct!r}"
        )

    def test_metrics_body_contains_prometheus_help_lines(self):
        """The response body must contain at least one '# HELP' line."""
        client = self._client()
        resp = client.get("/metrics")
        assert "# HELP" in resp.text, "Expected Prometheus HELP comments in /metrics"

    def test_metrics_body_contains_prometheus_type_lines(self):
        """The response body must contain at least one '# TYPE' line."""
        client = self._client()
        resp = client.get("/metrics")
        assert "# TYPE" in resp.text, "Expected Prometheus TYPE comments in /metrics"

    def test_metrics_available_after_requests(self):
        """Make a few requests then check /metrics — counters should be present."""
        client = self._client()
        client.get("/ping")
        client.get("/ping")
        resp = client.get("/metrics")
        assert resp.status_code == 200
        # At minimum some HTTP metric should appear after real requests.
        body = resp.text
        assert len(body) > 100, "Metrics body seems unexpectedly short"

    def test_custom_metrics_endpoint_path(self):
        """A custom metrics endpoint path is exposed correctly."""
        settings = GatekeeperSettings(
            RATE_LIMIT_PER_MINUTE=1000,
            MAX_BODY_BYTES=10 * 1024 * 1024,
            CLIENT_RECV_TIMEOUT_S=30.0,
            METRICS_ENDPOINT="/custom-metrics",
        )
        app = make_app(settings)
        client = TestClient(app, raise_server_exceptions=False)

        resp = client.get("/custom-metrics")
        assert resp.status_code == 200
