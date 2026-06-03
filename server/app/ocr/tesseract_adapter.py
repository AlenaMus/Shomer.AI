"""TesseractOcrBackend — the default OcrBackend adapter.

Implements ``OcrBackend`` (protocol.py) using Tesseract via ``pytesseract``.

Pipeline
--------
``process(image_bytes)``
    1. Size guard — reject bytes > ``ocr_max_image_mb`` MB immediately.
    2. Run ``ImagePreprocessor.preprocess()`` in a thread:
       resize → grayscale → adaptive threshold.
    3. Run ``TesseractRunner.run()`` in the same thread:
       pytesseract.image_to_data → (text, confidence, lang, bbox_count).
    4. Assemble ``OcrResult``.
    5. Emit metrics + structured log.

``health()``
    Probe Tesseract by calling ``pytesseract.get_tesseract_version()``.
    Returns ``HealthState.OK`` if it succeeds, ``HealthState.DOWN`` otherwise.

Error contract
--------------
``process()`` NEVER raises.  Any exception from PIL, pytesseract, or
preprocessing is caught and returned as
``OcrResult(extracted_text="", image_unreadable=True, ...)``.

Reference: docs/design/ocr/design.md §2.5, §3.2
"""

from __future__ import annotations

import asyncio
import os
import time
from typing import TYPE_CHECKING

import pytesseract
from PIL import UnidentifiedImageError

from ..schemas import HealthState, OcrResult
from .logging import logger
from .metrics import (
    ocr_confidence,
    ocr_errors_total,
    ocr_extracted_chars,
    ocr_image_unreadable_total,
    ocr_latency_seconds,
    ocr_requests_total,
)
from .preprocessor import ImagePreprocessor
from .settings import OcrSettings
from .tesseract_runner import TesseractRunner

if TYPE_CHECKING:
    pass


class TesseractOcrBackend:
    """OcrBackend adapter that wraps Tesseract via pytesseract.

    Parameters
    ----------
    settings:
        ``OcrSettings`` instance.  If not provided, one is constructed from
        environment variables (production default).
    """

    def __init__(self, settings: OcrSettings | None = None) -> None:
        self._settings = settings or OcrSettings()
        self._max_bytes = self._settings.ocr_max_image_mb * 1024 * 1024

        # Set the Tesseract binary path on Windows.
        # Only set it when the path actually exists to avoid overwriting a
        # valid PATH entry with a stale default.
        cmd = self._settings.tesseract_cmd
        if cmd and os.path.isfile(cmd):
            pytesseract.pytesseract.tesseract_cmd = cmd

        self._preprocessor = ImagePreprocessor(
            max_long_edge_px=self._settings.preprocess_max_long_edge_px,
        )
        self._runner = TesseractRunner(
            lang=self._settings.ocr_lang,
            psm=self._settings.tesseract_psm,
        )

    # ------------------------------------------------------------------
    # OcrBackend Protocol
    # ------------------------------------------------------------------

    async def process(
        self,
        image_bytes: bytes,
        mime_type: str = "image/jpeg",
    ) -> OcrResult:
        """Extract text from *image_bytes*.

        Always returns an ``OcrResult``.  On any failure, returns with
        ``image_unreadable=True`` and logs the exception at ERROR level.
        """
        t0 = time.perf_counter()
        try:
            result = await asyncio.to_thread(
                self._process_sync, image_bytes, mime_type
            )
        except Exception as exc:
            # Defensive catch-all.  _process_sync should already catch
            # everything, but belt-and-suspenders here.
            latency = time.perf_counter() - t0
            error_type = type(exc).__name__
            ocr_errors_total.labels(
                backend=self.backend_name, error_type=error_type
            ).inc()
            ocr_image_unreadable_total.labels(backend=self.backend_name).inc()
            ocr_requests_total.labels(
                backend=self.backend_name, outcome="error"
            ).inc()
            ocr_latency_seconds.labels(backend=self.backend_name).observe(
                latency
            )
            logger.error(
                "ocr_unexpected_error",
                module="ocr",
                backend=self.backend_name,
                error=error_type,
                detail=str(exc),
                latency_ms=round(latency * 1000),
            )
            return OcrResult(
                extracted_text="",
                confidence=0.0,
                lang_detected=(),
                bbox_count=0,
                image_unreadable=True,
                backend=self.backend_name,
            )
        return result

    async def health(self) -> tuple[HealthState, str]:
        """Return ``(HealthState, detail_string)``.

        Probes Tesseract by calling ``pytesseract.get_tesseract_version()``.
        """
        try:
            version = await asyncio.to_thread(
                pytesseract.get_tesseract_version
            )
            return HealthState.OK, f"tesseract {version}"
        except Exception as exc:
            return HealthState.DOWN, f"Tesseract unavailable: {exc}"

    @property
    def backend_name(self) -> str:
        return "tesseract"

    # ------------------------------------------------------------------
    # Synchronous implementation (runs in worker thread)
    # ------------------------------------------------------------------

    def _process_sync(self, image_bytes: bytes, mime_type: str) -> OcrResult:
        """Full synchronous OCR pipeline.  Called via ``asyncio.to_thread``."""
        t0 = time.perf_counter()

        # --- size guard ---
        if len(image_bytes) > self._max_bytes:
            latency = time.perf_counter() - t0
            logger.warning(
                "ocr_image_too_large",
                module="ocr",
                backend=self.backend_name,
                size_bytes=len(image_bytes),
                max_bytes=self._max_bytes,
                latency_ms=round(latency * 1000),
            )
            ocr_errors_total.labels(
                backend=self.backend_name, error_type="ImageTooLarge"
            ).inc()
            ocr_image_unreadable_total.labels(backend=self.backend_name).inc()
            ocr_requests_total.labels(
                backend=self.backend_name, outcome="error"
            ).inc()
            ocr_latency_seconds.labels(backend=self.backend_name).observe(
                latency
            )
            return OcrResult(
                extracted_text="",
                confidence=0.0,
                lang_detected=(),
                bbox_count=0,
                image_unreadable=True,
                backend=self.backend_name,
            )

        # --- preprocessing ---
        try:
            preprocessed = self._preprocessor.preprocess(image_bytes)
        except UnidentifiedImageError as exc:
            return self._unreadable_result(
                t0, "UnidentifiedImageError", str(exc)
            )
        except MemoryError as exc:
            return self._unreadable_result(t0, "MemoryError", str(exc))
        except Exception as exc:
            return self._unreadable_result(t0, type(exc).__name__, str(exc))

        # --- tesseract ---
        try:
            text, confidence, lang_detected, bbox_count = self._runner.run(
                preprocessed
            )
        except pytesseract.TesseractNotFoundError as exc:
            latency = time.perf_counter() - t0
            logger.error(
                "ocr_tesseract_unavailable",
                module="ocr",
                backend=self.backend_name,
                error="TesseractNotFoundError",
                fallback="vision",
                tesseract_cmd=self._settings.tesseract_cmd,
                latency_ms=round(latency * 1000),
            )
            ocr_errors_total.labels(
                backend=self.backend_name,
                error_type="TesseractNotFoundError",
            ).inc()
            ocr_image_unreadable_total.labels(backend=self.backend_name).inc()
            ocr_requests_total.labels(
                backend=self.backend_name, outcome="error"
            ).inc()
            ocr_latency_seconds.labels(backend=self.backend_name).observe(
                latency
            )
            return OcrResult(
                extracted_text="",
                confidence=0.0,
                lang_detected=(),
                bbox_count=0,
                image_unreadable=True,
                backend=self.backend_name,
            )
        except Exception as exc:
            return self._unreadable_result(t0, type(exc).__name__, str(exc))

        latency = time.perf_counter() - t0

        # --- assemble result ---
        image_unreadable = bbox_count == 0 or not text

        if image_unreadable:
            ocr_image_unreadable_total.labels(backend=self.backend_name).inc()
            ocr_requests_total.labels(
                backend=self.backend_name, outcome="no_text"
            ).inc()
            logger.info(
                "ocr_no_text",
                module="ocr",
                backend=self.backend_name,
                latency_ms=round(latency * 1000),
                bbox_count=0,
                confidence=0.0,
                image_unreadable=True,
                content_type=mime_type,
            )
        else:
            ocr_requests_total.labels(
                backend=self.backend_name, outcome="success"
            ).inc()
            logger.info(
                "ocr_success",
                module="ocr",
                backend=self.backend_name,
                latency_ms=round(latency * 1000),
                bbox_count=bbox_count,
                confidence=round(confidence, 4),
                lang_detected=list(lang_detected),
                text_length=len(text),
            )

        # --- metrics ---
        ocr_latency_seconds.labels(backend=self.backend_name).observe(latency)
        ocr_confidence.labels(backend=self.backend_name).observe(confidence)
        ocr_extracted_chars.labels(backend=self.backend_name).observe(
            len(text)
        )

        return OcrResult(
            extracted_text=text,
            confidence=confidence,
            lang_detected=lang_detected,
            bbox_count=bbox_count,
            image_unreadable=image_unreadable,
            backend=self.backend_name,
        )

    def _unreadable_result(
        self, t0: float, error_type: str, detail: str
    ) -> OcrResult:
        """Build an ``image_unreadable=True`` result after an exception."""
        latency = time.perf_counter() - t0
        logger.error(
            "ocr_error",
            module="ocr",
            backend=self.backend_name,
            error=error_type,
            detail=detail,
            latency_ms=round(latency * 1000),
        )
        ocr_errors_total.labels(
            backend=self.backend_name, error_type=error_type
        ).inc()
        ocr_image_unreadable_total.labels(backend=self.backend_name).inc()
        ocr_requests_total.labels(
            backend=self.backend_name, outcome="error"
        ).inc()
        ocr_latency_seconds.labels(backend=self.backend_name).observe(latency)
        return OcrResult(
            extracted_text="",
            confidence=0.0,
            lang_detected=(),
            bbox_count=0,
            image_unreadable=True,
            backend=self.backend_name,
        )
