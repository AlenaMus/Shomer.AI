# Phase 2 — Decisions

**Phase:** POC Phase 2 (pluggable image backends + strategy router)
**Decided on:** 2026-05-23
**Decided by:** Alona, with options presented by Claude

Captures the explicit decisions made when prompted during Phase 2 design.
Format per decision: **Question → Choice → Why → Alternatives considered → When to revisit**.

---

## D-Phase2-Architecture — Image-processing approach

**Question:** Should the server process images as text (OCR), as visual content (vision LLM), or both?

**Choice:** **Both — dual-track pluggable architecture.** The server hosts an OCR backend AND a vision LLM backend behind a common `ImageProcessor` interface, with a strategy router that picks which runs per request.

**Why:** The project's input space genuinely covers two distinct cases — chat screenshots (text-in-image, perfectly suited to OCR) and real photographs (visual content needing a vision model). Forcing one approach to do both would either be slow (vision-only for screenshots) or blind (OCR-only for photos). The architecture also positions Phase 4 (architecture study) to A/B all combinations on a labelled set — that comparison is the academic contribution.

**Alternatives considered:**
- *OCR-only:* simpler, faster, but misses non-textual offensive imagery.
- *Vision-only:* covers everything but slow (~5–15 s per call) and weaker at extracting Hebrew text from screenshots than dedicated OCR.

**Revisit:** if Phase 4 architecture study shows one approach reliably beats the other on the labelled dataset, simplify the production architecture.

---

## D2 — OCR engine

**Question:** Which OCR engine to use for Hebrew text extraction?

**Choice:** **Tesseract** (via `pytesseract`), language pack `heb`.

**Why:**
- Free, offline, open-source — fits the local-only POC model.
- Mature Hebrew language pack (`heb`); 20+ years of development; well-documented Hebrew accuracy on clean text (chat screenshots are the bread-and-butter Tesseract case).
- ~5-minute Windows installer with optional language data download.
- Easy to swap later — both engines sit behind the same `OcrBackend` interface contract.

**Alternatives considered:**
- *PaddleOCR:* deep-learning-based, often better on photographed signs / messy real-world text, but Hebrew is not a primary language for Baidu and the install brings the PaddlePaddle framework (~1 GB extra). Lower confidence on Hebrew chat screenshots.
- *Cloud OCR (Google Cloud Vision, Azure):* highest accuracy but breaks the "local POC" property and costs per request; not aligned with the academic POC scope.

**Revisit:** if Phase 4 measurements show Tesseract Hebrew accuracy below threshold (≤ 0.70 F1 on the eval set's text-heavy buckets), evaluate PaddleOCR as a drop-in replacement.

---

## D3 — Vision LLM

**Question:** Which multimodal LLM for visual image classification?

**Choice:** **`qwen2.5vl:7b`** via Ollama. *(Decision was originally `qwen2-vl:7b` but the Ollama registry's current name for the Qwen vision 7B model is `qwen2.5vl:7b` — same model family, newer release. Updated 2026-05-23 after `ollama pull qwen2-vl:7b` returned "model manifest does not exist".)*

**Why:**
- Newer model (2024) with explicit multilingual training that includes non-English including Middle-Eastern languages — better Hebrew handling than English-first models.
- Same model family as the text classifier (Qwen 2.5 7B) — consistent biases and failure modes; cleaner academic story to tell.
- 7B param size fits comfortably on consumer GPUs and runs on CPU (slow but possible).
- ~5 GB download — same order of magnitude as alternatives.

**Alternatives considered:**
- *LLaVA (1.5 / 1.6):* original open multimodal LLM, larger community/tutorials, but English-heavy training. Weaker on Hebrew.
- *BakLLaVA:* LLaVA variant on Mistral base — same English-bias issue.
- *Cloud multimodal APIs (GPT-4V, Gemini Vision, Claude):* highest quality but defeats the local-only POC and costs per request.

**Revisit:** if Phase 4 shows Qwen2-VL hallucinates or refuses Hebrew images frequently, try `llava:13b` or a newer Qwen2-VL release.

---

## D-default-strategy — Default image-processing strategy

**Question:** Which strategy should the server run by default?

**Choice:** **`pipeline`** — OCR first; fall back to vision LLM if no text was extracted.

**Why:**
- Hits the cost/quality sweet spot for the project's mixed-input use case. OCR is ~10–30× faster than vision LLM inference; running it first and only paying the vision cost when needed is empirically the best default for our problem.
- Defensible academically: easy to explain ("cheap first, expensive only when needed").
- Configurable: client can override per-request via `?strategy=` for the Phase 4 study; default lives in `IMAGE_STRATEGY` env var so changing it requires no code change.

**Alternatives considered:**
- *`ocr_only`:* fastest but blind to real photos.
- *`vision_only`:* covers everything but always slow.
- *`parallel`:* highest recall but always pays 2× the cost (vision dominates latency, ~5–15 s per request).

**Revisit:** Phase 4 architecture study will measure all four strategies on a labelled image set. If `parallel` wins by enough margin on precision/recall to justify the latency hit, switch default. If `ocr_only` is enough for the eval bucket the user actually cares about, simplify.

---

## D-default-strategy-demo-override — Temporary `stub` default for the feasibility demo

**Decided on:** 2026-05-24
**Question:** With Tesseract not installed (and vision slow / unverified on this machine), what should the deployed default image strategy be for the feasibility demo?

**Choice:** **Temporarily set `IMAGE_STRATEGY=stub`** in `server/.env`. Every image request returns a clean 200 (`backend=stub`), proving the Android↔server image wire without depending on OCR or the vision model.

**Why:** The POC's job is to prove the wire works end-to-end (Step 0 feasibility). A stub response is sufficient evidence for that and is fully reliable; real classification accuracy is not part of this step. This avoids both the Tesseract-missing 500 and the ~10–15 s vision latency during a live demo.

**Alternatives considered:**
- *`pipeline` (intended default):* now degrades to vision when OCR is missing (see `strategies.py` fix on 2026-05-24), but every image then pays ~10–15 s vision latency — fragile for a live demo.
- *`vision_only`:* works, but same latency concern and depends on the vision model staying loaded.
- *Install Tesseract + `heb` now:* the proper fix for real OCR, but more setup than the demo needs.

**Revisit:** flip back to `pipeline` in `.env` once Tesseract (`winget install UB-Mannheim.TesseractOCR` + Hebrew pack) and/or the vision model are verified. This does **not** override D-default-strategy — `pipeline` remains the intended product default.

---

## Tooling decisions (no user prompt — captured here so future-me sees the trail)

- **Tesseract install path on Windows:** `C:\Program Files\Tesseract-OCR\tesseract.exe` (configurable via `TESSERACT_CMD` env var).
- **Vision timeout:** 180 s separate from text classifier's 60 s. Vision inference on CPU can take 30–60 s easily; using the same timeout as text would cause spurious 504s.
- **`/classify-image` failure modes:** `httpx.TimeoutException` → HTTP 504; `httpx.HTTPError` → HTTP 502; anything else (e.g. `pytesseract.TesseractNotFoundError`) → HTTP 500 with the exception message. Andy debugging defects from this list go to `integration/integration-2.md`.

---

## Linked artifacts

- Implemented in: `server/app/image_backends/{ocr,vision,strategies}.py`, `server/app/main.py`, `server/.env`.
- Tested by: `integration/integration-2.md` (to be drafted), results under `integration/results/integration-2/`.
- Plan source: `plan-docs/POC_Plan.md` §4 Phase 2 + §5 Open decisions D2 / D3.
