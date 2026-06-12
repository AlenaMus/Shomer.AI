"""Confirm the screenshot-blob dilution hypothesis.

Runs the real OCR on the test screenshot, then classifies:
  (a) the whole OCR blob  (what /v1/monitor/image currently sends)
  (b) each line in isolation
and prints label + prob_offensive for each.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path("server").resolve()))

from app.ocr.tesseract_adapter import TesseractOcrBackend
from app.ocr.settings import OcrSettings
from app.classifier.huggingface_adapter import HuggingFaceClassifier
from app.classifier.settings import ClassifierSettings


async def main():
    img = Path("scripts/_chat_screenshot.png").read_bytes()

    ocr = TesseractOcrBackend(OcrSettings())
    res = await ocr.process(img, "image/png")
    blob = res.extracted_text.strip()
    print("=== RAW OCR TEXT ===")
    print(repr(blob))
    print(f"({len(blob)} chars)\n")

    clf = HuggingFaceClassifier(ClassifierSettings())
    if hasattr(clf, "warmup"):
        try:
            await clf.warmup()
        except Exception:
            pass

    async def classify(label, text):
        r = await clf.classify(text)
        prob_off = r.confidence if r.is_offensive else 1 - r.confidence
        print(f"[{label}] label={r.label:14s} is_off={r.is_offensive} "
              f"conf={r.confidence:.3f} prob_off={prob_off:.3f}  text={text!r}")

    print("=== CLASSIFY: whole blob (current behavior) ===")
    await classify("BLOB", blob)

    print("\n=== CLASSIFY: each line in isolation ===")
    for line in blob.splitlines():
        line = line.strip()
        if line:
            await classify("LINE", line)


asyncio.run(main())
