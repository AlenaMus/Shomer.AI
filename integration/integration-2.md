# Integration Test 2 — Phase 2: Pluggable image backends (OCR + Vision)

**Phase reference:** `../plan-docs/POC_Plan.md` §4 Phase 2
**Decisions:** `../plan-docs/decisions/phase-2.decision.md`
**Status:** ready to execute once Tesseract is installed and the vision model is pulled
**Last updated:** 2026-05-23
**Goal:** prove that real image classification works — Hebrew text-bearing images are read via OCR and classified by the existing text model, real photos are classified directly by a vision LLM, and the strategy router correctly composes them.

---

## Architecture under test

```
[android_client]
   │   POST /classify-image  (+ optional ?strategy=...)
   ▼
[FastAPI :8000]
   │
   ├──> [ImageProcessor selected by IMAGE_STRATEGY or query param]
   │      ├── OcrOnly      (just Tesseract → text classifier)
   │      ├── VisionOnly   (just vision LLM)
   │      ├── Pipeline     (OCR first; vision fallback if no text)  ← default
   │      └── Parallel     (both concurrent; results combined)
   │
   ├──> [OcrBackend] Tesseract `heb` → extracted text → [text classifier] (Ollama, offensive-hebrew:v1)
   └──> [VisionBackend] base64 image + prompt → [Ollama, qwen2.5vl:7b]
```

What this test verifies, in order:

| # | What | Tests |
|---|---|---|
| 1 | Tesseract is reachable and reads Hebrew correctly | T1 |
| 2 | The OCR backend pipes extracted text through the existing text classifier | T2 |
| 3 | The vision backend returns a structured JSON verdict on real photos | T3 |
| 4 | Each strategy (`ocr_only` / `vision_only` / `pipeline` / `parallel`) routes correctly | T4–T7 |
| 5 | `?strategy=` query param overrides the env-var default | T8 |
| 6 | The audit log records the *actual* backend that ran (not just the strategy) | T9 |
| 7 | Android UI shows the right backend label in the result card on both targets | A1–A3 |

---

## Prerequisites

- [ ] integration-1 PASSED on both emulator and physical Huawei (closed via `results/integration-1/run-2026-05-23*.md`)
- [ ] Tesseract for Windows installed with the **Hebrew** language data pack
- [ ] Tesseract reachable: `tesseract --version` from PowerShell prints a version
- [ ] Vision model pulled in Ollama: `ollama list` shows `qwen2.5vl:7b` (or fall-back model — see §Open issues)
- [ ] Python deps refreshed (Phase 2 added `pytesseract`, `Pillow` to `requirements.txt`)
- [ ] `IMAGE_STRATEGY=pipeline` set in `server/.env` (or env var of choice for the test)

---

## Setup

### S1 — Verify Tesseract + Hebrew language data

```powershell
& "C:\Program Files\Tesseract-OCR\tesseract.exe" --version
& "C:\Program Files\Tesseract-OCR\tesseract.exe" --list-langs | Select-String "heb"
```

**Pass when:** version is printed (any 5.x+ release is fine) AND `heb` appears in the language list.

If `heb` is missing, the installer's optional language pack wasn't ticked — re-run the installer and select Hebrew under "Additional language data".

### S2 — Verify vision model is registered with Ollama

```powershell
ollama list | Select-String "qwen2.5vl|llava"
ollama run qwen2.5vl:7b "Describe what you can see in one sentence." # smoke test (no image — just confirms model loads)
```

**Pass when:** the model is listed and `ollama run` returns a coherent English sentence within ~30 s (first run loads the model, subsequent are fast).

### S3 — Refresh server venv

```powershell
cd C:\AIDevelopmentCourse\Shomer.AI\server
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -c "import pytesseract, PIL; print('pytesseract=', pytesseract.__version__, 'Pillow=', PIL.__version__)"
```

**Pass when:** pytesseract and Pillow versions print without ImportError.

### S4 — Start the server

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

**Pass when:** startup completes with no traceback. Hit `/health` from a second shell to confirm — should still return `status=ok, ollama_reachable=true`.

---

## Test procedure

For T1–T8, you'll need **two test images** under, say, `C:\Users\Dima\Pictures\shomer-test\`:
- `chat.jpg` — a screenshot containing readable Hebrew text (e.g. a WhatsApp screenshot or a social-media post — content does not matter, only that the OCR can extract Hebrew).
- `photo.jpg` — a real photograph with no visible text (e.g. a landscape, a coffee cup, anything).

Prepare them once at the start.

### T1 — Tesseract reads Hebrew from `chat.jpg`

```powershell
& "C:\Program Files\Tesseract-OCR\tesseract.exe" "C:\Users\Dima\Pictures\shomer-test\chat.jpg" stdout -l heb
```

**Pass when:** non-empty Hebrew text appears in the output (approximate match to what's in the image is fine; OCR perfection isn't required).

### T2 — OCR backend end-to-end via `?strategy=ocr_only`

```powershell
curl.exe -s -F "image=@C:\Users\Dima\Pictures\shomer-test\chat.jpg" "http://127.0.0.1:8000/classify-image?strategy=ocr_only"
```

**Pass when:** JSON response with:
- `backend: "ocr"`
- `strategy: "ocr_only"`
- `extracted_text` is non-empty Hebrew
- `category` is one of: `abusive`, `hate`, `violence`, `pornographic`, `non_offensive` (the real classifier returned a real verdict).

### T3 — Vision backend end-to-end via `?strategy=vision_only`

```powershell
curl.exe -s -F "image=@C:\Users\Dima\Pictures\shomer-test\photo.jpg" "http://127.0.0.1:8000/classify-image?strategy=vision_only"
```

**Pass when:** JSON response with:
- `backend: "vision"`
- `strategy: "vision_only"`
- `extracted_text: ""` (vision backend doesn't OCR)
- `category` is one of the valid categories
- `latency_ms` reflects vision-LLM time (likely 5–30 s for CPU; faster with GPU)

### T4 — Pipeline strategy picks OCR on chat screenshot

```powershell
curl.exe -s -F "image=@C:\Users\Dima\Pictures\shomer-test\chat.jpg" "http://127.0.0.1:8000/classify-image?strategy=pipeline"
```

**Pass when:** `backend: "ocr"`, `strategy: "pipeline"`, `extracted_text` non-empty. (Pipeline used OCR because text was extracted; vision was NOT called.)

### T5 — Pipeline strategy falls back to vision on real photo

```powershell
curl.exe -s -F "image=@C:\Users\Dima\Pictures\shomer-test\photo.jpg" "http://127.0.0.1:8000/classify-image?strategy=pipeline"
```

**Pass when:** `backend: "vision"`, `strategy: "pipeline"`, `extracted_text: ""`. (OCR found no text → fell back to vision.)

### T6 — Parallel strategy runs both

```powershell
curl.exe -s -F "image=@C:\Users\Dima\Pictures\shomer-test\chat.jpg" "http://127.0.0.1:8000/classify-image?strategy=parallel"
```

**Pass when:** `backend: "ocr+vision"`, `strategy: "parallel"`. Latency ≈ vision-only latency (parallel doesn't double; it's `max(ocr, vision)`).

### T7 — Default strategy from env var

Stop the server. Edit `server/.env` and temporarily set `IMAGE_STRATEGY=vision_only`. Restart server. Run:

```powershell
curl.exe -s -F "image=@C:\Users\Dima\Pictures\shomer-test\chat.jpg" http://127.0.0.1:8000/classify-image
# (no ?strategy= query param)
```

**Pass when:** `strategy: "vision_only"`. (Default came from env var.) Reset `.env` back to `IMAGE_STRATEGY=pipeline` after testing.

### T8 — Invalid strategy is rejected

```powershell
curl.exe -s -w "`nHTTP %{http_code}`n" -F "image=@C:\Users\Dima\Pictures\shomer-test\chat.jpg" "http://127.0.0.1:8000/classify-image?strategy=banana"
```

**Pass when:** HTTP 400 with detail mentioning the valid strategies.

### T9 — Audit log records actual backend used

After T2–T6 are done, on the PC:

```powershell
Get-Content "C:\AIDevelopmentCourse\Shomer.AI\server\logs\audit-$(Get-Date -Format yyyy-MM-dd).jsonl" -Encoding UTF8 -Tail 10 |
    ForEach-Object { $_ | ConvertFrom-Json } |
    Where-Object { $_.path -eq "/classify-image" } |
    Select-Object @{n='strategy';e={$_.response.body.strategy}},
                  @{n='backend';e={$_.response.body.backend}},
                  @{n='extracted_len';e={if ($_.response.body.extracted_text) {$_.response.body.extracted_text.Length} else {0}}},
                  latency_ms
```

**Pass when:** each row matches what you saw in T2–T6: ocr_only → ocr; vision_only → vision; pipeline → ocr or vision; parallel → ocr+vision.

### A1 — Android emulator: chat screenshot through default strategy

In the emulator, in the running app, switch to Image mode → Pick → choose a Hebrew chat screenshot from the emulator's gallery. Tap Classify.

**Pass when:** the result card shows `backend=ocr • strategy=pipeline`, the category is a real one (not `stub`), and `extracted_text` (if exposed in the UI) is non-empty.

### A2 — Android emulator: real photo through default strategy

Take a photo of a non-text scene with the camera, classify.

**Pass when:** result card shows `backend=vision • strategy=pipeline`.

### A3 — Physical Huawei: same two tests

Same A1 + A2 on the physical Huawei P20 Pro. Captures real-world image quality variance.

---

## Where results live

`results/integration-2/run-YYYY-MM-DD.md` (and `run-YYYY-MM-DD-physical-huawei-p20pro.md` for the physical-device target). See `results/README.md` for the format.

---

## Pass criteria

- [ ] **S1–S4** — setup green
- [ ] **T1** — Tesseract reads Hebrew
- [ ] **T2** — OCR backend returns real categories with `extracted_text`
- [ ] **T3** — Vision backend returns real categories
- [ ] **T4** — Pipeline uses OCR on chat screenshots
- [ ] **T5** — Pipeline falls back to vision on text-free photos
- [ ] **T6** — Parallel runs both concurrently
- [ ] **T7** — `IMAGE_STRATEGY` env var sets default
- [ ] **T8** — Invalid strategy → HTTP 400
- [ ] **T9** — Audit log reflects actual backend per request
- [ ] **A1** — Emulator: OCR via Pipeline on chat screenshot
- [ ] **A2** — Emulator: Vision via Pipeline on real photo
- [ ] **A3** — Physical Huawei: same as A1+A2

---

## Known limitations (by design at this phase)

- **OCR accuracy varies wildly with image quality.** Crisp screenshots → near-perfect. Photographed Hebrew signs with weird lighting → may fail. This is exactly what the Phase 4 architecture study quantifies.
- **Vision LLM Hebrew quality unknown.** Qwen2.5-VL is multilingual but not Hebrew-first. Some prompts may come back in English even though we asked for JSON. Phase 4 measures this too.
- **Vision inference is slow on CPU.** 5–30 s per request typical without a GPU. Expected.
- **Parallel strategy doubles the load on Ollama** (two concurrent requests). On a single-GPU box this serializes anyway, so the win is smaller than the name suggests.

---

## Open issues / fall-backs

- **Vision model name varies across Ollama versions.** The decision was `qwen2-vl:7b` but Ollama's registry currently exposes it as `qwen2.5vl:7b` (newer release). If `ollama pull qwen2.5vl:7b` also fails, fall back to `llava:7b` and update `VISION_MODEL_NAME` in `server/.env` accordingly — and amend `plan-docs/decisions/phase-2.decision.md` D3 with the substitution.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `TesseractNotFoundError` | `pytesseract` can't find `tesseract.exe` | Set `TESSERACT_CMD` in `server/.env` to the absolute path; restart server |
| OCR returns empty for an image you know has text | Hebrew language pack not installed | Re-run installer, tick Hebrew under "Additional language data" |
| OCR returns garbled English chars for Hebrew | `lang="heb"` not passed, or pack missing | Check `OcrBackend.__init__(lang="heb")` and verify with `tesseract --list-langs` |
| Vision call hangs > 60 s | Cold-start of the vision model | First request loads the model into memory; can take 30–90 s on CPU. Subsequent calls are faster |
| `pull model manifest: file does not exist` | Wrong model name | Try the alternative tags listed in §Open issues |
| HTTP 422 from `/classify-image` | Vision LLM returned non-JSON | Lower the temperature in `OllamaClient` (already 0.1); or sharpen the `VISION_PROMPT` |
| Pipeline uses vision when text IS present | OCR returned empty due to image preprocessing | Check `chat.jpg` opens correctly; try a clean Hebrew screenshot first |

---

## After this passes — what's next

`integration-3.md` / POC Phase 3: train the real fine-tuned Hebrew text classifier and swap it for the stand-in. After Phase 3, the OCR pipeline returns real fine-tuned-model classifications instead of stand-in Qwen2.5 ones.
