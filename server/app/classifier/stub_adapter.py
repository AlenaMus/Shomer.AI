"""StubClassifier — a deterministic, dependency-free TextClassifier.

Reference: docs/design/classifier/design.md §2.5 ("StubClassifier").

This adapter exists for three reasons:

1. **Unit tests and contract tests** — every parametrized contract assertion
   can run against the stub without spinning up Ollama or downloading a HF
   model. Lets the test suite stay green in CI with zero external deps.
2. **Degraded-mode default** — if both real adapters fail to construct at
   startup, ``main.py`` can fall back to the stub so the rest of the
   pipeline keeps booting. The triage layer will treat every result as
   borderline (confidence=0.5) and route everything to the Context Agent
   or human review.
3. **Reference implementation** of the Protocol — anything that compiles
   against StubClassifier compiles against every real adapter, by Liskov.

The result always reads:
  ``label="non_offensive"``, ``confidence=0.5``, ``is_offensive=False``,
  ``is_borderline=True``, ``model_version="stub"``, ``error=False``.
"""

from __future__ import annotations

import time

from ..schemas import ClassificationResult, HealthState
from .logging import bind_context
from .metrics import record_classification


class StubClassifier:
    """No-op classifier returning a fixed mid-confidence borderline result."""

    _MODEL_VERSION = "stub"

    def __init__(self) -> None:
        # Stateless on purpose — no dependencies to inject.
        pass

    @property
    def model_version(self) -> str:
        return self._MODEL_VERSION

    async def health(self) -> tuple[HealthState, str]:
        """Always healthy. The stub has nothing to talk to."""
        return HealthState.OK, "stub classifier — fixed result"

    async def classify(self, text: str) -> ClassificationResult:
        """Return a fixed borderline non_offensive result.

        Honors the Protocol contract:
        - never raises
        - confidence ∈ [0, 1]
        - is_offensive == (label != "non_offensive")
        - is_borderline derived from confidence vs [0.3, 0.7]
        """
        t0 = time.perf_counter()
        # No real inference; keep latency_ms truthful for the metric.
        result = ClassificationResult(
            label="non_offensive",
            confidence=0.5,
            is_offensive=False,
            model_version=self._MODEL_VERSION,
            latency_ms=(time.perf_counter() - t0) * 1000,
            is_borderline=True,
            raw_confidence=0.5,
            error=False,
        )

        logger = bind_context(model_version=self._MODEL_VERSION)
        logger.info(
            "classification_complete",
            label=result.label,
            confidence=result.confidence,
            raw_confidence=result.raw_confidence,
            is_borderline=result.is_borderline,
            latency_ms=result.latency_ms,
            text_len=len(text) if isinstance(text, str) else 0,
            adapter="stub",
        )
        record_classification(
            label=result.label,
            model_version=result.model_version,
            confidence=result.confidence,
            raw_confidence=result.raw_confidence,
            latency_s=result.latency_ms / 1000.0,
            is_borderline=result.is_borderline,
            error=result.error,
            calibrated=False,
        )
        return result
