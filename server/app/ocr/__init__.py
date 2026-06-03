"""OCR module — Hebrew + English text extraction from images.

Public surface (port only — per docs/design/README.md §6):

    from server.app.ocr import OcrBackend      # the Protocol

Concrete adapters are NOT part of the public surface; import them by full
path inside ``server/app/main.py`` lifespan() only:

    from server.app.ocr.tesseract_adapter import TesseractOcrBackend
    from server.app.ocr.stub_adapter import StubOcrBackend

See docs/design/ocr/design.md.
"""

from __future__ import annotations

from .protocol import OcrBackend
from .stub_adapter import StubOcrBackend
from .tesseract_adapter import TesseractOcrBackend

__all__ = ["OcrBackend", "TesseractOcrBackend", "StubOcrBackend"]
