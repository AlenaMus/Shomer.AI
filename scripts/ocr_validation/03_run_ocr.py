#!/usr/bin/env python3
"""
03_run_ocr.py — run Tesseract OCR (heb+eng) on all rendered images.

USAGE:
    python 03_run_ocr.py

OUTPUT:
    data/ocr_validation/ocr_outputs.jsonl
    {"id": "...", "style": "...", "original_text": "...", "ocr_text": "...",
     "image_path": "...", "confidence": 0.0-1.0 or null}

The script asserts that the Hebrew language pack is loaded — fails fast with a
clear error if `heb` is missing from Tesseract's available languages.
"""
import json
import sys
import time
from pathlib import Path

import pytesseract
from PIL import Image

# Force UTF-8 stdout on Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

REPO = Path(__file__).resolve().parents[2]
SENTENCES = REPO / "data" / "ocr_validation" / "sentences.jsonl"
IMG_ROOT = REPO / "data" / "ocr_validation" / "images"
OUTPUT = REPO / "data" / "ocr_validation" / "ocr_outputs.jsonl"

# Tesseract binary location — try common Windows paths first, fall back to PATH
TESSERACT_CANDIDATES = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
]

OCR_LANG = "heb+eng"
OCR_CONFIG = "--psm 6 -c preserve_interword_spaces=1"


def configure_tesseract():
    """Set pytesseract.pytesseract.tesseract_cmd to a found binary."""
    for p in TESSERACT_CANDIDATES:
        if Path(p).exists():
            pytesseract.pytesseract.tesseract_cmd = p
            return p
    # Fall back to PATH
    return "tesseract"


def verify_hebrew_pack():
    """FAIL-FAST: assert the heb language pack is installed."""
    try:
        langs = pytesseract.get_languages(config="")
    except Exception as e:
        sys.exit(f"ERROR: Could not query Tesseract languages: {e}\n"
                 f"Make sure Tesseract is installed and in PATH.")
    if "heb" not in langs:
        sys.exit(
            f"FATAL: Hebrew language pack ('heb') NOT installed in Tesseract.\n"
            f"  Available languages: {sorted(langs)}\n"
            f"  Fix: download heb.traineddata from:\n"
            f"    https://github.com/tesseract-ocr/tessdata_best/raw/main/heb.traineddata\n"
            f"  and place it in Tesseract's tessdata/ folder (usually "
            f"C:\\Program Files\\Tesseract-OCR\\tessdata\\)"
        )
    if "eng" not in langs:
        sys.exit(f"FATAL: English language pack ('eng') NOT installed. Available: {sorted(langs)}")
    print(f"[OK] Tesseract languages: heb + eng available (full list: {sorted(langs)})")


def run_ocr_on_image(img_path: Path) -> tuple[str, float]:
    """Returns (extracted_text, mean_confidence). Confidence is in [0, 1]."""
    img = Image.open(img_path)
    data = pytesseract.image_to_data(
        img, lang=OCR_LANG, config=OCR_CONFIG,
        output_type=pytesseract.Output.DICT,
    )
    # Filter words with non-empty text and non-negative confidence
    words = [w for w, c in zip(data["text"], data["conf"]) if c >= 0 and w.strip()]
    confs = [int(c) for c in data["conf"] if c >= 0]
    text = " ".join(words).strip()
    mean_conf = (sum(confs) / len(confs) / 100.0) if confs else 0.0
    return text, mean_conf


def main():
    if not SENTENCES.exists():
        sys.exit(f"ERROR: {SENTENCES} not found. Run 01_generate_sentences.py first.")

    tess_cmd = configure_tesseract()
    print(f"Tesseract binary: {tess_cmd}")
    try:
        version = pytesseract.get_tesseract_version()
        print(f"Tesseract version: {version}")
    except Exception as e:
        sys.exit(f"ERROR: Tesseract binary not callable: {e}")

    verify_hebrew_pack()

    records = [json.loads(line) for line in SENTENCES.read_text(encoding="utf-8").splitlines()]
    print(f"Sentences to OCR: {len(records)}\n")

    results = []
    t_start = time.time()
    for rec in records:
        img_path = IMG_ROOT / rec["style"] / f"{rec['id']}.png"
        if not img_path.exists():
            print(f"  [SKIP] {rec['id']}: image not found ({img_path})")
            results.append({
                **rec,
                "ocr_text": None,
                "confidence": None,
                "image_path": str(img_path.relative_to(REPO)),
                "error": "image_missing",
            })
            continue
        try:
            text, conf = run_ocr_on_image(img_path)
            results.append({
                "id": rec["id"],
                "style": rec["style"],
                "style_label": rec["style_label"],
                "original_text": rec["text"],
                "ocr_text": text,
                "confidence": round(conf, 3),
                "image_path": str(img_path.relative_to(REPO)),
                "offensive": rec.get("offensive", False),
                "category": rec.get("category", "none"),
            })
            # Spot-check print for smoke runs
            if len(records) <= 20:
                print(f"  [{rec['style_label']}] {rec['id']}: conf={conf:.2f}")
                print(f"        original: {rec['text']}")
                print(f"        ocr:      {text}")
                print()
        except Exception as e:
            print(f"  [FAIL] {rec['id']}: {e}")
            results.append({
                **rec,
                "ocr_text": None,
                "confidence": None,
                "image_path": str(img_path.relative_to(REPO)),
                "error": str(e),
            })

    elapsed = time.time() - t_start
    with OUTPUT.open("w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    n_ok = sum(1 for r in results if r.get("ocr_text"))
    n_fail = len(results) - n_ok
    print(f"[OK] OCR complete: {n_ok}/{len(results)} succeeded, {n_fail} failed")
    print(f"     Elapsed: {elapsed:.1f}s ({elapsed/len(results):.2f}s/image)")
    print(f"     Output:  {OUTPUT.relative_to(REPO)}")


if __name__ == "__main__":
    main()
