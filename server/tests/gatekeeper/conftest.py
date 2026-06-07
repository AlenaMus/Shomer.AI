"""Shared fixtures for the Gatekeeper / API Gateway test suite.

Design principles for test isolation:
- Every test that calls ``register_gateway`` builds a fresh throwaway FastAPI
  app with its own ``GatekeeperSettings`` — this prevents middleware state
  from leaking across tests.
- The ``register_gateway`` duplicate-registration guard in ``gateway.py``
  (try/except on Counter/Histogram construction) allows the same Prometheus
  metrics to be "registered" multiple times in one process without raising
  ``ValueError: Duplicated timeseries``.
- The global ``_RATE_LIMIT_COUNTER`` etc. singletons are reset to ``None``
  between tests via the ``reset_gateway_metrics`` autouse fixture so each
  test gets a clean slate for the module-level guards.
"""

from __future__ import annotations

import sys
import os
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Make ``server/`` importable as the parent of ``app/``.
_SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(_SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVER_ROOT))

from app.gateway import GatekeeperSettings, register_gateway  # noqa: E402


# ---------------------------------------------------------------------------
# Prometheus registry reset helper
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_gateway_metrics():
    """Reset gateway module-level metric singletons before each test.

    This forces ``_init_custom_metrics`` to call the try/except path on
    each test rather than re-using the previous test's objects, which lets
    our duplicate-registration guard stay exercised without accumulating state.
    """
    import app.gateway as gw
    gw._RATE_LIMIT_COUNTER = None
    gw._PAYLOAD_REJECTED_COUNTER = None
    gw._GATEWAY_OVERHEAD_HISTOGRAM = None
    gw._ACTIVE_REQUESTS_GAUGE = None
    yield
    # No teardown needed — the guard handles re-registration.


# ---------------------------------------------------------------------------
# Minimal app builder
# ---------------------------------------------------------------------------

def make_app(settings: GatekeeperSettings) -> FastAPI:
    """Build a throwaway FastAPI app with the gateway registered.

    Provides two dummy routes:
    - GET  /ping           → 200 {"ok": true}
    - POST /echo           → 200 {"received": true}
    - GET  /slow           → sleeps for a long time (timeout tests)
    """
    import asyncio

    app = FastAPI()

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    @app.post("/echo")
    async def echo():
        return {"received": True}

    @app.get("/slow")
    async def slow():
        # Sleep much longer than any test timeout setting.
        await asyncio.sleep(60)
        return {"done": True}

    register_gateway(app, settings)
    return app


# ---------------------------------------------------------------------------
# Default settings fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def default_settings(monkeypatch) -> GatekeeperSettings:
    """GatekeeperSettings with all env vars cleared for reproducibility."""
    for var in (
        "RATE_LIMIT_PER_MINUTE",
        "RATE_LIMIT_STORE_URL",
        "MAX_BODY_BYTES",
        "CLIENT_RECV_TIMEOUT_S",
        "METRICS_ENDPOINT",
        "METRICS_LATENCY_BUCKETS",
        "LOG_LEVEL",
        "LOG_FORMAT",
    ):
        monkeypatch.delenv(var, raising=False)
    return GatekeeperSettings()
