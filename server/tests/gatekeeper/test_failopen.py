"""Tests for fail-open semantics — rate-limit store failure must allow requests.

slowapi's Limiter is constructed with ``swallow_errors=True``. This means that
if the backing store's ``hit()`` method raises an unexpected exception during
``__evaluate_limits``, the limiter swallows it and allows the request through
rather than blocking traffic. This is the PRD §8.7 fail-open contract.

We simulate a store outage by patching the internal ``limiter.hit`` method
(the limits-library strategy object, not the slowapi Limiter) to raise a
RuntimeError. This is the code path that ``swallow_errors`` actually guards.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from .conftest import GatekeeperSettings, make_app


def _make_client_and_app(limit: int = 1000):
    settings = GatekeeperSettings(
        RATE_LIMIT_PER_MINUTE=limit,
        MAX_BODY_BYTES=10 * 1024 * 1024,
        CLIENT_RECV_TIMEOUT_S=30.0,
    )
    app = make_app(settings)
    client = TestClient(app, raise_server_exceptions=False)
    return client, app


class TestFailOpen:
    """Requests must succeed even when the rate-limit storage raises."""

    def test_normal_request_passes_without_store_failure(self):
        """Baseline: without any monkeypatching, a request gets 200."""
        client, _ = _make_client_and_app()
        resp = client.get("/ping")
        assert resp.status_code == 200

    def test_request_passes_when_storage_hit_raises(self):
        """When the storage's hit() raises RuntimeError, swallow_errors allows the request.

        We patch the underlying limits-strategy ``hit`` method to simulate a
        storage outage. slowapi's ``_swallow_errors=True`` catches the exception
        inside ``__evaluate_limits`` and lets the request through.
        """
        client, app = _make_client_and_app()

        # The limiter attribute on app.state.limiter is the limits-library strategy.
        original_hit = app.state.limiter.limiter.hit

        def _raise_always(*args, **kwargs):
            raise RuntimeError("Simulated storage failure")

        app.state.limiter.limiter.hit = _raise_always
        try:
            resp = client.get("/ping")
            # Fail-open: request should get 200, not 429 or 500.
            assert resp.status_code == 200, (
                f"Expected 200 (fail-open) but got {resp.status_code}: {resp.text}"
            )
        finally:
            app.state.limiter.limiter.hit = original_hit

    def test_multiple_requests_pass_when_storage_fails(self):
        """Multiple successive requests all pass when the store is failing."""
        client, app = _make_client_and_app()

        original_hit = app.state.limiter.limiter.hit

        def _raise_always(*args, **kwargs):
            raise RuntimeError("Simulated storage failure")

        app.state.limiter.limiter.hit = _raise_always
        try:
            for i in range(5):
                resp = client.get("/ping")
                assert resp.status_code == 200, (
                    f"Request {i+1} failed with {resp.status_code} — fail-open broken"
                )
        finally:
            app.state.limiter.limiter.hit = original_hit

    def test_fail_open_does_not_return_500(self):
        """A storage failure must not propagate as a 500 Internal Server Error."""
        client, app = _make_client_and_app()

        original_hit = app.state.limiter.limiter.hit
        app.state.limiter.limiter.hit = lambda *a, **kw: (_ for _ in ()).throw(
            Exception("boom")
        )
        try:
            resp = client.get("/ping")
            assert resp.status_code != 500, (
                "Storage failure must not result in 500; fail-open should yield 200"
            )
        finally:
            app.state.limiter.limiter.hit = original_hit

    def test_fail_open_does_not_return_429(self):
        """A storage failure must not erroneously produce a 429 rate-limit response."""
        client, app = _make_client_and_app()

        original_hit = app.state.limiter.limiter.hit
        app.state.limiter.limiter.hit = lambda *a, **kw: (_ for _ in ()).throw(
            RuntimeError("boom")
        )
        try:
            resp = client.get("/ping")
            assert resp.status_code != 429, (
                "Storage failure must not produce 429; fail-open should yield 200"
            )
        finally:
            app.state.limiter.limiter.hit = original_hit
