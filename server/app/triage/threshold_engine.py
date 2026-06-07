"""Concrete rule-based Triage adapter — the default production implementation.

Reference: docs/design/triage/design.md §3 (Internal Design).

``ThresholdTriageEngine`` reproduces the exact logic from the inline
``_triage()`` function in ``server/app/main.py`` and extends it with:
- Label-specific overrides (always_escalate_labels, always_alert_labels).
- A/B baseline path when ``context_agent_enabled=False``.
- Prometheus metrics and structlog observability.
- A safe outer try/except so the engine can never raise to its caller.

The G-03 fix is implemented in ``_decide_inner`` Step A: ``prob_offensive`` is
derived from ``result.confidence`` by inverting when ``is_offensive=False``.
This means ``is_offensive=False, confidence=0.92`` yields ``prob_offensive=0.08``
and routes to ``SILENT`` — NOT ``ALERT_DIRECT``.
"""

from __future__ import annotations

import structlog

from ..schemas import ClassificationResult, TriageDecision
from .metrics import (
    triage_decisions_total,
    triage_input_confidence,
    triage_label_overrides_total,
)
from .settings import TriageSettings

log = structlog.get_logger("shomer.triage")


class ThresholdTriageEngine:
    """Deterministic threshold-based triage engine.

    Thread-safe: all state is read-only after ``__init__``.  One shared
    instance should be constructed in ``main.py lifespan()`` and stored on
    ``app.state``.

    Args:
        settings: ``TriageSettings`` instance (usually loaded from env).
    """

    def __init__(self, settings: TriageSettings) -> None:
        self._s = settings

    # ------------------------------------------------------------------
    # Public Protocol surface
    # ------------------------------------------------------------------

    def decide(
        self,
        result: ClassificationResult,
        context_agent_enabled: bool,
    ) -> TriageDecision:
        """Return a ``TriageDecision`` for ``result``.

        Failure mode: any exception inside ``_decide_inner`` (bad types, None
        confidence, etc.) is caught here and returns ``REVIEW_NEEDED`` — the
        engine never raises to its caller.
        """
        try:
            return self._decide_inner(result, context_agent_enabled)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "triage.decide.exception",
                error=str(exc),
                result=(
                    result.__repr__()
                    if result is not None
                    else "None"
                ),
            )
            return self._emit(TriageDecision.REVIEW_NEEDED)

    # ------------------------------------------------------------------
    # Internal logic
    # ------------------------------------------------------------------

    def _decide_inner(
        self,
        result: ClassificationResult,
        context_agent_enabled: bool,
    ) -> TriageDecision:
        # 1. Classifier hard failure → always REVIEW_NEEDED.
        if result.error:
            log.info("triage.classifier_error")
            return self._emit(TriageDecision.REVIEW_NEEDED)

        # 2. Label-specific overrides — checked BEFORE threshold routing.
        if result.label in self._s.always_escalate_labels:
            if not context_agent_enabled:
                # A/B baseline: CA is off → treat as ALERT_DIRECT.
                log.debug(
                    "triage.label_override_escalate_ca_disabled",
                    label=result.label,
                    confidence=result.confidence,
                )
                triage_label_overrides_total.labels(
                    label=result.label, override_type="always_escalate"
                ).inc()
                return self._emit(TriageDecision.ALERT_DIRECT)
            log.debug(
                "triage.label_override_escalate",
                label=result.label,
                confidence=result.confidence,
            )
            triage_label_overrides_total.labels(
                label=result.label, override_type="always_escalate"
            ).inc()
            return self._emit(TriageDecision.ESCALATE_TO_CA)

        if result.label in self._s.always_alert_labels:
            log.debug(
                "triage.label_override_alert",
                label=result.label,
                confidence=result.confidence,
            )
            triage_label_overrides_total.labels(
                label=result.label, override_type="always_alert"
            ).inc()
            return self._emit(TriageDecision.ALERT_DIRECT)

        # 3. G-03 fix — normalize confidence to P(offensive).
        #    ``result.confidence`` = P(predicted_class), NOT P(offensive).
        #    For ``is_offensive=False, confidence=0.92``:
        #      prob_offensive = 1 - 0.92 = 0.08 → routes to SILENT (correct).
        #    Without this step the same input would route to ALERT_DIRECT (wrong).
        if result.is_offensive:
            prob_offensive = result.confidence
        else:
            prob_offensive = 1.0 - result.confidence

        triage_input_confidence.observe(prob_offensive)

        # 4. Threshold routing on P(offensive) — uniform direction.
        if prob_offensive <= self._s.borderline_low:
            log.debug(
                "triage.decide",
                label=result.label,
                is_offensive=result.is_offensive,
                confidence=result.confidence,
                prob_offensive=prob_offensive,
                decision=TriageDecision.SILENT.value,
                context_agent_enabled=context_agent_enabled,
                label_override=False,
            )
            return self._emit(TriageDecision.SILENT)

        if prob_offensive >= self._s.borderline_high:
            log.debug(
                "triage.decide",
                label=result.label,
                is_offensive=result.is_offensive,
                confidence=result.confidence,
                prob_offensive=prob_offensive,
                decision=TriageDecision.ALERT_DIRECT.value,
                context_agent_enabled=context_agent_enabled,
                label_override=False,
            )
            return self._emit(TriageDecision.ALERT_DIRECT)

        # 5. Borderline zone — A/B split.
        if not context_agent_enabled:
            decision = (
                TriageDecision.ALERT_DIRECT
                if prob_offensive >= self._s.baseline_threshold
                else TriageDecision.SILENT
            )
            log.debug(
                "triage.decide_ab_baseline",
                label=result.label,
                is_offensive=result.is_offensive,
                confidence=result.confidence,
                prob_offensive=prob_offensive,
                decision=decision.value,
                context_agent_enabled=False,
                label_override=False,
            )
            return self._emit(decision)

        log.debug(
            "triage.escalate_borderline",
            label=result.label,
            is_offensive=result.is_offensive,
            confidence=result.confidence,
            prob_offensive=prob_offensive,
            decision=TriageDecision.ESCALATE_TO_CA.value,
            context_agent_enabled=True,
            label_override=False,
        )
        return self._emit(TriageDecision.ESCALATE_TO_CA)

    @staticmethod
    def _emit(decision: TriageDecision) -> TriageDecision:
        """Increment the decisions counter and return the decision."""
        triage_decisions_total.labels(decision=decision.value).inc()
        return decision
