"""Configuration for the Frontline Classifier module.

Reference: docs/design/classifier/design.md §6.2.

Every env-var key matches `server/.env.example` (NO prefix — fields use their
own names directly so the existing flat .env stays the source of record).
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# Versions the module knows how to satisfy. Anything else is rejected at boot.
KNOWN_MODEL_VERSIONS: frozenset[str] = frozenset(
    {
        "v1.0-standin",
        "v1.1-dictabert",
        "v1.1-dictabert-base-untrained",
    }
)

# Calibration methods the ConfidenceCalibrator understands.
KNOWN_CALIBRATION_METHODS: frozenset[str] = frozenset({"none", "temperature", "isotonic"})


class ClassifierSettings(BaseSettings):
    """Settings for the classifier module.

    Read directly from environment (no prefix). The flat var names match
    `server/.env.example` so the same .env feeds every module.

    Use ``ClassifierSettings()`` to load from env; tests can pass overrides
    via keyword arguments (e.g. ``ClassifierSettings(borderline_low=0.4)``).
    """

    model_config = SettingsConfigDict(
        env_prefix="",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    # --- Adapter selection -----------------------------------------------------
    model_version: str = Field(
        default="v1.0-standin",
        alias="CLASSIFIER_MODEL_VERSION",
        description="v1.0-standin (Ollama+Qwen) | v1.1-dictabert (HF DictaBERT).",
    )

    # --- DictaBERT (HF adapter) ------------------------------------------------
    dictabert_model_path: Path = Field(
        default=Path("server/models/dictabert-offensive"),
        alias="DICTABERT_MODEL_PATH",
        description="Local fine-tuned checkpoint dir; if missing, fall back to HF base.",
    )
    dictabert_hf_name: str = Field(
        default="dicta-il/dictabert",
        alias="DICTABERT_HF_NAME",
        description="HuggingFace model name used when DICTABERT_MODEL_PATH is missing.",
    )

    # --- Timeout & borderline thresholds --------------------------------------
    classifier_timeout_s: float = Field(
        default=60.0,
        alias="CLASSIFIER_TIMEOUT_S",
        description="Per-call timeout for the underlying inference path.",
    )
    borderline_low: float = Field(
        default=0.3,
        alias="BORDERLINE_LOW",
        description="Inclusive lower bound of the borderline zone.",
    )
    borderline_high: float = Field(
        default=0.7,
        alias="BORDERLINE_HIGH",
        description="Inclusive upper bound of the borderline zone.",
    )

    # --- Calibration -----------------------------------------------------------
    calibration_method: str = Field(
        default="none",
        alias="CALIBRATION_METHOD",
        description='"none" | "temperature" | "isotonic"',
    )
    calibration_pkl_path: Path = Field(
        default=Path("server/models/calibrator.pkl"),
        alias="CALIBRATION_PKL_PATH",
        description="Fitted calibrator file (sklearn IsotonicRegression or float T).",
    )

    # --- Ollama fallback (v1.0-standin) ---------------------------------------
    ollama_url: str = Field(
        default="http://localhost:11434",
        alias="OLLAMA_URL",
        description="Ollama API base URL.",
    )
    ollama_model: str = Field(
        default="offensive-hebrew:v1",
        alias="OLLAMA_MODEL",
        description="Ollama model tag for the v1.0-standin adapter.",
    )

    # --- Validators ------------------------------------------------------------
    @field_validator("model_version")
    @classmethod
    def _validate_model_version(cls, v: str) -> str:
        if v not in KNOWN_MODEL_VERSIONS:
            raise ValueError(
                f"Unknown CLASSIFIER_MODEL_VERSION={v!r}. "
                f"Known versions: {sorted(KNOWN_MODEL_VERSIONS)}"
            )
        return v

    @field_validator("calibration_method")
    @classmethod
    def _validate_calibration_method(cls, v: str) -> str:
        if v not in KNOWN_CALIBRATION_METHODS:
            raise ValueError(
                f"Unknown CALIBRATION_METHOD={v!r}. "
                f"Known methods: {sorted(KNOWN_CALIBRATION_METHODS)}"
            )
        return v

    @field_validator("borderline_low", "borderline_high")
    @classmethod
    def _validate_borderline(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError(f"Borderline threshold must be in [0, 1], got {v}")
        return v

    @field_validator("borderline_high")
    @classmethod
    def _validate_borderline_order(cls, v: float, info) -> float:
        low = info.data.get("borderline_low")
        if low is not None and v < low:
            raise ValueError(
                f"borderline_high ({v}) must be >= borderline_low ({low})"
            )
        return v
