# Shomer.AI POC Plan

**Status:** draft, 2026-05-23 (revised same day)
**Owner:** Alona
**Companion docs:** `Shomer_AI_Project_Proposal.docx` (scope), `Shomer_AI_10_Meeting_Plan.docx` (schedule)

---

## 1. Goal

End-to-end working demo where an Android client sends **text or an image** to a local FastAPI server, and the server returns whether the content is offensive — using Hebrew-tuned models running locally via Ollama, with a **pluggable image-processing layer** so multiple approaches (OCR, vision LLM, hybrid) can be swapped, combined, and compared as part of the project's neural-network architecture study.

The early focus is **getting the wire working end-to-end** for both text and image payloads. *How* an image is processed (OCR vs vision LLM vs both) is the **academic contribution** that gets explored after the plumbing is solid.

Success looks like a screen recording of:
- Typing a Hebrew sentence → label appears.
- Taking/selecting a screenshot of Hebrew text → label appears.
- Taking/selecting a real photo (scene/object/person) → label appears.

---

## 2. Scope

**In scope**
- Hebrew **text** classification (typed in app).
- **Image** classification — both:
  - *Text-bearing images* (screenshots, signs, social-media posts) — handled via OCR → Hebrew text classifier.
  - *Real images* (photos of scenes/objects/people) — handled via vision LLM (multimodal model).
- A **pluggable backend layer** on the server so OCR and vision models can be swapped or combined.
- Local-only runtime (Android emulator or phone on same Wi-Fi → PC server → Ollama on PC).

**Out of scope (POC)**
- Audio / video input.
- Cloud deployment, multi-user accounts, persistence beyond a single request.
- Production hardening, rate limiting, auth.

---

## 3. Architecture (target state)

```
┌────────────────────┐    HTTP(S)     ┌─────────────────────────────────┐    HTTP    ┌────────────────────┐
│  android_client    │ ─────────────▶ │  server (FastAPI)               │ ─────────▶ │  Ollama :11434     │
│  • text input      │                │  POST /classify      (text)     │            │  • text classifier │
│  • image picker    │                │  POST /classify-image (image)   │            │  • vision LLM      │
└────────────────────┘                │            │                    │            └────────────────────┘
                                      │            ▼                    │
                                      │   ┌─────────────────────┐       │
                                      │   │  ImageProcessor     │       │
                                      │   │  (strategy router)  │       │
                                      │   └─┬─────────────┬─────┘       │
                                      │     │             │             │
                                      │     ▼             ▼             │
                                      │  OcrBackend   VisionBackend     │
                                      │  (Tesseract)  (Ollama VL)       │
                                      └─────────────────────────────────┘
```

**ImageProcessor interface** (Python `abc.ABC` in `server/app/image_backends/base.py`):
```python
class ImageProcessor(ABC):
    @abstractmethod
    def process(self, image_bytes: bytes) -> ClassifyResult: ...
```

**Initial backends** (each is one `ImageProcessor` implementation):
- `OcrBackend` — Tesseract (`pytesseract`, lang `heb`) → calls the existing text classifier internally.
- `VisionBackend` — multimodal LLM via Ollama (`qwen2-vl:7b` or `llava`), one-shot prompt asking for offensive/not + category.

**Strategies that compose backends** (config + query-param):

| Strategy | Behaviour |
|---|---|
| `ocr_only` | OCR backend only. |
| `vision_only` | Vision backend only. |
| `pipeline` | OCR first; if extracted text is empty or low-confidence, fall back to vision. |
| `parallel` | Run OCR and vision concurrently; combine (OR offensive flags, weighted confidence). |

The active default is a config knob (`server/.env` → `IMAGE_STRATEGY=...`); the response always echoes which strategy was used so the client and the study can see it.*done-when** check, **risk**. Don't start Phase N+1 until Phase N's done-when is true.

### Phase 0 — Recover the text path on the stand-in model (post-migration smoke test)

**Objective:** the text-only stack from before the 2026-05-23 migration still works end-to-end.

**Steps**
1. Recreate the server venv (broken absolute paths after migration):
   `Remove-Item -Recurse -Force server\.venv ; cd server ; python -m venv .venv ; .\.venv\Scripts\Activate.ps1 ; pip install -r requirements.txt`
2. `ollama pull qwen2.5:7b-instruct`
3. `ollama create offensive-hebrew:v1 -f server\Modelfile.standin`
4. `uvicorn app.main:app --host 0.0.0.0 --port 8000` (from `server/`).
5. Smoke test with curl: `/health`, then `POST /classify` with a Hebrew sentence.
6. Open `android_client/` in Android Studio (from the new path), run on emulator, set server URL `http://10.0.2.2:8000/`, classify "שלום, מה שלומך?".

**Done when:** the Android app receives a label from the server using the stand-in model.

**Risk:** Gradle caches still pointing at the old path. *Mitigation:* File → Invalidate Caches & Restart.

---

### Phase 1 — Connection plumbing for text **and** image (image backend is a stub)

**Objective:** the wire works for both input types. The server can *receive* an image and *return* a `ClassifyResult` — the image isn't actually processed yet, just acknowledged. This is the "initial step" the user asked for.

**What changes**

*In `android_client/`:*
- New UI: input-mode toggle (Text | Image), with a text field on one side and an image picker + camera capture on the other.
- Photo Picker API (`ActivityResultContracts.PickVisualMedia`) for gallery; `TakePicture` for camera; `READ_MEDIA_IMAGES` / `CAMERA` permission flow (Android 13+ photo picker needs no read permission).
- Client-side compression: longest side ≤ 1600 px, JPEG quality ~80, target ≤ 1 MB.
- New Retrofit method: `@Multipart fun classifyImage(@Part image: MultipartBody.Part): Response<ClassifyResponse>`.

*In `server/`:*
- New endpoint `POST /classify-image` accepting `multipart/form-data` (field name `image`).
- `app/image_backends/base.py` — `ImageProcessor` ABC + `ClassifyResult` dataclass.
- `app/image_backends/stub.py` — returns `{ is_offensive: false, category: "stub", confidence: 0.0, extracted_text: "", backend: "stub", strategy: "stub" }`.
- Wire the endpoint to the stub backend via DI/config so it's swappable in Phase 2 with no API change.
- Update `app/schemas.py` to include `extracted_text`, `backend`, `strategy` fields in the image response.
- Add `python-multipart` to `requirements.txt`.

**Done when:**
- `curl -F image=@anything.jpg http://localhost:8000/classify-image` returns the stub response.
- The Android app can pick an image OR capture one, tap Classify, and see the stub response on screen (label = "stub", but the round-trip is proven).
- The text path from Phase 0 still works unchanged.

**Risk:** Android permission UX. *Mitigation:* prefer the photo-picker (no permission on Android 13+). *Risk:* multipart vs JSON. *Mitigation:* multipart is the default; JSON+base64 is the alternative if multipart causes pain on Android.

---

### Phase 2 — Pluggable image backends: OCR + Vision + strategy router

**Objective:** swap the stub for real image-processing backends and the strategy router.

**What changes (in `server/app/image_backends/`):**
- `ocr.py` — `OcrBackend`. Uses `pytesseract` with `lang="heb"`; extracts text; if non-empty, calls the existing text classifier; if empty, returns `category="no_text"`. (Tesseract Hebrew language pack must be installed locally — document this in `server/README.md`.)
- `vision.py` — `VisionBackend`. Uses `ollama` Python client with a multimodal model (default `qwen2-vl:7b`). One-shot prompt: classify offensive/not + category, JSON output.
- `strategies.py` — `OcrOnly`, `VisionOnly`, `Pipeline`, `Parallel` composite processors.
- `app/main.py` — read `IMAGE_STRATEGY` env var, build the processor at startup, inject into the endpoint.
- `POST /classify-image?strategy=...` query param overrides the default per-request (useful for the architecture study).

**Done when:**
- `POST /classify-image?strategy=ocr_only` on a Hebrew screenshot returns a label derived from OCR + text classifier.
- `POST /classify-image?strategy=vision_only` on a real photo returns a label from the vision LLM.
- `pipeline` and `parallel` both return valid responses and the response says which backend(s) ran.

**Risk:** Tesseract Hebrew accuracy on photos vs screenshots. *Mitigation:* this is exactly what Phase 4 measures — don't tune now.
**Risk:** vision LLM weak on Hebrew. *Mitigation:* same — measure in Phase 4. If it's hopeless, swap default to `llava` or larger qwen2-vl.

---

### Phase 3 — Train the real Hebrew text classifier

**Objective:** stand-in `qwen2.5:7b-instruct` is replaced by the actual fine-tuned model.

**Steps** (in WSL2 with CUDA GPU)
1. `cd /mnt/c/AIDevelopmentCourse/Shomer.AI/training` ; venv + `pip install -r requirements.txt`.
2. `python prepare_data.py`
3. `python train_lora.py --config configs/train.yaml`
4. `python evaluate.py --adapter outputs/offensive-hebrew-lora`
5. `python export_gguf.py --adapter outputs/offensive-hebrew-lora --out ../server/offensive-hebrew.gguf --llama-cpp-dir ../../llama.cpp`
6. Windows: `ollama rm offensive-hebrew:v1 ; ollama create offensive-hebrew:v1 -f server\Modelfile`
7. Rerun Phase 0 and Phase 2 smoke tests.

**Done when:** `evaluate.py` reports macro-F1 ≥ 0.70 on the balanced split AND the Android app gets responses from the real fine-tuned model on text and on text-bearing images (the OcrBackend now feeds the real model).

**Risk:** OOM / weak F1. *Mitigation:* `training/README.md` VRAM notes; consider DictaLM 2.0 as alternative base.

---

### Phase 4 — Neural-network architecture study (the academic contribution)

**Objective:** decide, with numbers, which image-processing strategy belongs in the final system — and document the reasoning.

**What changes**
- Curate a small labeled eval set, ~80–120 images split into buckets:
  - *text-heavy clean* (screenshots, ~30)
  - *text-heavy noisy* (photographed signs, ~20)
  - *visual-only* (no readable text, ~30)
  - *mixed* (real scene with embedded text, ~20)
  - *adversarial* (mocked attempts to evade — distorted text, sarcasm, code-switch, ~20)
- Eval harness `training/eval_images.py`: runs all 4 strategies, records precision/recall/F1/latency per bucket.
- Compare against a text-only baseline (the Phase 3 model on extracted-text-from-image via OCR with no vision fallback).
- Write findings into a new `plan-docs/Architecture_Study.md` — comparison table, error analysis, recommendation for default strategy and any tuning.

**Done when:**
- Architecture_Study.md exists with real numbers and a recommended default strategy.
- `server/.env` default `IMAGE_STRATEGY` set to that recommendation.

**Risk:** label noise on the eval set. *Mitigation:* keep it small enough to double-check by hand.

---

### Phase 5 — Promote `server/sdk/` from placeholder to real client library (optional within POC)

**Objective:** stop hand-rolling HTTP in `android_client/`; let future clients reuse the same library.

**What changes**
- Decide: OpenAPI-generated vs hand-written.
- Implement Kotlin module under `server/sdk/kotlin/`: `ShomerApiClient.classifyText(...)` and `classifyImage(..., strategy=...)`.
- Refactor `android_client/` onto it.

**Done when:** all HTTP in `android_client/` goes through `server/sdk/kotlin/`. No raw Retrofit interfaces in the client.

---

### Phase 6 — Evaluation & write-up

**Objective:** academic deliverable matches the actual POC.

**What changes**
- Combine `training/evaluate.py` (text) + `training/eval_images.py` (Phase 4) into a single reproducible benchmark.
- Numbers + screenshots + short demo video.
- Update `plan-docs/Shomer_AI_Project_Proposal.docx` results section, citing `plan-docs/Architecture_Study.md`.
- Mentor checkpoint per `Shomer_AI_10_Meeting_Plan.docx`.

**Done when:** the project proposal has real numbers and the demo can be reproduced cold from the README.

---

## 5. Open decisions

| # | Decision | When | Default |
|---|---|---|---|
| D1 | Image-processing strategy default — `ocr_only` / `vision_only` / `pipeline` / `parallel` | resolved in Phase 4 with data | `pipeline` until measured |
| D2 | OCR engine — Tesseract vs PaddleOCR vs cloud OCR | Phase 2 | Tesseract (offline, free, Hebrew pack `heb` exists) |
| D3 | Vision LLM — `qwen2-vl:7b` vs `llava` vs `bakllava` | Phase 2 | `qwen2-vl:7b` (same family as the text base; OK Hebrew rumored) |
| D4 | Text-classifier base model — Qwen 2.5 7B vs DictaLM 2.0 | Phase 3 | Qwen 2.5 7B (matches `training/configs/train.yaml`) |
| D5 | SDK shape — generated vs hand-written | Phase 5 | Hand-written |
| D6 | Image upload format — multipart vs base64 JSON | Phase 1 | Multipart |
| D7 | Image compression target (mobile-side) | Phase 1 | longest side 1600 px, JPEG ~80, ≤ 1 MB |

---

## 6. Risks (project-level)

- **OCR weak on real-world Hebrew photos.** *Mitigation:* Phase 4 quantifies; vision backend exists as fallback.
- **Vision LLM weak on Hebrew.** *Mitigation:* Phase 4; can swap model in `Modelfile`-style config without touching app code.
- **Training never converges to a useful F1.** *Mitigation:* stand-in model is the demo fallback; Phase 4 still produces a meaningful study even with a weak text classifier.
- **No CUDA GPU available.** *Mitigation:* Phase 3 slips; Phases 0–2 and 4 still runnable using stand-in + vision LLM only.
- **Workspace was reorganized on 2026-05-23.** IDE caches, venv, hard-coded paths — Phase 0 explicitly verifies all of these before anything else.

---

## 7. Tracking

- [ ] **Phase 0** — text path on stand-in, end-to-end (post-migration smoke test)
- [ ] **Phase 1** — connection plumbing for text + image (stub image backend)
- [ ] **Phase 2** — pluggable image backends (OCR + Vision) + strategy router
- [ ] **Phase 3** — train real Hebrew text classifier (macro-F1 ≥ 0.70)
- [ ] **Phase 4** — architecture study: compare backends, pick default strategy
- [ ] **Phase 5** — *(optional)* promote `server/sdk/` to real shared client lib
- [ ] **Phase 6** — evaluation + write-up

---

## 8. What "initial step" means right now

The next concrete unit of work after this plan is approved is **Phase 0 followed by Phase 1**:
1. Recover the text path on the stand-in model (Phase 0).
2. Add image upload from Android + a stub `/classify-image` on the server (Phase 1).

After that, the academic-interesting work (Phases 2 and 4) builds on a known-good wire.
