"""Strategy router — composes :class:`OcrBackend` and :class:`VisionBackend`.

Each strategy is itself an :class:`ImageProcessor`, so the endpoint code
treats them uniformly. The strategy chosen at startup (via the
``IMAGE_STRATEGY`` env var) becomes ``app.state.image_processor``;
the ``?strategy=`` query param picks a different one per-request.

The four strategies (see ``../../plan-docs/POC_Plan.md`` for rationale):

- ``ocr_only``  — always OCR; useful when you know inputs are chat screenshots.
- ``vision_only`` — always vision; useful for real photos / memes.
- ``pipeline``  — OCR first; if no text found, fall back to vision.
- ``parallel``  — run both concurrently and combine results.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace

import pytesseract

from .base import ImageClassifyResult, ImageProcessor
from .ocr import OcrBackend
from .vision import VisionBackend

logger = logging.getLogger(__name__)

# Tesseract can be absent (not installed / not on PATH) or misconfigured
# (e.g. missing the 'heb' language pack). In a composite strategy that already
# has a vision fallback, that should *degrade to vision* — not 500 the whole
# request. ``ocr_only`` deliberately does NOT swallow these: if you explicitly
# asked for OCR and it's unavailable, you want to know.
OCR_UNAVAILABLE = (pytesseract.TesseractNotFoundError, pytesseract.TesseractError)


async def _try_ocr(
    ocr: OcrBackend, image_bytes: bytes, content_type: str | None
) -> ImageClassifyResult | None:
    """Run OCR, returning ``None`` (instead of raising) when the OCR engine
    itself is unavailable, so the caller can fall back to vision."""
    try:
        return await ocr.process(image_bytes, content_type)
    except OCR_UNAVAILABLE as exc:
        logger.warning("OCR unavailable, falling back to vision: %s", exc)
        return None


class OcrOnly(ImageProcessor):
    def __init__(self, ocr: OcrBackend):
        self.ocr = ocr

    async def process(self, image_bytes: bytes, content_type: str | None = None) -> ImageClassifyResult:
        result = await self.ocr.process(image_bytes, content_type)
        return replace(result, strategy="ocr_only")


class VisionOnly(ImageProcessor):
    def __init__(self, vision: VisionBackend):
        self.vision = vision

    async def process(self, image_bytes: bytes, content_type: str | None = None) -> ImageClassifyResult:
        result = await self.vision.process(image_bytes, content_type)
        return replace(result, strategy="vision_only")


class Pipeline(ImageProcessor):
    """OCR first; fall back to vision only if no text was extracted.

    Rationale: OCR is ~10–30× faster than a vision LLM call. Most "offensive
    image" inputs in our target use case (Hebrew social-media moderation) are
    actually text-bearing screenshots. Pay the vision cost only when there
    really is no text to classify.
    """

    def __init__(self, ocr: OcrBackend, vision: VisionBackend):
        self.ocr = ocr
        self.vision = vision

    async def process(self, image_bytes: bytes, content_type: str | None = None) -> ImageClassifyResult:
        ocr_result = await _try_ocr(self.ocr, image_bytes, content_type)
        # Fall back to vision when OCR found no text OR the OCR engine is missing.
        if ocr_result is not None and ocr_result.extracted_text:
            return replace(ocr_result, strategy="pipeline")
        vision_result = await self.vision.process(image_bytes, content_type)
        return replace(vision_result, strategy="pipeline")


class Parallel(ImageProcessor):
    """Run OCR and vision concurrently; merge their verdicts.

    Combination rule:
    - ``is_offensive`` = OR of the two backends (either one flagging is enough).
    - ``category`` = from whichever backend declared the more specific
      offensive verdict; if both agree on non-offensive, pick the higher
      confidence. If they disagree on category but both flag offensive, the
      higher-confidence one wins.
    - ``extracted_text`` = OCR's text (vision contributes nothing here).
    - Latency = max(OCR, vision) ≈ vision's latency (vision dominates).
    """

    def __init__(self, ocr: OcrBackend, vision: VisionBackend):
        self.ocr = ocr
        self.vision = vision

    async def process(self, image_bytes: bytes, content_type: str | None = None) -> ImageClassifyResult:
        ocr_result, vision_result = await asyncio.gather(
            _try_ocr(self.ocr, image_bytes, content_type),
            self.vision.process(image_bytes, content_type),
        )

        # OCR engine unavailable → fall back to the vision verdict alone.
        if ocr_result is None:
            return replace(vision_result, strategy="parallel")

        is_offensive = ocr_result.is_offensive or vision_result.is_offensive

        # Pick whose category + confidence to surface.
        if ocr_result.is_offensive and vision_result.is_offensive:
            chosen = ocr_result if ocr_result.confidence >= vision_result.confidence else vision_result
        elif ocr_result.is_offensive:
            chosen = ocr_result
        elif vision_result.is_offensive:
            chosen = vision_result
        else:
            chosen = ocr_result if ocr_result.confidence >= vision_result.confidence else vision_result

        return ImageClassifyResult(
            is_offensive=is_offensive,
            category=chosen.category,
            confidence=chosen.confidence,
            extracted_text=ocr_result.extracted_text,
            backend="ocr+vision",
            strategy="parallel",
        )
