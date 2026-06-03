"""Pluggable image-processing backends.

Each backend implements :class:`ImageProcessor` (see :mod:`.base`). The active
processor is chosen at app startup via the ``IMAGE_STRATEGY`` env var so the
HTTP endpoint stays unaware of which combination is running.

Phase 1 introduced :class:`StubImageProcessor` for end-to-end wire testing.
Phase 2 adds the real backends:

- :class:`OcrBackend` — Tesseract → text classifier.
- :class:`VisionBackend` — multimodal LLM via Ollama.

And the strategies that compose them:

- :class:`OcrOnly`, :class:`VisionOnly`, :class:`Pipeline`, :class:`Parallel`.
"""

from .base import ImageClassifyResult, ImageProcessor
from .ocr import OcrBackend
from .strategies import OcrOnly, Parallel, Pipeline, VisionOnly
from .stub import StubImageProcessor
from .vision import VisionBackend

__all__ = [
    "ImageClassifyResult",
    "ImageProcessor",
    "OcrBackend",
    "OcrOnly",
    "Parallel",
    "Pipeline",
    "StubImageProcessor",
    "VisionBackend",
    "VisionOnly",
]
