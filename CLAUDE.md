# Shomer.AI — Project Context for Claude

Load-bearing handoff document between sessions. **Read it first.**
(Full historical session log preserved in `CLAUDE.full.md` and git history.)

---

## What this project is

**Shomer.AI** is Alona's graduate project: a Hebrew-language safety / offensive-content
classification system around a fine-tuned local model. One consolidated workspace
(the old `offensive-hebrew` prototype was merged in 2026-05-23).

**Runtime architecture:**
```
[Android (Kotlin/Compose)] --HTTP--> [FastAPI :8000] --pipeline--> classifier · ocr · context_agent · triage · alerts · audit_log
                                                          (DictaBERT/Ollama)  (Tesseract)  (Gemini→Haiku)
```

**Design principle (ports & adapters):** every module is a Protocol (the "port") with ≥2
adapters. `server/app/main.py` `lifespan()` is the **only** place concrete adapters are
constructed → swapping an implementation is a one-line env-var flip
(`CLASSIFIER_MODEL_VERSION=v1.0-standin ↔ v1.1-dictabert`). Rule codified in `docs/design/README.md`.

---

## Directory map

```
C:\AIDevelopmentCourse\Shomer.AI\
├── CLAUDE.md / CLAUDE.full.md   ← this file / full archived history
├── README.md
├── plan-docs\          ← academic deliverables + roadmap
│   ├── Plan.md                  ← master 10-meeting plan; detail in plan\00–10
│   ├── POC_Plan.md              ← technical roadmap (7 phases 0–6)
│   ├── decisions\*.decision.md  ← decision log (REQUIRED, see below)
│   └── meetings\m<N>\           ← per-meeting goal/tasks/results (m3, m5, m6)
├── docs\
│   ├── design\                  ← 10 module LLDs + README + review.md + 144-task backlog
│   └── concepts\                ← DictaBERT architecture + data-techniques (locked)
├── prompts\            ← per-session digest log (REQUIRED, see below) + _template.md
├── integration\        ← integration test plans, one per POC phase
├── android_client\     ← Kotlin + Compose client
├── server\             ← FastAPI service (app\ · logs\ · sdk\ Kotlin SDK+CLI · tests\)
└── training\           ← DictaBERT fine-tune (WSL2 + cu128 stack)
```

`server/sdk/` is the shared client library for all clients — **implemented** (hand-written Kotlin `:sdk` + `:sdk-cli`, standalone Gradle build; see status table + `plan-docs/decisions/sdk-implementation.decision.md`).

---

## Current status (2026-06-12)

| Area | State |
|---|---|
| **Server (Python)** | ✅ **Real monitoring app S1→S4 shipped + verified end-to-end.** All modules Protocol-typed: `classifier · ocr · context_agent · triage · alerts · gatekeeper · audit_log(SqliteAuditStore) · identity(SqliteIdentityStore) · monitor · dedup · flagged(SqliteFlaggedEventStore default) · digest(DigestScheduler)`. **693 tests pass (8 skipped; full suite ~5m50s).** `main.py` v0.6.3-parent-review. **Gmail email alerts (2026-06-12):** `GmailApiNotifier` adapter added (`server/app/alerts/gmail_notifier.py`); `ALERTS_CHANNEL=email` selects it. Parent email captured at `/v1/parent/register`; `_dispatch_alert` resolves child→parent→email via identity store. New env vars: `GMAIL_CLIENT_JSON`, `GMAIL_TOKEN_JSON`, `ALERT_FROM`. One-time consent: `scripts/gmail_oauth_setup.py`. 33 new tests: `test_gmail_notifier.py` (13 unit), `test_email_registration.py` (16 contract ×2 adapters), `test_email_alert_channel.py` (4 integration). `gmail_credentials/` git-ignored. **Conversation-scoping fix (2026-06-12):** history scoped by `(child_id, conversation_id)` — cross-thread false alarms (Daria bleed) fixed; OCR gibberish gate (`_looks_like_text`) added to `monitor/router.py`; SQLite `conversations` table migrated idempotently; multi-tenant isolation confirmed + tested. **Monitor flow:** child pairs (OTP→device token, `/v1/pair`) → batch-uploads captured msgs (`POST /v1/monitor/events`, Bearer-authed, `child_id` match enforced) → `MonitorIngest` dedups + reuses `_run_pipeline` verbatim → flags `alerted`/`review_needed` → **once-a-day `DigestScheduler`** aggregates per child (`GET /v1/parent/digests/{date}`; `AsyncioCronDigestScheduler` default-off, `DIGEST_BACKEND=asyncio` to enable) → parent reviews + reacts (`GET /v1/parent/alerts`, `/{id}`, `POST /{id}/react` ack·label·severity, `GET /v1/parent/labels/export` for training). Auth: `DeviceAuthMiddleware` (content-blind) in Gatekeeper group; opaque device/parent tokens. **End-to-end demo: `scripts/monitor_demo.py`** (in-process TestClient, no uvicorn orphan — runs the full slice green). **Run pytest from REPO ROOT.** |
| **DictaBERT classifier** | ✅ **Architecture locked + TRAINED (final = D10; D11 + D12 both reverted).** Test macro-F1 **0.836**, recall[violence]=0.788, precision[non_off]=0.935, ECE=0.034. All 3 gate criteria PASS. Per-class F1: non_off 0.931 · abusive 0.831 · hate 0.739 · violence 0.712 · porn 0.970. Best checkpoint: `training/outputs/dictabert-offensive/checkpoint-best/` (738 MB safetensors). Stylistic slices: clear_hebrew 0.787 · children_mistakes 0.744 · code_switching 0.803 · poor_spelling 0.615. **Data built across 6 rounds** (SinaLab+textdetox real Hebrew + Gemini translation/synthesis + char-noise aug; prevalence-aware ~50% non-off train / ~70% eval + Focal+weights). D11 heavy-noise **reverted** (cost hate −0.08 for +0.02 poor_spelling); D12 kid-pool-scoped noise (2026-06-08) **also reverted** — same failure mode (hate −0.10, poor_spelling −0.04). **Synthetic char-noise can't lift poor_spelling without costing hate — data lever exhausted for that slice.** Handoff: `training/outputs/dictabert-offensive/HANDOFF.md`. Decisions D1–D12 in `plan-docs/decisions/data-pipeline.decision.md`. **✅ WIRED LIVE (2026-06-08):** server now uses it via `HuggingFaceClassifier` (`CLASSIFIER_MODEL_VERSION=v1.1-dictabert`); 564 tests pass; smoke OK. **Head-to-head vs Ollama stand-in on same 445 test rows** (`scripts/eval_ollama_vs_dictabert.py`, `docs/accuracy_eval/`): DictaBERT 89.4% 5-class / macro-F1 0.836 vs Ollama `offensive-hebrew:v1` 37.8% / 0.373, 424× faster — decision `plan-docs/decisions/classifier-model-selection.decision.md` (use trained model, not Ollama/off-the-shelf = the unique solution). Result graphs: `training/outputs/dictabert-offensive/plots/`. **⚠️ Caveats:** minority val/test partly synthetic (porn 100% synthetic) → in-distribution numbers overstate real-world; serve-time calibration NOT yet wired (raw softmax over-escalates benign → Context Agent); no real gold-set benchmark yet. |
| **Training stack** | ✅ **WSL2 + CUDA 12.8 verified (RTX 5080, sm_120).** Venv `~/shomer-training-venv` with `torch 2.11.0+cu128`, `transformers 5.10.1`, `bitsandbytes 0.49.2`. Real BF16 fwd+bwd + DictaBERT Hebrew forward pass confirmed on GPU. Pinned in `training/requirements-wsl.txt`. Final D10 train size: 7,974 rows; ~2 min/run on RTX 5080; gate eval automated in `train_dictabert.py`. |
| **Design package** | ✅ Signed off (Meeting 4). 10 module LLDs + `docs/design/README.md` + `review.md` (3 blockers G-01/02/03 resolved) + 144-task backlog (`tasks_index.json`) + PDFs. |
| `android_client/` | ✅ **Real client BUILT (`com.shomer.client`) — both flavors compile.** LLD `android_client/design.md`. **Child-mode:** `ShomerAccessibilityService` (captures other apps' text) → `PreFilter` (Hebrew-ratio/dedup/sha256) → encrypted Room buffer → `MonitorUploader` (WorkManager → `POST /v1/monitor/events`, Bearer); consent (inbound+outbound) + pairing (`/v1/pair`) + permission flow + non-dismissible monitoring indicator. **Parent-mode:** role chooser → parent auth (`/v1/parent/register` or paste token) → alert list/detail/**react** (ack·label·severity, polling) + digest screen; `ShomerFcmService` written but **opt-in** (no `google-services.json` needed to build). Gradle flavors `poc`(`com.dima.offensivehebrew`)+`client`(`com.shomer.client`) — **APK uninstall required** when switching applicationId. **All wire models verified field-by-field against `server/app/schemas.py` + routers** (snake_case `@Json`). Set `JAVA_HOME` to Studio JBR; `./gradlew assembleClientDebug`. |
| **Parent web dashboard** | ✅ `dashboard/index.html` (+README) — self-contained Hebrew-RTL parent surface reading the S4 API (alerts list w/ borderline review queue, detail + ack·label·severity, daily-digest view). Configurable base-URL+token in localStorage; serve via FastAPI StaticFiles or open standalone. |
| `server/sdk/` | ✅ **Implemented (MVP v1.0.0, 2026-06-08).** Hand-written Kotlin/JVM standalone Gradle build (own wrapper): `:sdk` lib (`ShomerApi` port → internal `ShomerHttpClient` OkHttp+Moshi adapter; `ShomerResult`/`ShomerError` 6 types; retry 1s/2s/4s on 5xx+IOError, never 4xx; UUID4 `X-Trace-ID`; models mirror `schemas.py`) + `:sdk-cli` clikt fat-jar (`classify`/`classify-image`/`health`/`info`/`demo`). **`:sdk:test` = 10/10 MockWebServer contract tests pass; `:sdk-cli:fatJar` builds (18 MB).** Build: `JAVA_HOME`=Studio JBR (JDK 21 → Java-17 bytecode, no toolchain), `cd server/sdk && ./gradlew :sdk:test :sdk-cli:fatJar`. **Not yet:** batch mode (SDK-CLI-03); wiring the Android client off `ApiService.kt` onto `:sdk`. Decision: `plan-docs/decisions/sdk-implementation.decision.md`. |
| `training/` | ✅ **Full pipeline + final D10 model.** `fetch_inspect_sinalab.py` (Stage-0 download), `gemini_utils.py`, `sublabel_textdetox.py`, `synthesize_{porn,hate_violence,abusive,kids,codeswitch}.py`, `translate_en_he.py`, `expand_slang_lexicon.py`, `augment_noise.py` (heavy-noise fns present but unused after revert), `prepare_data_dictabert.py` (deterministic; consumes cached `training/data/interim/*.jsonl`), `scripts/validate_splits.py`, `train_dictabert.py` (locked). Raw data + inventory: `training/data/raw/`. Checkpoint at `outputs/dictabert-offensive/checkpoint-best/`. |
| `server/.venv/` | ✅ Functional; all deps installed. DictaBERT base (~708 MB) cached at `~/.cache/huggingface/hub/`. |
| Tooling | Android Studio · Ollama (running) · MiKTeX (`xelatex` at `C:\Program Files\MiKTeX\miktex\bin\x64\`) · Edge (for `scripts/md_to_pdf.py`) · Tesseract `heb+eng` at `C:\Program Files\Tesseract-OCR\`. GPU: RTX 5080 16 GB, driver 591.86; 64 GB RAM. |

---

## Server behavior to remember

- **No LLM keys** → Context Agent uses a deterministic **mock** that resolves escalated/borderline
  cases to "not a threat" → `silent`. Real escalation alerts need `GEMINI_API_KEY` /
  `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` in `server/.env` + `CONTEXT_AGENT_ENABLED=true`.
  Composition-root LLM priority: **Gemini → OpenAI → Anthropic** (first key primary, second fallback, Mock fills gaps).
- **Triage routing** (G-03 fix): `_decide_inner` does Step A `prob_offensive = result.confidence if
  result.is_offensive else 1 - result.confidence` **before** Step B threshold routing. Direct alerts
  fire on high-confidence non-violence offensive (`abusive`/`hate`) or `pornographic` (always-alert);
  `violence` always escalates to the CA first.
- **Labels** locked to underscore spelling: `non_offensive` (matches `schemas.py`/`prompt.py`).
- Requests **without `child_id`** share the `"unknown"` rate-limit bucket (anti-storm); per-child traffic gets its own bucket.
- **Windows console**: `main.py` forces UTF-8 stdio (Hebrew structlog lines crash cp1252 otherwise).
- **Baseline accuracy** (`scripts/eval_accuracy.py`): TEXT 69.5 % / IMAGE 66.3 % 5-class, ~80 % binary;
  `hate` recall ≈0.10; image ≈ text → **the classifier, not OCR, is the bottleneck.**

**Debug tooling:** `scripts/dev_client.py` (+ `replay <trace_id>`) · `scripts/inspect_audit.py`
(read-only SQLite inspector) · `scripts/load_test.py` · `scripts/test_console.py` (self-starting
interactive console, Hebrew RTL via `python-bidi`, numbered sample picker).
**Gotcha:** background uvicorn servers launched via the harness can orphan and hold `:8000`
un-killably — use a fresh `--port` for live runs.

---

## Training env (reproduce)

```bash
wsl -d Ubuntu-24.04
python3 -m venv ~/shomer-training-venv && source ~/shomer-training-venv/bin/activate
pip install --upgrade pip wheel setuptools
pip install torch==2.11.0+cu128 torchvision==0.26.0+cu128 torchaudio==2.11.0+cu128 \
    --index-url https://download.pytorch.org/whl/cu128
pip install -r training/requirements-wsl.txt
```
Use the WSL-native venv (not `/mnt/c/...`) for fast pip + HF I/O. WSL repo root: `/mnt/c/AIDevelopmentCourse/Shomer.AI/`.

---

## Next session priorities

**Monitoring app (server S1→S4 + Android child+parent modes DONE; plan `~/.claude/plans/linked-yawning-sifakis.md`):**
1. **On-device integration test** (user-driven — needs Android Studio + emulator/phone). Contract + build
   are verified; the live run is the only unverified step. Follow `integration/integration-monitor.md`:
   start server `--host 0.0.0.0 --port 8011`, build/install the `client` flavor (uninstall POC APK first),
   pair via an OTP from `/v1/parent/pairing-code`, enable AccessibilityService, send a Hebrew message in
   WhatsApp, confirm it flags server-side + appears in the dashboard/parent-mode. Android A5/A6 (OCR
   fallback, multi-app direction tuning, prod cleartext-off) are follow-ons.
2. **S5 privacy hardening** — **enforce `MONITOR_STORE_RAW=false`** (raw text is still persisted for
   monitor events; setting exists, non-flagged blanking is the remaining work) · TLS + cleartext-off
   prod · at-rest encryption · PII-scrub logs (G-06) · consent indicator (Android).
3. **Live FCM ops** — real Firebase project + service-account JSON so the daily digest pushes to a real
   device (today `LogNotifier`; `FcmNotifier` implemented, needs creds + `ALERTS_CHANNEL=fcm`).
4. **S6 scale + classifier gate** — Redis dedup · async ingest queue · batched DictaBERT · build a
   **monitor-realistic eval slice**; gate the `v1.1-dictabert` flip on `hate`/`violence` recall +
   calibration, not just F1≥0.78.

**DictaBERT training track — TRAINED (final D10), ready for server integration:**
5. **Flip `CLASSIFIER_MODEL_VERSION=v1.1-dictabert`** in `server/.env` → `backend-developer` wires
   `DictaBertAdapter` (the MLP-head `DictaBertWithMlpHead` must be importable before `from_pretrained`)
   → run fast tests from REPO ROOT → live `/classify` smoke test with a misspelled Hebrew sentence.
   See `training/outputs/dictabert-offensive/HANDOFF.md` for the full checklist.
   - Tuning is **closed** (6 rounds). Further gains need real misspelled/minority data, not synthesis.
   - Before flip, optionally produce the **honest real-only eval** (synth→train-only) as a companion
     metric, and add a real Hebrew porn test seed (D6/D8/D9 caveats).
6. **Deferrable (Important review issues):** G-04 port-naming · G-05 error model · G-06 PII scrub ·
   G-07 A/B eval doc · G-09 Slang Lexicon LLD · G-12 health rollup · G-14 gold-set annotation.

---

## Session update — 2026-06-08 (DictaBERT trained: full data pipeline, 6 rounds → final D10, gate PASS)

Built the entire train/val/test dataset from scratch and trained the classifier to the F1≥0.78 gate.
Full decision trail D1–D11 in `plan-docs/decisions/data-pipeline.decision.md`.

- **Stage 0 (recon):** SinaLab is on **GitHub `SinaLab/OffensiveHebrew`** (NOT an HF dataset — `load_dataset`
  404s). Real deduped counts are far worse than §9 assumed: non_off 14,298 · hate 624 · violence 453 ·
  abusive **119** · pornographic **4**. Label is a messy free-text column (typos, `racism`→hate, comma
  multi-label). Verified inventory: `training/data/raw/README.md`.
- **Sources:** SinaLab + **textdetox `he`** (807 real toxic → Gemini sub-labeled) as real base; **Jigsaw**
  (threat→violence, identity_hate→hate) Gemini-translated EN→HE; Gemini synthesis for porn / in-context
  hate+violence / abusive / kids-register / code-switch; deterministic Hebrew char-noise aug. hatespeechdata.com
  has no Hebrew; OLaH/D_OLaH = SinaLab itself.
- **Key learnings (the iteration story):** full class-balancing (1:1:1:1:1) **failed** non_off precision
  (0.69 — false-alarm flood) → reverted to **prevalence-aware** (~50% non-off train / ~70% eval + Focal+weights);
  benign Heb-Eng code-switch synthesis fixed a code_switching regression (0.68→0.81); heavy typo-noise (D11)
  was **reverted** (cost hate −0.08 for +0.02 poor_spelling).
- **Final model (D10):** test macro-F1 **0.836** · recall[violence] 0.788 · precision[non_off] 0.935 ·
  ECE 0.034 — **all gates PASS**. Slices: clear 0.787 · children 0.744 · code-switch 0.803 · poor_spelling 0.615.
  Train 7,974 rows. Checkpoint `training/outputs/dictabert-offensive/checkpoint-best/`.
- **⚠️ Documented limitation (thesis):** minority val/test partly synthetic/translated (D8 user choice) →
  minority F1 overstates real-world; porn val/test 100% synthetic (Gemini safety-blocked a real seed).
  Slang lexicon expanded 10→72 (`server/data/slang_lexicon.json`, also helps Context Agent).
- **NOT flipped:** `CLASSIFIER_MODEL_VERSION` still `v1.0-standin` — server integration is the next step.

---

## Session update — 2026-06-07 (Meeting-6: Gemini CA live + baseline accuracy + test console)

Brought the Context Agent up on a **real LLM**, measured baseline accuracy, built an interactive test console. **387 fast tests pass.**

- **Gemini Context Agent (live).** New `GeminiClient` (Gemini's OpenAI-compatible endpoint → reuses
  `openai` SDK, no new dep). Verified: `violence` message escalates → `gemini-2.5-flash` returns
  `is_real_threat=true, severity=high` → real alert; `haiku-4.5` is the working fallback. Bring-up
  fixes: model `2.0-flash` retired→`2.5-flash`; parser strips ```` ```json ```` fences;
  `reasoning_effort=none` (Gemini 2.5 "thinking" truncated JSON); `_build_llm_clients` passed settings
  object instead of api-key string; user's misspelled `.env` keys (`GEMENI_`/`ANTROPIC_`) → corrected.
- **Baseline accuracy** (`scripts/eval_accuracy.py`, 200 text + 300 image, stratified): TEXT 69.5 % /
  IMAGE 66.3 %. Reports: `docs/meeting6_accuracy_report.pdf`, `docs/meeting6_accuracy_summary.md`.
- **Interactive test console** (`scripts/test_console.py`): self-starts server, per-session
  `audit.db`+`server.log` under `test-sessions/`, Hebrew RTL + numbered sample picker.
  New deps `python-bidi`+`matplotlib`.

**Meeting artifacts convention:** per-meeting goal/tasks/results under `plan-docs/meetings/m<N>/`
(m6 = `00-goal-and-scope.md`, `01-tasks.md`, `02-results-summary.md`, `meeting6_server_flow_plan.md`).
Detailed reports stay under `docs/`; decisions under `plan-docs/decisions/`.

---

## Plan & academic framing

- **Master plan:** `plan-docs/Plan.md` (10 academic meetings; detail in `plan-docs/plan/00–10`).
  POC reframed as Step 0 (feasibility, done).
- **Technical roadmap:** `plan-docs/POC_Plan.md` — 7 phases (0–6). **Phase 3** = train the Hebrew classifier;
  **Phase 4** = multimodal image-strategy A/B (OCR vs vision-LLM vs pipeline vs parallel) — **secondary axis** since the 2026-05-27 reframe.
- **Research question (REFRAMED 2026-05-27 → `docs/research_question/research_question.md`):**
  *Does adding conversational context (the previous k turns) to Hebrew bullying classification reduce the
  false-positive rate vs. classifying the message in isolation — without hurting recall?* Measured = **FPR + recall**;
  baseline = the **same model, context-blind**. Success = a statistically-significant FPR drop with non-inferior recall on a
  real gold set. The multimodal image-routing axis was **demoted from spine to secondary** (old RQ3/RQ4).
  Decision: `plan-docs/decisions/research-framing.decision.md` (D-Reframe-2026-05-27).
- **Flagship anchors** (`docs/literature/literature_flagship.md`): SinaLab Offensive-Hebrew (Hamad et al. 2023,
  arXiv:2309.02724) = the 5-label schema **and the context-blind baseline we compare against**; Pavlopoulos 2020 = context axis;
  Sap 2019 / Davidson 2019 = false-positive axis; SynBullying / ToxiGen = synthetic conversational data; QLoRA = fine-tune method.
  **Contribution = bringing conversational-context FP-reduction to Hebrew bullying detection — an axis not yet studied in Hebrew.**

---

## REQUIRED on every session

**1. Decision capture** → `plan-docs/decisions/<phase-or-step>.decision.md`.
Write one any time the user picks between substantive paths (model/library/architecture/default).
Per-decision fields: **Question · Choice · Why · Alternatives considered · Revisit** (copy an existing file).
Write right after an `AskUserQuestion` answer, a multi-option dialogue, or a direction-locking instruction.
Skip routine clarifications (paths, names, formatting). Backfill allowed but mark it as backfill.

**2. Session prompts log** → `prompts/YYYY-MM-DD_meeting-N.md` (`N` = next *upcoming* meeting; template in `prompts/_template.md`).
Append a `### N. <label>` block per substantive prompt **as the session progresses** (not reconstructed at end):
restated prompt · what was delivered (links) · decisions/files of note. End with "Open / carry-over" + "Files touched."
Restatement not transcript (~3–6 lines/turn). Skip only trivial one-question sessions that created no file.

The prompts log records *what happened*; decision files record *what was decided and why* — link, don't restate.

---

## Conventions

- **Don't assume training has run** — no GGUF/checkpoint exists yet; the Ollama stand-in is the default classifier path.
- **English** for code, comments, commits. Hebrew is the *domain language* (text being classified), not the working language.
- **Hebrew Markdown must render RTL (MANDATORY):** wrap the whole file — first line `<div dir="rtl">` + blank line,
  last line `</div>` preceded by blank line. **English-only `.md` files stay LTR — do not wrap** (this file, `Plan.md`, `README.md`, `plan-docs/plan/*`).
- **Shell is PowerShell on Windows.** WSL2 only for training. Username on the machine is `Dima`; **the user is Alona** — don't conflate.
- Android URLs: emulator `http://10.0.2.2:8000/`; physical phone `http://<PC-LAN-IP>:8000/`
  (one-time firewall: `New-NetFirewallRule -DisplayName "OffensiveHebrew" -Direction Inbound -LocalPort 8000 -Protocol TCP -Action Allow`).
- Open the Android project from `android_client/` (not `app/`) in Studio, or Gradle sync breaks.
- Any reference to `C:\Users\Dima\Projects\offensive-hebrew\` is **stale** — update on sight.
- PDF generation: `python scripts/md_to_pdf.py [files...]` (Hebrew RTL Markdown → PDF via headless Edge). LaTeX (business plan) uses XeLaTeX/MiKTeX.

---

## How to resume

1. Read this file.
2. Skim the most recent `prompts/` digest for carry-over items.
3. Continue from "Next session priorities" above. Open today's prompts log on the first substantive prompt; append turn-by-turn.
4. Modular server pipeline is **alive end-to-end** (387 tests). DictaBERT architecture **locked** but **not trained** —
   first action is `training/prepare_data_dictabert.py`.
