"""Configuration for the Triage module.

Reference: docs/design/triage/design.md §6 (Config table).

Env-var names match what ``server/app/main.py`` currently reads for the
inline ``_triage()`` helper:
  - ``BORDERLINE_LOW``            (no prefix — shared with ClassifierSettings)
  - ``BORDERLINE_HIGH``           (no prefix — shared with ClassifierSettings)
  - ``TRIAGE_BASELINE_THRESHOLD`` (triage-specific)
  - ``CONTEXT_AGENT_ENABLED``     (cross-module switch, no prefix)
  - ``TRIAGE_ALWAYS_ESCALATE_LABELS``
  - ``TRIAGE_ALWAYS_ALERT_LABELS``

Use ``TriageSettings()`` at runtime; tests pass overrides as keyword args.
"""

from __future__ import annotations

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class TriageSettings(BaseSettings):
    """Threshold configuration for ``ThresholdTriageEngine``.

    All float fields must satisfy ``0.0 <= borderline_low < borderline_high <= 1.0``.
    A misconfigured pair raises ``ValueError`` at instantiation so the server
    fails fast (rather than silently misrouting in production).
    """

    model_config = SettingsConfigDict(
        env_prefix="",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    # --- Borderline zone bounds -----------------------------------------------
    borderline_low: float = Field(
        default=0.3,
        alias="BORDERLINE_LOW",
        description=(
            "Inclusive lower bound of the borderline zone on P(offensive). "
            "prob_offensive <= this → SILENT."
        ),
    )
    borderline_high: float = Field(
        default=0.7,
        alias="BORDERLINE_HIGH",
        description=(
            "Inclusive upper bound of the borderline zone on P(offensive). "
            "prob_offensive >= this → ALERT_DIRECT."
        ),
    )

    # --- A/B baseline ---------------------------------------------------------
    baseline_threshold: float = Field(
        default=0.5,
        alias="TRIAGE_BASELINE_THRESHOLD",
        description=(
            "Midpoint cut on P(offensive) used when context_agent_enabled=False. "
            "prob_offensive >= this → ALERT_DIRECT, else → SILENT."
        ),
    )
    context_agent_enabled: bool = Field(
        default=True,
        alias="CONTEXT_AGENT_ENABLED",
        description=(
            "A/B switch. False = context-blind baseline; borderline cases are "
            "decided by baseline_threshold rather than escalated to the Context Agent."
        ),
    )

    # --- Label overrides ------------------------------------------------------
    always_escalate_labels: set[str] = Field(
        default={"violence"},
        alias="TRIAGE_ALWAYS_ESCALATE_LABELS",
        description=(
            "Labels that always escalate to the Context Agent regardless of "
            "confidence (e.g. 'violence'). Comma-separated in env."
        ),
    )
    always_alert_labels: set[str] = Field(
        default={"pornographic"},
        alias="TRIAGE_ALWAYS_ALERT_LABELS",
        description=(
            "Labels that always produce ALERT_DIRECT regardless of confidence "
            "(e.g. 'pornographic'). Comma-separated in env."
        ),
    )

    # --- Validators -----------------------------------------------------------
    @field_validator("borderline_low", "borderline_high", "baseline_threshold")
    @classmethod
    def _validate_in_unit_interval(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"Threshold must be in [0, 1], got {v}")
        return v

    @model_validator(mode="after")
    def _validate_borderline_order(self) -> "TriageSettings":
        if self.borderline_low >= self.borderline_high:
            raise ValueError(
                f"BORDERLINE_LOW ({self.borderline_low}) must be strictly less than "
                f"BORDERLINE_HIGH ({self.borderline_high}). "
                "Check TRIAGE_* env vars (triage.settings_invalid)."
            )
        return self
