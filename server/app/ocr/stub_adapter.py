"""StubOcrBackend — deterministic test double for OcrBackend.

Returns a fixed ``OcrResult`` so tests can run without Tesseract installed
and without touching the filesystem.

This adapter is the recommended test default when the OCR result is not
the thing under test — inject it instead of ``TesseractOcrBackend`` to
keep tests fast and hermetic.

Reference: docs/design/ocr/design.md §2.5 (StubOcrBackend row)
"""

from __future__ import annotations

from ..schemas import HealthState, OcrResult


class StubOcrBackend:
    """Implements the ``OcrBackend`` Protocol with a fixed response.

    Always returns::

        OcrResult(
            extracted_text="STUB_OCR_TEXT",
            confidence=0.99,
            lang_detected=("heb",),
            bbox_count=1,
            image_unreadable=False,
            backend="stub",
        )

    Never raises.
    """

    async def process(
        self,
        image_bytes: bytes,
        mime_type: str = "image/jpeg",
    ) -> OcrResult:
        return OcrResult(
            extracted_text="STUB_OCR_TEXT",
            confidence=0.99,
            lang_detected=("heb",),
            bbox_count=1,
            image_unreadable=False,
            backend=self.backend_name,
        )

    async def health(self) -> tuple[HealthState, str]:
        return HealthState.OK, "stub always healthy"

    @property
    def backend_name(self) -> str:
        return "stub"
