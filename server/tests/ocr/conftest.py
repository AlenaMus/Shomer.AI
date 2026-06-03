"""Pytest fixtures for the OCR test suite.

Fixture images are GENERATED at test time using PIL.ImageDraw so the
repository carries no binary blobs.  Generation is deterministic and fast
(< 10 ms per image).

Fixture inventory
-----------------
``hebrew_png_bytes``
    Tiny PNG with a short Hebrew sentence rendered in a system font.

``english_png_bytes``
    Tiny PNG with a short English sentence.

``mixed_png_bytes``
    PNG with both Hebrew and English text on separate lines.

``blank_png_bytes``
    Solid white 100×100 PNG — Tesseract returns zero bounding boxes.

``garbage_bytes``
    32 random bytes — not a valid image format.

``oversized_bytes``
    ``11 MB`` of zero bytes prepended with a valid PNG header byte so it
    passes the ``bytes`` type check but fails the size guard.

Notes
-----
- The fixtures use PIL's built-in default font.  Hebrew characters may not
  render as distinct glyphs (the default font is Latin-only), but the images
  are valid PNGs that Tesseract can attempt to process.
- For integration tests that require real Hebrew OCR output, use the actual
  Tesseract binary with the ``heb`` language pack installed (marked with
  ``pytest.mark.tesseract``).
"""

from __future__ import annotations

from io import BytesIO

import pytest
from PIL import Image, ImageDraw, ImageFont


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_text_png(
    text: str,
    width: int = 400,
    height: int = 100,
    bg: str = "white",
    fg: str = "black",
) -> bytes:
    """Render *text* into a PNG and return the raw bytes."""
    img = Image.new("RGB", (width, height), color=bg)
    draw = ImageDraw.Draw(img)
    # Use PIL's built-in bitmap font — no external font files needed.
    try:
        font = ImageFont.load_default(size=20)
    except TypeError:
        # Older Pillow versions do not support size= kwarg
        font = ImageFont.load_default()
    draw.text((10, 30), text, fill=fg, font=font)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def hebrew_png_bytes() -> bytes:
    """PNG containing a short Hebrew sentence (Unicode only; glyphs may
    not render with PIL default font, but the PNG is valid)."""
    return _make_text_png("שלום עולם — בדיקת OCR")


@pytest.fixture(scope="session")
def english_png_bytes() -> bytes:
    """PNG containing a short English sentence."""
    return _make_text_png("Hello World — OCR test")


@pytest.fixture(scope="session")
def mixed_png_bytes() -> bytes:
    """PNG containing both Hebrew and English text."""
    return _make_text_png("Hello שלום Test בדיקה")


@pytest.fixture(scope="session")
def blank_png_bytes() -> bytes:
    """Solid white 100×100 PNG — no text content."""
    img = Image.new("RGB", (100, 100), color="white")
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture(scope="session")
def garbage_bytes() -> bytes:
    """32 random bytes — not a valid image."""
    return bytes(range(32))


@pytest.fixture(scope="session")
def oversized_bytes() -> bytes:
    """11 MB of null bytes — exceeds the 10 MB default limit."""
    return b"\x00" * (11 * 1024 * 1024)


@pytest.fixture(scope="session")
def empty_bytes() -> bytes:
    """Zero bytes — definitely not a valid image."""
    return b""
