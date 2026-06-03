"""OCR backend — extract Hebrew text from an image, then classify the text.

Uses Tesseract via ``pytesseract`` for OCR. If the image has no readable text
(typical for real photos with no text content), returns a synthetic
``category="no_text"`` result so the caller (a strategy router) can decide
whether to fall back to a vision backend.
"""

from __future__ import annotations

import asyncio
from io import BytesIO

import pytesseract
from PIL import Image

from ..classifier import classify_text
from ..ollama_client import OllamaClient
from .base import ImageClassifyResult, ImageProcessor


class OcrBackend(ImageProcessor):
    """Pipeline: image bytes → Tesseract → text → existing text classifier."""

    def __init__(
        self,
        text_ollama: OllamaClient,
        tesseract_cmd: str | None = None,
        lang: str = "heb",
    ):
        """``tesseract_cmd`` is the absolute path to ``tesseract.exe`` on Windows;
        pass ``None`` to rely on PATH (Linux/macOS default).
        ``lang`` is the Tesseract language code — ``heb`` for Hebrew. Use ``heb+eng``
        if you expect mixed Hebrew + English screenshots.
        """
        self.text_ollama = text_ollama
        self.lang = lang
        if tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

    async def process(
        self,
        image_bytes: bytes,
        content_type: str | None = None,
    ) -> ImageClassifyResult:
        # PIL + pytesseract are blocking; run on a worker thread so the event
        # loop isn't held up. Decoding and OCR can take 200ms–1s combined.
        text = await asyncio.to_thread(self._run_ocr, image_bytes)

        if not text:
            return ImageClassifyResult(
                is_offensive=False,
                category="no_text",
                confidence=1.0,
                extracted_text="",
                backend="ocr",
                strategy="ocr",
            )

        parsed = await classify_text(self.text_ollama, text)
        return ImageClassifyResult(
            is_offensive=parsed["is_offensive"],
            category=parsed["category"],
            confidence=parsed["confidence"],
            extracted_text=text,
            backend="ocr",
            strategy="ocr",
        )

    def _run_ocr(self, image_bytes: bytes) -> str:
        img = Image.open(BytesIO(image_bytes))
        # `image_to_string` returns text including newlines and trailing whitespace;
        # strip so "" reliably means "no text found".
        raw = pytesseract.image_to_string(img, lang=self.lang)
        return raw.strip()
