from __future__ import annotations

from .base import ImageClassifyResult, ImageProcessor


class StubImageProcessor(ImageProcessor):
    """Phase 1 placeholder. Acknowledges the upload, returns a fixed result.

    The point is to prove the wire (Android → multipart → FastAPI → JSON
    response) before any real image processing exists. The response shape
    matches what real backends will return in Phase 2.
    """

    async def process(
        self,
        image_bytes: bytes,
        content_type: str | None = None,
    ) -> ImageClassifyResult:
        return ImageClassifyResult(
            is_offensive=False,
            category="stub",
            confidence=0.0,
            extracted_text="",
            backend="stub",
            strategy="stub",
        )
