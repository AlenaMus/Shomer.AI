"""TesseractRunner — thin pytesseract wrapper.

Wraps ``pytesseract.image_to_data()`` and extracts:
- the joined text string
- mean per-word confidence (filtered: only words with conf >= 0)
- the language tag (the lang string passed to Tesseract — recorded as
  ``lang_detected`` because Tesseract does not auto-detect scripts)
- the number of non-empty word bounding boxes (``bbox_count``)

Tesseract is run in a blocking call; the caller (``TesseractOcrBackend``) is
responsible for wrapping this in ``asyncio.to_thread()``.

This class does NOT catch exceptions — callers must handle
``pytesseract.TesseractNotFoundError`` and ``pytesseract.TesseractError``.

Reference: docs/design/ocr/design.md §3.2 (TesseractRunner)
"""

from __future__ import annotations

import unicodedata

import pytesseract
from PIL import Image


# Unicode block ranges for script detection.
# We use a fast per-character approach rather than running Tesseract twice.
_HEBREW_RANGE_START = 0x0590
_HEBREW_RANGE_END = 0x05FF
_HEBREW_EXTENDED_START = 0xFB1D
_HEBREW_EXTENDED_END = 0xFB4F


def _detect_scripts(text: str) -> tuple[str, ...]:
    """Return which scripts are present in *text*.

    Returns a tuple of script tags from ``{"heb", "eng"}``.
    Hebrew is detected by Unicode block membership; English by the presence
    of ASCII letters.

    This is O(n) and deterministic — see LLD §11 Q3 for the alternative
    (running Tesseract twice per language).
    """
    has_heb = False
    has_eng = False
    for ch in text:
        cp = ord(ch)
        if not has_heb and (
            (_HEBREW_RANGE_START <= cp <= _HEBREW_RANGE_END)
            or (_HEBREW_EXTENDED_START <= cp <= _HEBREW_EXTENDED_END)
        ):
            has_heb = True
        if not has_eng and ch.isascii() and ch.isalpha():
            has_eng = True
        if has_heb and has_eng:
            break

    langs: list[str] = []
    if has_heb:
        langs.append("heb")
    if has_eng:
        langs.append("eng")
    return tuple(langs)


class TesseractRunner:
    """Run Tesseract on a preprocessed ``PIL.Image`` and parse the output.

    Parameters
    ----------
    lang:
        Tesseract language string, e.g. ``"heb+eng"``.
    psm:
        Page Segmentation Mode (``--psm`` flag).  Default 6 = uniform block
        of text; see design.md §3.2 for rationale.
    """

    TESSERACT_CONFIG_TEMPLATE = "--psm {psm} -c preserve_interword_spaces=1"

    def __init__(self, lang: str = "heb+eng", psm: int = 6) -> None:
        self.lang = lang
        self.psm = psm
        self._config = self.TESSERACT_CONFIG_TEMPLATE.format(psm=psm)

    def run(
        self, img: Image.Image
    ) -> tuple[str, float, tuple[str, ...], int, tuple[str, ...]]:
        """Extract text from a preprocessed image.

        Returns
        -------
        (text, mean_confidence, lang_detected, bbox_count, line_segments)

        - ``text``: joined, stripped word text; empty string when nothing
          detected.
        - ``mean_confidence``: mean of per-word confidences where conf >= 0,
          normalised to [0.0, 1.0].  Returns 0.0 when no confident words.
        - ``lang_detected``: tuple of detected script tags from the text.
        - ``bbox_count``: number of non-empty word bounding boxes.
        - ``line_segments``: one entry per detected text line (words grouped by
          Tesseract's ``(block_num, par_num, line_num)``), NFC-normalised and
          stripped.  Empty lines are dropped.  This lets message-granular
          consumers classify each chat line independently instead of one blob.

        Does NOT swallow exceptions — the caller must catch
        ``pytesseract.TesseractNotFoundError`` and
        ``pytesseract.TesseractError``.
        """
        data = pytesseract.image_to_data(
            img,
            lang=self.lang,
            config=self._config,
            output_type=pytesseract.Output.DICT,
        )

        # Each row in data is a detected element (page/block/para/line/word).
        # Filter to word-level entries: non-empty text and conf >= 0.  Track the
        # (block, paragraph, line) key per word so we can reconstruct lines.
        #
        # block_num/par_num/line_num are always present in real pytesseract
        # output; guard with .get() so partial mocks (and any pytesseract
        # version that omits them) degrade to a single line group instead of
        # raising KeyError.
        block_nums = data.get("block_num")
        par_nums = data.get("par_num")
        line_nums = data.get("line_num")
        has_line_keys = (
            block_nums is not None
            and par_nums is not None
            and line_nums is not None
        )

        words: list[str] = []
        confs: list[int] = []
        # Ordered grouping of words into lines keyed by (block, par, line).
        line_words: "dict[tuple[int, int, int], list[str]]" = {}
        n = len(data["text"])
        for i in range(n):
            word_text = data["text"][i]
            conf = data["conf"][i]
            # Tesseract uses -1 for non-word rows (block/para/line aggregates).
            if isinstance(conf, int) and conf >= 0 and str(word_text).strip():
                w = str(word_text).strip()
                words.append(w)
                confs.append(conf)
                key = (
                    (block_nums[i], par_nums[i], line_nums[i])
                    if has_line_keys
                    else (0, 0, 0)
                )
                line_words.setdefault(key, []).append(w)

        text = " ".join(words).strip()
        # Normalise Unicode (NFC) — important for Hebrew combining characters.
        text = unicodedata.normalize("NFC", text)

        # Reconstruct per-line segments in reading order (dict preserves
        # insertion order, which follows Tesseract's top-to-bottom scan).
        line_segments = tuple(
            seg
            for words_in_line in line_words.values()
            if (seg := unicodedata.normalize("NFC", " ".join(words_in_line).strip()))
        )

        if confs:
            # Tesseract returns confidence as 0–100 integers; normalise to [0,1].
            mean_conf = sum(confs) / len(confs) / 100.0
        else:
            mean_conf = 0.0

        lang_detected = _detect_scripts(text)
        bbox_count = len(words)

        return text, mean_conf, lang_detected, bbox_count, line_segments
