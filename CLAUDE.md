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
├── server\             ← FastAPI service (app\ · logs\ · sdk\ placeholder · tests\)
└── training\           ← DictaBERT fine-tune (WSL2 + cu128 stack)
```

`server/sdk/` is the shared client library for all clients — still a placeholder (README only).

---

## Current status (2026-06-07)

| Area | State |
|---|---|
| **Server (Python)** | ✅ **Full flow wired end-to-end + Gemini CA live.** All modules Protocol-typed: `classifier · ocr · context_agent · triage · alerts · gatekeeper · audit_log(SqliteAuditStore)`. **387 fast tests pass.** `main.py` v0.6.0-fullflow. Live-verified on Ollama `v1.0-standin`: classify→triage→CA→LogNotifier alert→SQLite + history + `/metrics`. Context Agent runs on real `gemini-2.5-flash` (primary) + `haiku-4.5` (fallback) when keys in `server/.env`. **Run pytest from REPO ROOT** (running from `server/` falsely fails 9 data-file tests). |
| **DictaBERT classifier** | ✅ **Architecture locked** at `docs/concepts/dictabert_classifier_architecture.md`: MLP head (`[CLS]→Dropout→Linear(768→256)→GELU→Dropout→Linear(256→5)`); Focal Loss(γ=2, alpha=class_weights); ε=0.05 label smoothing; AdamW + cosine LR + lr=2e-5 + batch=32 + 5 epochs + BF16, seed=42. Real param count **184.3 M** (Hebrew vocab), BF16 ≈370 MB, ~6–8 GB VRAM. Data techniques + locked Meeting-5 stack in `docs/concepts/dictabert_data_techniques.md` §11. Fallback if F1<0.78: MLP→Multi-task→DictaBERT-large→DAPT. **NOT yet trained.** |
| **Training stack** | ✅ **WSL2 + CUDA 12.8 verified (RTX 5080, sm_120).** Venv `~/shomer-training-venv` with `torch 2.11.0+cu128`, `transformers 5.10.1`, `bitsandbytes 0.49.2`. Real BF16 fwd+bwd + DictaBERT Hebrew forward pass confirmed on GPU. Pinned in `training/requirements-wsl.txt`. Reproduce: see "Training env" below. |
| **Design package** | ✅ Signed off (Meeting 4). 10 module LLDs + `docs/design/README.md` + `review.md` (3 blockers G-01/02/03 resolved) + 144-task backlog (`tasks_index.json`) + PDFs. |
| `android_client/` | Built once (2026-05-20) as `com.dima.offensivehebrew`. Package rename + Gradle flavors = Open Question (needs APK uninstall). |
| `server/sdk/` | Placeholder. Track C (SDK + Kotlin `:sdk-cli`) untouched — Meeting-5 demo blocker. |
| `training/` | Legacy QLoRA scripts only. **`prepare_data_dictabert.py` + `train_dictabert.py` = immediate next work.** |
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

1. **Spawn `ai-researcher-developer` for `training/prepare_data_dictabert.py`** (task #19, briefed & unblocked).
   Inputs: architecture §9 (data contract) + techniques §11 (locked stack). Outputs:
   `prepare_data_dictabert.py` + `data/{train,validation,test}.jsonl` + `class_weights.json` +
   `stylistic_eval.jsonl` (1040 held-out) + `validate_splits.py` (no-leakage asserts).
2. **Write `training/train_dictabert.py`** per locked architecture → train in WSL2 (~2–3 h) →
   checkpoint at `outputs/dictabert-offensive/`.
3. **Evaluate F1 ≥ 0.78 gate.** If pass → flip `CLASSIFIER_MODEL_VERSION=v1.1-dictabert` in `server/.env`, re-test end-to-end.
4. **In parallel:** populate `server/.env` with real LLM keys; start Track C (SDK + Kotlin CLI) for Meeting-5 demo.
5. **Deferrable (7 Important review issues):** G-04 port-naming · G-05 error model · G-06 PII scrub ·
   G-07 A/B eval doc · G-09 Slang Lexicon LLD · G-12 health rollup · G-14 gold-set annotation.

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
  **Phase 4** = the academic contribution: A/B image strategies (OCR vs vision-LLM vs pipeline vs parallel),
  pick default empirically (decision D1).
- **Research questions:** `plan-docs/research_questions.md` (8 RQs). Thesis spine = **RQ3 + RQ4** (multimodal architecture study).
- **Flagship anchors:** `plan-docs/related_work.md` — SinaLab Offensive-Hebrew (Hamad et al. 2023, arXiv:2309.02724)
  + QLoRA. Multimodal-moderation axis is the project's own contribution.

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
