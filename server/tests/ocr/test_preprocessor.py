"""Unit tests for ImagePreprocessor.

All tests are synchronous (ImagePreprocessor has no async methods) and do not
require Tesseract to be installed.
"""

from __future__ import annotations

from io import BytesIO

import pytest
from PIL import Image

from app.ocr.preprocessor import ImagePreprocessor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_png(width: int, height: int, color: str = "white") -> bytes:
    img = Image.new("RGB", (width, height), color=color)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_output_is_grayscale() -> None:
    """Preprocessed image must be mode 'L' (grayscale)."""
    prep = ImagePreprocessor()
    png = _make_png(200, 200)
    result = prep.preprocess(png)
    assert result.mode == "L", f"Expected mode 'L', got '{result.mode}'"


def test_small_image_not_upscaled() -> None:
    """Images with long edge < max_long_edge_px must not be resized larger."""
    prep = ImagePreprocessor(max_long_edge_px=2000)
    png = _make_png(100, 100)
    result = prep.preprocess(png)
    assert max(result.size) <= 100, (
        f"Image was upscaled; size={result.size}"
    )


def test_large_image_is_downsized() -> None:
    """Long edge of a 3000×2000 image must be capped at max_long_edge_px."""
    max_px = 500
    prep = ImagePreprocessor(max_long_edge_px=max_px)
    png = _make_png(3000, 2000)
    result = prep.preprocess(png)
    assert max(result.size) <= max_px, (
        f"Image not downsized; size={result.size}"
    )


def test_aspect_ratio_preserved() -> None:
    """Resize must preserve the original aspect ratio (within 1 pixel)."""
    prep = ImagePreprocessor(max_long_edge_px=300)
    png = _make_png(600, 200)  # 3:1 ratio
    result = prep.preprocess(png)
    w, h = result.size
    # Original aspect = 3.0; result should be close
    ratio = w / h
    assert abs(ratio - 3.0) < 0.05, (
        f"Aspect ratio changed: {ratio:.3f} (expected ~3.0)"
    )


def test_invalid_image_bytes_raises() -> None:
    """Garbage bytes must raise PIL.UnidentifiedImageError (not silently pass)."""
    from PIL import UnidentifiedImageError

    prep = ImagePreprocessor()
    with pytest.raises(UnidentifiedImageError):
        prep.preprocess(b"not an image at all")


def test_empty_bytes_raises() -> None:
    """Empty bytes must raise (PIL cannot open zero-byte stream)."""
    from PIL import UnidentifiedImageError

    prep = ImagePreprocessor()
    with pytest.raises((UnidentifiedImageError, OSError)):
        prep.preprocess(b"")


def test_odd_block_size_required() -> None:
    """threshold_block_size must be odd — even values raise ValueError."""
    with pytest.raises(ValueError, match="odd"):
        ImagePreprocessor(threshold_block_size=32)


def test_exact_long_edge_unchanged() -> None:
    """Image whose long edge equals max_long_edge_px must not be resized."""
    prep = ImagePreprocessor(max_long_edge_px=400)
    png = _make_png(400, 300)
    result = prep.preprocess(png)
    # Long edge may still differ slightly due to grayscale conversion, but
    # width and height must stay the same.
    assert result.size == (400, 300), f"Unexpected size: {result.size}"


def test_output_is_binary_image() -> None:
    """Adaptive threshold should produce predominantly 0 and 255 pixel values."""
    import numpy as np

    prep = ImagePreprocessor()
    # Use a simple black-text-on-white image
    png = _make_png(100, 50, color="white")
    result = prep.preprocess(png)
    arr = np.array(result)
    unique_vals = set(arr.flatten().tolist())
    # After binary threshold, only 0 and 255 should appear.
    assert unique_vals.issubset({0, 255}), (
        f"Non-binary pixel values found: {unique_vals - {0, 255}}"
    )
