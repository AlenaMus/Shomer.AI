# Decision: Screenshot → OCR capture for open-chat messages

Status: Accepted (2026-06-09) · Scope: Android `android_client/` + server `server/app/`

## Question
WhatsApp exposes **open-chat message bubbles** neither to the accessibility tree nor
to notifications (verified 2026-06-09 — see the monitoring-client commit). How do we
capture messages the child reads/receives *while actively viewing a chat*, without
(a) sending duplicate screenshots and (b) overloading the server with images?

## Choice
Capture the screen with **MediaProjection** on the device, **de-duplicate and throttle
on-device**, and upload only novel JPEGs to a new **`POST /v1/monitor/image`** endpoint
that **OCRs the image (existing Tesseract `heb+eng`) and reuses the existing monitor
ingest pipeline** (dedup → classify → triage → flag) by synthesizing a single-event batch.

### Wire contract — `POST /v1/monitor/image` (multipart/form-data)
Auth: `Authorization: Bearer <child device_token>` — same rule as `/v1/monitor/events`
(role must be `child`, `child_id` must match the token).

Fields:
- `image`     — file, JPEG
- `child_id`  — str
- `session_id`— str
- `client_msg_id` — str (UUID4, idempotency key)
- `captured_at`   — float (epoch seconds)
- `direction` — str, default `"screen"`

Behavior:
1. OCR via `app.state.ocr.process(bytes)` → `extracted_text`.
2. If blank → return `accepted=0, ocr_text_len=0` (a no-text screenshot is **not** an error).
3. Else synthesize `MonitorEvent(text=ocr_text, text_hash=sha256(normalized_text), …)`
   and call the **existing** `MonitorIngest.ingest_batch` → dedup by `(child_id, text_hash)`
   → `_run_pipeline` → flag/digest. **No change to MonitorIngest.**

Response 202 (extends `MonitorBatchResponse`): `{ accepted, deduped, flagged, acks, ocr_text_len }`.

### Two-layer de-duplication + volume control (the core requirement)
**Device (primary — prevents duplicate uploads + caps volume):**
1. **Trigger only on change**: capture on accessibility `WINDOW_CONTENT_CHANGED` for a
   monitored foreground app, **debounced** ~1.5 s (quiet period after the last change).
2. **Perceptual dedup**: downscale to a small grayscale thumbnail, compute a 64-bit
   **dHash**; keep a ring buffer of recent hashes; **skip upload if Hamming distance ≤ 6**
   to any recent hash → static redraws / the same visible messages are not re-sent.
3. **Crop volatile chrome** (status-bar clock, compose box) before hashing so trivial
   pixel changes don't defeat the dedup.
4. **Rate limit**: min interval between uploads (≈4 s) + hard cap (≈20 images / 5 min)
   via a token bucket; excess is dropped (logged).
**Server (defense in depth):** OCR text → `text_hash` dedup via the existing `DedupStore`,
so a near-duplicate image that slips through yields identical OCR text and is deduped —
never double-flagged.

### Privacy / consent
Screen capture is a **privacy escalation** (the whole screen, not just chat text). It
requires a MediaProjection consent dialog (cannot be granted silently) and a foreground
service. The onboarding consent screen must disclose screen capture explicitly; raw
images are processed transiently and not persisted unless an event is flagged.

## Alternatives considered
- **On-device OCR (ML Kit) → send text** (B1): avoids uploading images and reuses the
  text pipeline, but adds an ML Kit dependency + on-device OCR tuning. Deferred — the
  server already has Tesseract `heb+eng`, so server-side OCR is less new code now.
- **Accessibility `FLAG_INCLUDE_NOT_IMPORTANT_VIEWS`**: tried 2026-06-09, did **not**
  reveal WhatsApp bubbles (they aren't in the tree at all). Rejected.
- **Send every frame / fixed-interval polling**: rejected — violates the no-duplicate /
  don't-overload constraint; perceptual-hash-on-change is the chosen trigger.

## Update 2026-06-11 — per-line classification (dilution fix)
First real-OCR end-to-end run (`scripts/test_image_endpoint.py` against the live
DictaBERT + Tesseract server) revealed that synthesising **one** `MonitorEvent`
from the whole screen **dilutes** a lone offensive line below the offensive
threshold. Measured on the real model:
- isolated line `אתה מטומטם ואני שונא אותך` → `is_offensive=True @ 0.73`
- whole-screen blob (title + 4 bubbles + timestamps) → `is_offensive=False @ 0.55`

**Fix (shipped):** the OCR layer now reconstructs **per-line segments** from
Tesseract's `block/par/line` numbering (`OcrResult.line_segments`), and
`POST /v1/monitor/image` emits **one event per line** (chrome/timestamps filtered
by `_select_text_segments`; ≥2 alphabetic chars). Fully compatible with
`MonitorIngest.ingest_batch` (it already handles N-event batches + per-event
dedup). Fallback to the single-blob event when a backend doesn't segment. After
the fix the same screenshot yields `flagged≥1` and a parent alert.
Tests: `test_monitor_image.py` (6) + `test_tesseract_adapter.py` segmentation, green.

**Orthogonal findings (tracked under the classifier, not this feature):**
- A mild insult is labelled `violence` → force-escalated to the Context Agent →
  real Gemini rules `is_real_threat=False` → silenced. The violence→CA rule can
  suppress non-threat bullying.
- Raw-softmax over-escalation flags some benign lines (e.g. `נתראה מחר בבית ספר`).
  Serve-time calibration is still not wired (CLAUDE.md caveat).

## Update 2026-06-11b — on-device findings: app scope, flooding, memory

First real-device run (Huawei P20, Android 10) surfaced three issues; all fixed:

**1. Request timeout / retry storm.** A real chat screen OCRs to 15–35 lines; with
per-line classification each borderline line makes a synchronous Context-Agent
(Gemini ~1.5 s) call, so `/v1/monitor/image` blew past the 30 s gateway timeout →
the app never got a 2xx → re-uploaded → storm. **Fix:** cap segments per screenshot
to the N most text-dense lines (`MONITOR_IMAGE_MAX_SEGMENTS`, default **8**).
Deeper fix (async ingest queue / batched classify / skip per-segment CA on the
monitor path) remains the S6 item.

**2. Misleading app support + Instagram/Facebook.** The consent copy implied
per-app *text* monitoring of WhatsApp/Instagram/Telegram/Messenger, but the
accessibility-text path is unreliable on most (IG/FB hide content from the a11y
tree — same as WhatsApp bubbles). **Decision (user-chosen): "enable all via
screenshots + honest copy."** The screenshot+OCR path is pixel-based and therefore
app-agnostic, so it genuinely covers IG/FB comments & chats. Changes: reframed
`strings.xml` consent/rationale around the screen-capture+OCR mechanism; **added
`com.facebook.katana` (main Facebook app)** to `accessibility_service_config.xml` +
`TargetAppRegistry` (Instagram/Messenger/Telegram were already in the ceiling).

**3. Flooding + on-device memory.** Screenshots were uploaded too eagerly and the
full bitmap was held in memory during the multi-second upload. **Fixes (device):**
serialize the capture→upload path with a `Mutex` (one screenshot in flight; new
captures during processing are **dropped** — no urgency); **compress to JPEG and
recycle the bitmap BEFORE the network call** (hold only the small byte[]); add a
deliberate post-upload spacing delay; tightened throttle — debounce 1.5→3 s, min
interval 4→8 s, token bucket 20→10 per 5 min, dHash ring 10→24. The text path
already deletes sent rows from the Room buffer (`MonitorUploader` → `deleteByIds`);
the screenshot path holds no durable buffer (fire-and-forget, recycled).

## Revisit
- If Tesseract accuracy on chat screenshots is poor, switch to on-device ML Kit OCR (B1)
  or crop tighter to bubble regions.
- If image upload volume/cost is still high, move OCR on-device and upload text only.
- Per-message bubble grouping (vs. per-line) if multi-line messages get split awkwardly.
- **S6:** async ingest queue + batched classification + skip/throttle per-segment
  Context-Agent on the monitor path (the proper fix for the timeout, vs. the segment cap).
- Verify the screenshot path on Instagram/Facebook/Telegram on-device (mechanism is
  app-agnostic and proven on WhatsApp; per-app confirmation still pending).
