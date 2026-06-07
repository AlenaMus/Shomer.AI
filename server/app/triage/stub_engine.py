"""Stub Triage adapter — returns a fixed decision, for tests and dry-runs.

Reference: docs/design/triage/design.md §2.5 (adapter table).

``StubTriageEngine`` satisfies the ``TriageEngine`` Protocol and always returns
the decision supplied at construction time. It is the test double used in
full-pipeline integration tests when the caller wants deterministic triage
routing without depending on threshold configuration.
"""

from __future__ import annotations

from ..schemas import ClassificationResult, TriageDecision


class StubTriageEngine:
    """Fixed-decision triage engine for tests.

    Args:
        fixed_decision: The ``TriageDecision`` returned for every ``decide()``
            call. Defaults to ``SILENT``.
    """

    def __init__(
        self,
        fixed_decision: TriageDecision = TriageDecision.SILENT,
    ) -> None:
        self._decision = fixed_decision

    def decide(
        self,
        result: ClassificationResult,
        context_agent_enabled: bool,
    ) -> TriageDecision:
        """Return the pre-configured fixed decision regardless of input."""
        return self._decision
