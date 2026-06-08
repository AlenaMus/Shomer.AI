"""Monitor module — batch ingest orchestrator + endpoint for Shomer.AI.

Public surface:

    from server.app.monitor import MonitorIngest, register_monitor

``MonitorIngest`` is an application service (not a swappable port) constructed
once in ``main.py`` lifespan() and stored at ``app.state.monitor``.

``register_monitor(app)`` registers the ``POST /v1/monitor/events`` router on
the FastAPI app — call it from ``main.py`` after ``register_gateway()``.

Reference: linked-yawning-sifakis.md §S1 "Ingest MVP".
"""

from __future__ import annotations

from .ingest import MonitorIngest
from .router import register_monitor

__all__ = [
    "MonitorIngest",
    "register_monitor",
]
