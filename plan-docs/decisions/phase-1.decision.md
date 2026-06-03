# Phase 1 — Decisions

**Phase:** POC Phase 1 (connection plumbing — text + image with stub backend)
**Decided on:** 2026-05-23
**Decided by:** Alona, with options presented by Claude
**Note:** backfilled retroactively after the convention was established; future phases capture decisions in real time.

---

## D-Phase1-Initial-step — What "initial step" means for the POC

**Question:** Should Phase 1 focus on real image processing immediately, or just on wiring text + image transport with a stub processor?

**Choice:** **Wiring first; image processing comes later.** Phase 1 proves the wire (Android → multipart → FastAPI → JSON response) end-to-end. Image classification is intentionally stubbed and arrives in Phase 2.

**Why:** decoupling transport from model gives a known-good baseline before architectural choices are made. The wire is the thing most prone to network / config / build issues; the model choice is the thing most prone to academic-quality issues. Solving them separately makes each easier to debug.

**Alternatives considered:**
- *Phase 1 includes real OCR or vision:* would conflate two unrelated debugging surfaces.

**Revisit:** never — this decision is foundational to the phase structure of the entire POC.

---

## D-Phase1-Folder-Structure — Project layout for client + server

**Question:** Should the Android client live alongside the server, or in its own repo?

**Choice:** **Single workspace at `C:\AIDevelopmentCourse\Shomer.AI\`.** Subfolders: `android_client/`, `server/`, `training/`, `plan-docs/`, `integration/`.

**Why:** academic project with one owner; one git history for everything makes traceability easy. Migrated the prior standalone `offensive-hebrew` prototype into this workspace on the same day.

**Alternatives considered:**
- *Separate repos per component:* more "real-world" but adds coordination overhead with no benefit at POC scale.

**Revisit:** if the project ever ships a real client SDK independent of the server, split then.

---

## D-Phase1-Vendor-Toggle-UX — How to switch between text and image input modes

**Question:** What UI control for the Text | Image input-mode toggle?

**Choice:** **Material 3 `SingleChoiceSegmentedButtonRow`** with two `SegmentedButton`s.

**Why:** idiomatic Material 3 for mutually-exclusive small option sets; matches existing app style; clearly conveys "you can only be in one mode at a time".

**Alternatives considered:**
- *Two top-level tabs (`TabRow`):* heavier UI, implies separate "screens".
- *A single `Switch`:* not clearly labelled, ambiguous which side is which.

**Revisit:** if a third input mode appears (audio? video?), reconsider whether segmented buttons still fit or a `TabRow` would be cleaner.

---

## D6 — Image upload encoding

**Question:** Multipart/form-data vs base64-in-JSON for sending images to the server?

**Choice:** **Multipart/form-data** (standard `MultipartBody.Part` from Android; `UploadFile` on FastAPI).

**Why:**
- ~33% smaller payload than base64 (no encoding overhead).
- Streams cleanly through proxies and ASGI servers.
- Standard HTTP idiom; widely understood by tooling (curl, Postman, Wireshark).

**Alternatives considered:**
- *Base64-in-JSON:* simpler client code (no multipart libraries needed), but bigger payload and harder to inspect.

**Revisit:** if the Android side ever needs to send richer structured metadata alongside the image, JSON+base64 might be simpler. Multipart can already carry metadata as additional form fields, so unlikely.

---

## D7 — Image compression target (client-side)

**Question:** How much should the Android client compress images before upload?

**Choice:** **Longest edge ≤ 1600 px, JPEG quality 80**, targeting ≤ 1 MB per upload.

**Why:**
- 4K phone photos are 3–8 MB. Sending raw is slow on Wi-Fi and the LLM doesn't benefit from the extra pixels.
- 1600 px is enough for OCR to read normal-sized text reliably, and well above what a vision LLM samples internally.
- Quality 80 is the standard "very-high-quality" JPEG sweet spot; visible artifacts only appear below ~50.

**Alternatives considered:**
- *No compression:* 5–10× slower uploads on home Wi-Fi; not worth it.
- *Aggressive compression (≤ 800 px, q60):* would degrade OCR accuracy on small text.

**Revisit:** if Phase 4 OCR accuracy turns out to be limited by image resolution, raise to 2000 px.

---

## D-Phase1-Server-SDK — Shared client library

**Question:** Should Phase 1 build the shared SDK at `server/sdk/` for clients to import?

**Choice:** **No — placeholder only.** Each client keeps its own minimal HTTP layer for now. SDK promotion is deferred to Phase 5 (optional).

**Why:** the API is small (3 endpoints), only one client exists today, and the SDK shape (generated vs hand-written) is an open decision that doesn't need to be answered before the wire works. Premature abstraction.

**Alternatives considered:**
- *Generate Kotlin + TypeScript clients from OpenAPI now:* defensible academically, but adds tooling complexity at the moment we most need to keep moving.

**Revisit:** Phase 5 (if a second client materialises) or whenever the cost of keeping models in sync between client and server exceeds the cost of code generation.

---

## Linked artifacts

- Implemented in: Phase 1 across `android_client/`, `server/app/main.py`, `server/app/image_backends/stub.py`.
- Tested by: `integration/integration-1.md`. Results: `integration/results/integration-1/run-2026-05-23.md` (emulator) + `run-2026-05-23-physical-huawei-p20pro.md` (Huawei P20 Pro). Both PASS.
- Plan source: `plan-docs/POC_Plan.md` §4 Phase 1.
