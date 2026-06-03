"""Public port for the Frontline Classifier module.

Reference: docs/design/classifier/design.md §2, §2.5.

The server core, the triage module, and the contract test suite all depend on
this Protocol — never on a concrete adapter class. Adapters
(OllamaDictaBertClassifier, HuggingFaceClassifier, StubClassifier) live in
private submodules and are constructed only in server/app/main.py lifespan().
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..schemas import ClassificationResult, HealthState


@runtime_checkable
class TextClassifier(Protocol):
    """Hebrew text classifier — 5-label SinaLab schema.

    Contract (every adapter MUST satisfy):
    - ``classify()`` NEVER raises on model failure. On any error it returns
      a ClassificationResult with ``error=True``, ``label="non_offensive"``,
      ``confidence=0.5``; the triage router treats this as REVIEW_NEEDED.
    - ``confidence`` is the CALIBRATED ``P(predicted_class)``, 0.0–1.0.
    - ``is_borderline`` is derived from ``confidence`` against the configured
      thresholds (``BORDERLINE_LOW``, ``BORDERLINE_HIGH``).
    - Latency target: p99 < 100 ms (PRD §8.1).
    """

    async def classify(self, text: str) -> ClassificationResult: ...

    async def health(self) -> tuple[HealthState, str]:
        """Return ``(state, detail)``. Aggregated by the server ``/health`` rollup."""
        ...

    @property
    def model_version(self) -> str:
        """e.g. ``"v1.0-standin"`` or ``"v1.1-dictabert"``."""
        ...
