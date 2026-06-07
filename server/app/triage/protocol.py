"""Public port for the Triage module.

Reference: docs/design/triage/design.md §2, §2.5.

The ``/classify`` handler and any future pipeline orchestrator depend on this
Protocol — never on ``ThresholdTriageEngine`` directly. Concrete adapters
(ThresholdTriageEngine, StubTriageEngine) live in private submodules and are
constructed only in server/app/main.py lifespan().

Contract (every adapter MUST satisfy):
- ``decide()`` is synchronous, CPU-only, completes in < 0.5 ms.
- ``decide()`` NEVER raises. Any error or invalid input maps to
  ``TriageDecision.REVIEW_NEEDED`` — consistent with the PRD's default-safe
  principle: "never silently lose an alert in a child-safety system".
- ``decide()`` is idempotent: same ``ClassificationResult`` + same settings
  → same ``TriageDecision`` every time.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..schemas import ClassificationResult, TriageDecision


@runtime_checkable
class TriageEngine(Protocol):
    """Deterministic decision gate between the frontline classifier and the
    Context Agent.

    The caller passes the raw ``ClassificationResult`` from the classifier and
    a flag indicating whether the Context Agent is currently active. The engine
    returns a ``TriageDecision`` that drives the next pipeline step.

    Implementations:
    - ``ThresholdTriageEngine`` — default rule-based adapter (§3 of the LLD).
    - ``StubTriageEngine`` — fixed/configurable decision for tests.
    """

    def decide(
        self,
        result: ClassificationResult,
        context_agent_enabled: bool,
    ) -> TriageDecision:
        """Return a ``TriageDecision`` for ``result``.

        Args:
            result: Output from ``TextClassifier.classify()``.
            context_agent_enabled: True iff the Context Agent is wired in and
                available. When False the engine must produce ``ALERT_DIRECT``
                or ``SILENT`` — never ``ESCALATE_TO_CA``.

        Returns:
            A ``TriageDecision`` enum value. Never raises.
        """
        ...
