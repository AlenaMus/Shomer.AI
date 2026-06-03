from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class ImageClassifyResult:
    """Backend-agnostic classification result for an image.

    Mirrors the public API response shape minus the bookkeeping fields
    (``model``, ``latency_ms``) which the endpoint fills in.
    """

    is_offensive: bool
    category: str
    confidence: float
    extracted_text: str
    backend: str
    strategy: str


class ImageProcessor(ABC):
    """Strategy interface for classifying an image.

    Implementations decide *how* to turn bytes into a label — OCR + text
    classifier, a vision LLM, or a composite of both. The endpoint doesn't
    know or care which is active; that lets Phase 2 swap real backends in
    without changing the API.
    """

    @abstractmethod
    async def process(
        self,
        image_bytes: bytes,
        content_type: str | None = None,
    ) -> ImageClassifyResult:
        """Classify ``image_bytes`` and return the result.

        ``content_type`` is whatever the client sent (e.g. ``image/jpeg``).
        Backends may use it as a hint; they should not refuse on missing
        content type since multipart uploaders sometimes omit it.
        """
