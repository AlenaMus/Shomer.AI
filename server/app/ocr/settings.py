"""OcrSettings — environment-driven configuration for the OCR module.

All settings are loaded from environment variables (or a .env file).
No secret values live here — these are tuning knobs only.

Reference: docs/design/ocr/design.md §6.2
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class OcrSettings(BaseSettings):
    """Pydantic-settings model for the OCR module.

    Environment variable names are derived from the field names (uppercase).
    The prefix is empty so names match exactly: ``TESSERACT_CMD``,
    ``OCR_BACKEND``, ``OCR_LANG``, etc.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Path to the Tesseract binary.
    # Default is the UB-Mannheim Windows installer path.
    # On Linux/WSL2 set to empty string or "tesseract" to use PATH.
    tesseract_cmd: str = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

    # Which adapter to wire at startup (informational — actual wiring is in
    # server/app/main.py lifespan(); this field is for observability / health).
    ocr_backend: str = "tesseract"

    # Language pack(s) passed to Tesseract ``-l`` flag.
    # "heb+eng" handles Israeli teen chat code-switching.
    ocr_lang: str = "heb+eng"

    # Maximum upload size in megabytes (backup to Gatekeeper's 4 MB limit).
    ocr_max_image_mb: int = 10

    # Hard timeout for a single OCR call in seconds.
    ocr_timeout_s: int = 180

    # Preprocessing: maximum long-edge in pixels before resize.
    # Images already smaller than this are passed through unchanged.
    preprocess_max_long_edge_px: int = 2000

    # Tesseract ``--psm`` (page segmentation mode).
    # 6 = assume a single uniform block of text; optimal for chat screenshot
    # regions.  See design.md §3.2 for rationale.
    tesseract_psm: int = 6

    # Mean per-word confidence threshold below which the result is treated as
    # "no text" (image_unreadable=True).
    ocr_min_confidence: float = 0.0
