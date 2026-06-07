"""ContextAgentSettings — Pydantic-settings for the Context Agent module.

Reference: docs/design/context_agent/design.md §6.2 (Config table).
All CONTEXT_AGENT_* env vars are read from the environment / .env file.
Secrets (OPENAI_API_KEY, ANTHROPIC_API_KEY) are typed as SecretStr so their
values are never accidentally logged.
"""

from __future__ import annotations

import structlog
from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = structlog.get_logger("shomer.context_agent.settings")


class ContextAgentSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="",          # env vars use their literal names (OPENAI_API_KEY etc.)
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Toggle for the A/B experiment (False = context-blind baseline)
    context_agent_enabled: bool = True

    # LLM secrets — marked SecretStr so values never appear in repr / logs
    openai_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = None      # GEMINI_API_KEY (Google AI Studio)

    # LLM model selection
    context_agent_primary_llm: str = "gpt-4o-mini"
    context_agent_fallback_llm: str = "haiku-4.5"
    gemini_model: str = "gemini-2.5-flash"        # GEMINI_MODEL override

    # Timing
    context_agent_timeout_s: float = 5.0

    # Context window
    context_agent_max_history_turns: int = 5

    # Storage paths
    context_agent_audit_db: str = "server/audit.db"
    slang_lexicon_path: str = "server/data/slang_lexicon.json"
    token_prices_path: str = "server/app/context_agent/token_prices.yaml"

    # Daily budgets
    context_agent_daily_token_budget: int = 100_000
    context_agent_daily_usd_budget: float = 0.50

    # ------------------------------------------------------------------ #
    # Validation                                                           #
    # ------------------------------------------------------------------ #

    @model_validator(mode="after")
    def warn_missing_keys(self) -> "ContextAgentSettings":
        """Emit a WARNING (not error) when keys are missing while enabled."""
        if not self.context_agent_enabled:
            return self
        if self.openai_api_key is None:
            logger.warning(
                "context_agent_settings_warning",
                detail="OPENAI_API_KEY is not set; MockLlmClient will be used as fallback",
            )
        if self.anthropic_api_key is None:
            logger.warning(
                "context_agent_settings_warning",
                detail="ANTHROPIC_API_KEY is not set; Haiku fallback will be unavailable",
            )
        return self

    @field_validator("context_agent_timeout_s")
    @classmethod
    def timeout_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("context_agent_timeout_s must be > 0")
        return v

    @field_validator("context_agent_daily_usd_budget")
    @classmethod
    def budget_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("context_agent_daily_usd_budget must be > 0")
        return v
