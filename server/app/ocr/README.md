# OCR Module

Extracts Hebrew and English text from chat screenshot images so the text
classifier can process image content through the same DictaBERT pipeline.

**In scope:** input validation, PIL preprocessing, Tesseract OCR, structured output.  
**Out of scope:** text classification, vision-LLM image understanding, on-device OCR.

---

## Package layout

```
server/app/ocr/
├── __init__.py          Re-exports OcrBackend (Protocol) + concrete adapters
├── protocol.py          OcrBackend Protocol — the only symbol the server core imports
├── settings.py          OcrSettings (pydantic-settings)
├── logging.py           Bound structlog logger "shomer.ocr"
├── metrics.py           Prometheus counters/histograms
├── preprocessor.py      ImagePreprocessor: resize → grayscale → adaptive threshold
├── tesseract_runner.py  TesseractRunner: thin pytesseract wrapper
├── tesseract_adapter.py TesseractOcrBackend: default OcrBackend adapter
├── stub_adapter.py      StubOcrBackend: deterministic test double
└── README.md            This file
```

The legacy code at `server/app/image_backends/ocr.py` is STILL PRESENT.
It conflates OCR with classification and is kept for reference only during
the parallel-safe migration described in `docs/design/ocr/design.md`.
A future task removes it; do not modify it or reference it from new code.

---

## OcrBackend Protocol

```python
class OcrBackend(Protocol):
    async def process(
        self,
        image_bytes: bytes,
        mime_type: str = "image/jpeg",
    ) -> OcrResult: ...

    async def health(self) -> tuple[HealthState, str]: ...

    @property
    def backend_name(self) -> str: ...
```

**Contract:**
- `process()` NEVER raises. Any failure returns `OcrResult(image_unreadable=True)`.
- p99 latency target: < 2 s (PRD §8.2).
- Extraction only — the adapter never calls the classifier.

---

## OcrResult schema

```python
@dataclass(frozen=True)
class OcrResult:
    extracted_text: str          # UTF-8, stripped; "" when no text found
    confidence: float            # mean per-word Tesseract confidence, 0.0–1.0
    lang_detected: tuple[str, ...] # e.g. ("heb",) or ("heb", "eng")
    bbox_count: int              # number of detected word bounding boxes
    image_unreadable: bool       # True when OCR found nothing meaningful
    backend: str                 # "tesseract" | "stub"
```

---

## Preprocessing pipeline

```
image_bytes (raw JPEG/PNG)
    ↓  ImagePreprocessor.preprocess()
    1. PIL.Image.open(BytesIO(image_bytes))
    2. Resize: cap long edge at preprocess_max_long_edge_px (default 2000 px)
               preserving aspect ratio — skipped if already within limit
    3. img.convert("L")          → grayscale
    4. adaptive threshold        → binary image (0/255 pixels)
       Gaussian-weighted mean per 31×31 block, threshold = mean - 10
       Implemented in numpy (no OpenCV dependency — see deviation note below)
    ↓  TesseractRunner.run()
    pytesseract.image_to_data(img, lang="heb+eng",
                              config="--psm 6 -c preserve_interword_spaces=1")
    Filter: words with conf >= 0; join into text string; NFC normalise
    Compute: mean confidence / 100 → [0.0, 1.0]
    Detect: Hebrew (Unicode block U+0590–U+05FF, U+FB1D–U+FB4F) and ASCII alpha
```

**Deviation from LLD §3.2:** The LLD references `cv2.adaptiveThreshold`.
This implementation uses a numpy Gaussian-weighted mean threshold that
produces equivalent output without the OpenCV dependency (saves ~50 MB).
The decision is deferred to Meeting 5 (LLD Q1). To switch to OpenCV, replace
`ImagePreprocessor._adaptive_threshold_numpy` with a `cv2.adaptiveThreshold`
call — the public `preprocess()` interface is unchanged.

---

## TESSERACT_CMD resolution

| Platform | Behaviour |
|---|---|
| Windows (default) | `settings.tesseract_cmd` = `C:\Program Files\Tesseract-OCR\tesseract.exe`. Set only when the file actually exists — avoids overwriting a valid `PATH` entry with a stale default. |
| Linux / WSL2 | Set `TESSERACT_CMD=` (empty string) or `TESSERACT_CMD=tesseract`. The path `C:\Program Files\...` does not exist so the env var is ignored and `PATH` is used. |
| CI (no Tesseract) | Leave `TESSERACT_CMD` unset. `health()` returns `HealthState.DOWN`; tests that need Tesseract skip automatically. |

Install on Windows (UB-Mannheim installer, includes Hebrew + English packs):

```powershell
winget install UB-Mannheim.TesseractOCR
```

Install on WSL2 / Ubuntu:

```bash
sudo apt-get install tesseract-ocr tesseract-ocr-heb tesseract-ocr-eng
```

---

## image_unreadable — signal semantics

| Condition | `image_unreadable` | `extracted_text` | Router action |
|---|---|---|---|
| Text found, bbox_count > 0 | `False` | non-empty | Pass to classifier |
| Tesseract finds no bounding boxes | `True` | `""` | OcrOnly: return `no_text`; Pipeline: try VisionBackend |
| PIL cannot decode bytes | `True` | `""` | Logged as `ocr_error` |
| Tesseract binary not found | `True` | `""` | Logged as `ocr_tesseract_unavailable` |
| Input > ocr_max_image_mb | `True` | `""` | Logged as `ocr_image_too_large` |
| MemoryError during preprocess | `True` | `""` | Logged as `ocr_error` |

---

## Environment variables (OcrSettings)

| Variable | Default | Description |
|---|---|---|
| `TESSERACT_CMD` | `C:\Program Files\Tesseract-OCR\tesseract.exe` | Absolute path to tesseract binary |
| `OCR_BACKEND` | `tesseract` | Active adapter name (informational) |
| `OCR_LANG` | `heb+eng` | Tesseract language packs |
| `OCR_MAX_IMAGE_MB` | `10` | Size guard (MB) |
| `OCR_TIMEOUT_S` | `180` | Hard timeout per call (seconds) |
| `OCR_PREPROCESS_MAX_LONG_EDGE_PX` | `2000` | Max long edge before resize |
| `TESSERACT_PSM` | `6` | Tesseract page segmentation mode |
| `OCR_MIN_CONFIDENCE` | `0.0` | Min mean word confidence to treat as readable |

---

## Structured log events

```json
{"event": "ocr_success", "module": "ocr", "backend": "tesseract",
 "latency_ms": 312, "bbox_count": 14, "confidence": 0.82,
 "lang_detected": ["heb", "eng"], "text_length": 87}

{"event": "ocr_no_text", "module": "ocr", "backend": "tesseract",
 "latency_ms": 198, "bbox_count": 0, "confidence": 0.0,
 "image_unreadable": true, "content_type": "image/jpeg"}

{"event": "ocr_tesseract_unavailable", "module": "ocr", "backend": "tesseract",
 "error": "TesseractNotFoundError", "fallback": "vision",
 "tesseract_cmd": "C:\\Program Files\\Tesseract-OCR\\tesseract.exe"}
```
