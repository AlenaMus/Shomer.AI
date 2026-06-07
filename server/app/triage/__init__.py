"""Triage module — deterministic decision gate between classifier and Context Agent.

Public surface (port-only, per docs/design/README.md):

    from server.app.triage import TriageEngine

Concrete adapters (ThresholdTriageEngine, StubTriageEngine) are also exported
here so the composition root (server/app/main.py lifespan()) can import them
with a single import.  All other business code should depend on the Protocol.

Reference: docs/design/triage/design.md.
"""

from __future__ import annotations

from .protocol import TriageEngine
from .settings import TriageSettings
from .stub_engine import StubTriageEngine
from .threshold_engine import ThresholdTriageEngine

__all__ = [
    # Port — the only symbol downstream business code should import.
    "TriageEngine",
    # Adapters — imported by main.py lifespan() (composition root).
    "ThresholdTriageEngine",
    "StubTriageEngine",
    # Settings
    "TriageSettings",
]
