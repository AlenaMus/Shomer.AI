"""Public port for the OCR module.

Reference: docs/design/ocr/design.md §2, §2.5.

This is EXTRACTION ONLY — the post-G-01 refactor explicitly separated OCR from
classification (the legacy ``server/app/image_backends/ocr.py`` conflated the
two). Concrete adapters: ``TesseractOcrBackend`` (default), ``EasyOcrBackend``,
``MlkitOcrBackend``, ``StubOcrBackend``.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..schemas import HealthState, OcrResult


@runtime_checkable
class OcrBackend(Protocol):
    """Image-to-text extraction port (Hebrew + English).

    Contract:
    - ``process()`` NEVER raises on an unreadable image. On any failure it
      returns ``OcrResult(extracted_text="", image_unreadable=True, ...)``.
    - p99 latency target: < 2 s (PRD §8.2).
    - Output is EXTRACTION ONLY. Calling code is responsible for then feeding
      ``extracted_text`` into the classifier — the backend never classifies.
    """

    async def process(
        self,
        image_bytes: bytes,
        mime_type: str = "image/jpeg",
    ) -> OcrResult: ...

    async def health(self) -> tuple[HealthState, str]: ...

    @property
    def backend_name(self) -> str:
        """e.g. ``"tesseract"``, ``"easyocr"``, ``"mlkit"``."""
        ...
