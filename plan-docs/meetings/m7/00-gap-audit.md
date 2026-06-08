# Shomer.AI — Development Gap Audit (everything except model training)

**Date:** 2026-06-08
**Author:** session audit (Claude)
**Scope:** Are all designed components — design modules, full-flow server, SDK, client apps — actually built? Where are the gaps and open questions? **Model training is explicitly out of scope** (the DictaBERT fine-tune is a known, expected gap tracked separately).

**Method:** every claim below was verified against actual files (Glob/Grep/Read), not against `CLAUDE.md` prose.

---

## TL;DR

| Area | Built? | Biggest non-training gap |
|---|---|---|
| **Server + design modules** | ✅ built + tested (550 tests, 44 test files) | PII scrub (G-06) · privacy hardening (S5, `MONITOR_STORE_RAW`) · eval harness (G-07/G-14) |
| **SDK + `:sdk-cli`** | ❌ design-only, 0/13 tasks → **now in progress** | The whole library + CLI; only a README existed |
| **Client apps** | 🟡 code-complete, both flavors compile | **On-device live run never executed**; FCM dormant |

The two things between "designed" and "done" (training aside): **(1) build the SDK + CLI** (this session starts it), and **(2) run the live Android↔server integration test** (`integration/integration-monitor.md`).

---

## 1. Design modules + full-flow server — ✅ ~90% built & verified

All 10 design-module LLDs have a Protocol port + ≥2 adapters, wired only in `server/app/main.py` `lifespan()`. Five additional modules were built beyond the original index.

| Design module | Server impl | Status |
|---|---|---|
| gatekeeper | `app/gateway.py` (3 ports: trace-id, metrics, rate-limit) | ✅ |
| ocr | `app/ocr/` (Tesseract + Stub) | ✅ |
| classifier | `app/classifier/` (Ollama + HF + Stub) | ✅ — HF adapter awaits checkpoint (the one expected training gap) |
| context_agent | `app/context_agent/` (Gemini/OpenAI/Anthropic/Mock + 3 tools) | ✅ (no per-port `health()` → G-12) |
| triage | `app/triage/` (G-03 polarity fix in code) | ✅ |
| alerts | `app/alerts/` (FCM/Log/Ntfy/Stub) | ✅ |
| audit_log | `app/audit_log/` (Sqlite + InMemory, RetentionSweeper) | ✅ |
| server core | `app/main.py` composition root | ✅ |
| android_client LLD | — | see §3 |
| sdk LLD | `docs/design/sdk/design.md` | design-only → §2 |

**Built beyond the original 10:** `monitor`, `dedup`, `flagged`, `identity`, `digest` — all Protocol-typed and wired.

**Both flows verified end-to-end-wired:**
- **Text flow:** gatekeeper → classifier → triage → (context_agent if escalate) → alerts → audit ✅
- **Monitor flow:** pair (`/v1/pair`) → `POST /v1/monitor/events` → dedup → pipeline → flagged → daily `DigestScheduler` → parent review (`/v1/parent/alerts`, `/{id}/react`, `/labels/export`) ✅

**Tests:** `server/tests/` = **44 test files** across every module + `integration/`. Consistent with the 550-pass / 5-skip (HF classifier awaits checkpoint) claim.

### Server gaps (non-training)
- 🟡 **G-06 — PII scrub** before the LLM call: only char-capping (`CA_PRIVACY_MAX_CHARS`), no redaction of phones/@mentions/names.
- 🟡 **S5 privacy: `MONITOR_STORE_RAW=false` not enforced** — raw monitor text is still persisted; non-flagged blanking is unbuilt.
- 🟡 **G-12 — `/health` rollup** omits `OcrBackend.health()` + `ContextReasoner.health()`.
- 🟡 **G-07 / G-14 — eval harness:** Meeting-8 A/B (ΔFPR) scripts + gold-set annotation workflow not written (the `gold_label` column exists).
- 🟡 **G-09 — Slang Lexicon** has a schema but no versioning/curation LLD.
- 🟡 **Prod TLS / cleartext-off / at-rest encryption** — dev posture only.
- 🟡 **FCM live ops** — `FcmNotifier` implemented but defaults to `LogNotifier`; needs a real Firebase service-account JSON + `ALERTS_CHANNEL=fcm`.

### Open questions (server)
- Does Dr. Segal require PII scrubbing before any LLM hop (blocks prod)?
- Should the `v1.1-dictabert` flip gate on `hate`/`violence` recall + calibration rather than F1≥0.78 alone?
- Redis dedup + async ingest queue needed before scale (S6)?

---

## 2. SDK (`server/sdk/`) — ❌ was design-only → 🟡 implementation started this session

**Before this session:** `server/sdk/` contained **only `README.md`** — no Kotlin, no Gradle module. The LLD `docs/design/sdk/design.md` (522 lines) fully specifies a hand-written Kotlin library; `tasks.json` lists **10 SDK tasks + 3 `:sdk-cli` tasks = 0/13 done**. No `:sdk-cli` Gradle subproject existed (`android_client/settings.gradle.kts` includes only `:app`, still named `OffensiveHebrew`). The Android client talks to the server via its own `ApiService.kt`/`ParentApi.kt`, not the SDK.

**Started this session** (standalone Gradle build at `server/sdk/`, pure Kotlin/JVM so it compiles headless and stays Android-import-clean per LLD §2.5):
- `:sdk` library — `ShomerApi` port, `ShomerHttpClient` adapter (OkHttp + Moshi), `ShomerResult`/`ShomerError`, `SdkConfig`, models mirroring `schemas.py`, retry + trace-id interceptors, SLF4J logger, `MetricsCallback`.
- `:sdk-cli` — clikt fat-jar wrapping the same `ShomerApi`: `classify`, `classify-image`, `health`, `info`, `demo` (golden set).
- Contract/unit tests via MockWebServer.

**Remaining SDK gaps:** batch mode for Meeting-8 gold-set evals (SDK-CLI-03, Phase 6); wiring `:sdk` into the Android client (replace `ApiService.kt`); `Authorization` header (Phase 9 auth); TypeScript variant (Phase 9). **Open question:** keep `:sdk` a standalone build, or fold it into `android_client/settings.gradle.kts` as `project(":sdk")` per LLD §9 (requires APK rebuild). Decision: `plan-docs/decisions/sdk-implementation.decision.md`.

---

## 3. Client applications (`android_client/`) — 🟡 code-complete, not live-verified

Both flavors compile (`poc` = `com.dima.offensivehebrew`, `client` = `com.shomer.client`). Every feature in `android_client/design.md` is written; the on-device live run is the only unverified step.

**Child-mode** (all ✅ in code): `ShomerAccessibilityService` capture → `PreFilter` (Hebrew-ratio/dedup/sha256) → encrypted Room buffer → `MonitorUploader` (WorkManager → `POST /v1/monitor/events`, Bearer) → consent + pairing + permission flow → `CaptureForegroundService` non-dismissible indicator → `BootReceiver`.

**Parent-mode** (all ✅ in code): role chooser → auth (`/v1/parent/register` or token paste) → alert list/detail/**react** (ack·label·severity, polling) → digest screen. `ShomerFcmService` 🟡 skeleton only.

### Client gaps (non-training)
- ❌ **On-device integration test never run** — no `integration/results/…` file exists. A1–A4 (pair → capture from WhatsApp → flag server-side → parent sees it → react persists) are all code-only. **#1 unverified claim in the whole project.**
- 🟡 **FCM dormant** — no `google-services.json`, plugin not applied, `firebase-messaging` commented out; parent is polling-only.
- 🟡 **Direction inference** (inbound/outbound) tuned for WhatsApp only; others default to inbound (A5).
- ❌ **OCR fallback** (MediaProjection + ML Kit) for canvas-rendered apps — deferred (A5).
- ❌ **Target-app picker UI** — app list hardcoded to 4 (A5).
- 🟡 **Prod hardening (A6):** cleartext-off override, SQLCipher at-rest, prod domain pinning — documented, not implemented.

### Open questions (client)
- Does the AccessibilityService actually capture real WhatsApp/IG Hebrew text on a physical device (and survive OEM battery-killers)?
- Which compose-box view-ids make direction inference reliable?
- Is 15-min upload cadence acceptable UX?

---

## Prioritized next actions (training aside)

1. **Run the live Android↔server integration test** (`integration/integration-monitor.md`) → converts the client from "contract-verified" to "verified." Highest-value, lowest-cost.
2. **Finish the SDK + CLI** (started here) → then migrate the Android client onto `:sdk` and delete the hand-rolled `ApiService.kt`.
3. **Server privacy hardening** — PII scrub (G-06) + enforce `MONITOR_STORE_RAW=false` (S5).
4. **Eval harness** (G-07/G-14) — needed for the Meeting-8 research-question result regardless of training.
5. **FCM live ops** — real Firebase project so the daily digest pushes.
