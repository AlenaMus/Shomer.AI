# Shomer.AI — Project Context for Claude

This file is the load-bearing handoff document between sessions. Read it first.

---

## What this project is

**Shomer.AI** is Alona's graduate project: a Hebrew-language safety / offensive-content classification system built around a fine-tuned local LLM. As of 2026-05-23 the prior standalone prototype (`offensive-hebrew`) has been merged into this directory — there is now **one consolidated workspace**.

---

## Directory map

```
C:\AIDevelopmentCourse\Shomer.AI\
├── CLAUDE.md                ← this file
├── README.md                ← project README (migrated from prototype)
├── .git\                    ← git history (migrated from prototype)
├── .gitignore
├── plan-docs\               ← academic deliverables (proposal, meeting plan, summaries)
│   ├── POC_Plan.md          ← authoritative POC roadmap (7 phases)
│   ├── Shomer_AI_Project_Proposal.docx   ← authoritative scope
│   ├── Shomer_AI_10_Meeting_Plan.docx
│   ├── Shomer_AI_Sources_Summary.docx
│   ├── 1_Papers_Summary.docx
│   ├── 2_Datasets_Summary.docx
│   └── 3_Technologies_Summary.docx
├── integration\             ← integration test plans, one per POC phase
│   ├── README.md            ← naming convention + index
│   └── integration-1.md     ← Phase 1 (connection plumbing) test plan
├── prompts\                 ← per-session prompts log (date + meeting #), one .md per working session
│   ├── README.md            ← convention + template pointer
│   └── _template.md         ← copyable template for a new session file
├── android_client\          ← Kotlin + Compose client (Settings screen for server URL)
├── server\                  ← FastAPI service
│   ├── app\                 ← /health, /model/info, /classify, /classify-image → calls Ollama
│   ├── logs\                ← per-day audit JSONL: audit-YYYY-MM-DD.jsonl (gitignored)
│   └── sdk\                 ← shared client library for android_client + future web_client (placeholder)
└── training\                ← QLoRA fine-tune on SinaLab/Offensive-Hebrew, exports GGUF
```

The `server/sdk/` folder is the **shared client library** that every client (Android, web, future others) imports to talk to the FastAPI server. As of 2026-05-23 it's a placeholder with a README only — the generated-from-OpenAPI vs hand-written choice is deferred until the first real integration. Clients keep their own minimal HTTP layer in the meantime.

Architecture:
```
[Android (Kotlin/Compose)] --HTTP--> [FastAPI :8000] --HTTP--> [Ollama :11434] -> offensive-hebrew:v1
```

---

## Current status (as of 2026-06-01)

| Area | State |
|---|---|
| Workspace | **Consolidated.** `offensive-hebrew` migrated 2026-05-23; old path `C:\Users\Dima\Projects\offensive-hebrew\` is gone. |
| **Design package** | ✅ **Ready for Meeting 4 sign-off (2026-06-01).** `docs/design/` contains 10 module LLDs (~5,470 lines) + `README.md` (ports-and-adapters principles) + `review.md` (architecture review, all 3 blockers resolved) + 144-task backlog across 10 `tasks.json` files + `tasks_index.json` + 12 PDFs. See "Session update — 2026-05-31 → 2026-06-01" below. |
| `server/` | Code skeleton present (`main.py`, `classifier.py`, `audit.py`, `middleware.py`, `schemas.py`, `ollama_client.py`, `prompt.py`, `image_backends/`). Architecture refactor per the new server LLD is Sprint-1 work. Stand-in `Modelfile.standin` (`qwen2.5:7b-instruct` + system prompt) keeps the stack runnable before DictaBERT training. |
| `android_client/` | Built once (2026-05-20) under `com.dima.offensivehebrew`. The new LLD recommends a package rename to `com.shomer.client` + Gradle product flavors (Child/Parent) — flagged as an Open Question in `android_client/design.md` because it requires APK uninstall. |
| `server/sdk/` | Still a placeholder. `sdk/design.md` + 16 SDK tasks (incl. new `:sdk-cli` Gradle subproject for terminal SDK runner — SDK-CLI-01/02/03) are ready to execute. |
| `training/` | Scripts present, **never executed.** `train_dictabert.py` is a new Meeting-5 task (the existing `train_lora.py` targets generative models; DictaBERT-base needs `AutoModelForSequenceClassification`). |
| `server/.venv/` | **Stale after migration.** Recreate before first Sprint-1 task: `python -m venv .venv ; .\.venv\Scripts\Activate.ps1 ; pip install -r requirements.txt`. |
| Local tooling | Android Studio installed. Ollama installed. MiKTeX installed (xelatex). Microsoft Edge installed (for `scripts/md_to_pdf.py`). **GPU: NVIDIA RTX 5080, 16 GB VRAM, CUDA `sm_120` (Blackwell), driver 591.86; 64 GB system RAM.** Blackwell needs CUDA 12.8+ and `sm_120`-aware PyTorch/bitsandbytes wheels in WSL2. |

---

## Session update — 2026-05-24 (planning + Meeting-3 prep)

> **Doc-direction note:** Hebrew `.md` files are now wrapped in `<div dir="rtl">…</div>` (RTL) — see Conventions. English-only docs stay LTR.

**Produced this session:**
- **`plan-he/`** — Hebrew, course-aligned plan (11 files: `README.md` + `01`–`10`), mapped to Dr. Segal's **official 10-meeting roadmap** (not the `plan/` 0–10 numbering). Includes a gap-analysis table. `plan-docs/plan/` (English) remains the technical source of record.
- **`plan-docs/decisions/plan-he-alignment.decision.md`** — records (D1) follow Segal's roadmap; (D2) SDK + AI-agent mandate + SUNO/Nano-Banana are **mandatory** (were optional in `plan/`).
- **`docs/next-meeting-prep-2026-05-28.md`** — execution plan for **Meeting 3 (Thu 28/05/2026)** via the `hebrew-ai-project-manager` skill: 9 tasks with deadlines, open questions, 3-option decisions, agenda.
- **`plan-docs/m3/`** — one Hebrew file per Meeting-3 task (`01`–`09`).
- **Meeting-3 deliverables started (✅ done):** `docs/research_question.md` (main RQ = **RQ3** multimodal routing + RQ1 foundational) and `docs/literature_flagship.md` (anchors: **SinaLab Offensive-Hebrew** + **QLoRA**).

**Meeting 3 (28/05) — what's due:** preparatory report (דו"ח מכין), adapted research question (✅), business plan **in LaTeX**. Hard deadline = meeting day.

**Remaining Meeting-3 tasks** (see `plan-docs/m3/`): ⬜ 3 prep report · ⬜ 4–6 business plan (LaTeX) · ⬜ 7 prompt book · ⬜ 8 GitHub commit+tag · ⬜ 9 agenda.

**▶ Next session (tomorrow):** (1) continue **implementing the Meeting-3 steps** — start with task 3, `docs/preparatory_report.md` (the 7-component report, depends on the two done docs); then the LaTeX business plan. (2) Run an **implementation analysis** of what's been done — `hebrew-ai-project-manager` Module 1 → `docs/implementation-summary-2026-05-25.md`.

---

## Session update — 2026-05-27 (Meeting-3 deliverables built)

Built the remaining Meeting-3 deliverables, in parallel via sub-agents + main thread:

- **`docs/preparatory_report.md`** ✅ — the 7-component "work contract" (slide 9). Reconciles the older Proposal framing (DictaBERT + agents + synthetic data) with the locked RQ3-multimodal / QLoRA spine; presents architecture as **tentative**, with the model + agents-vs-single-server decisions explicitly deferred to Meeting 4 (per `decisions/plan-structure.decision.md`).
- **`docs/literature_flagship.md`** ✅ — citations verified/corrected via web. **SinaLab citation was wrong** — corrected to **Hamad, N., Jarrar, M., Khalilia, M., & Nashif, N. (2023), "Offensive Hebrew Corpus and Detection using BERT," AICCSA, arXiv:2309.02724** (lead author Hamad, not Jarrar). DictaLM 2.0 → Shmidman et al. 2024, arXiv:2407.07080. New **`docs/references.bib`** created.
- **`docs/business_plan/business_plan.tex` (+ `.pdf`)** ✅ — 6-section Hebrew/RTL plan, **compiled to a 4-page PDF with XeLaTeX/MiKTeX** (David CLM font; 0 errors, 0 missing glyphs). Verified market/pricing/token numbers via web; unsourced ones tagged `[למקור]`. Font line uses an `\IfFontExistsTF` fallback chain so it compiles on **both** Overleaf and local Windows+MiKTeX. Fixed during compile: a hyperref/bidi load-order crash, a missing-monospace-font error, and cost-section math (rewrote so math nests inside `\textenglish{}`, not a language-switch inside math).
- **`docs/prompt-book.md`** ✅ — Path A (Claude Code as dev agent), 3 entries in the 7-field format.

**PDF generation:** `scripts/md_to_pdf.py` converts Hebrew RTL Markdown → styled RTL HTML → PDF via **headless Edge** (no LaTeX/font setup). Generated `.pdf` for all 5 Hebrew docs under `docs/`. Re-run after editing any `.md`: `python scripts/md_to_pdf.py [files...]` (needs `pip install markdown`, already installed).

**LaTeX:** **MiKTeX is installed** (via `choco`; `xelatex` lives at `C:\Program Files\MiKTeX\miktex\bin\x64\` — not yet on this shell's PATH, call by full path or open a fresh terminal). The business plan compiles clean locally. The Edge route (`scripts/md_to_pdf.py`) is only for the Markdown docs, not the `.tex`.

**Open / next:** (1) reconcile 3 minor RQ-numbering inconsistencies between `research_question.md` and `literature_flagship.md` (RQ4 framing drift; RQ5 and RQ7 appear in one doc but not the other); (2) fill the `[למקור]` numbers in the business plan after the meeting; (3) `commit` + `tag` for Meeting 3 (task 8 — only when user asks); (4) confirm meeting time/platform. Meeting 3 is **28/05/2026**.

---

## Session update — 2026-05-31 → 2026-06-01 (Design package built; ready for Meeting 4)

Delivered the full pre-implementation design package for Meeting 4: a 10-module Low-Level Design suite + 144-task backlog + architecture review + 12 PDFs. The package is the blueprint for the Meeting 5–8 engineering work.

**What landed (in order):**

1. **9 module LLDs at `docs/design/<module>/design.md`** — three product-strategist sub-agents in parallel produced `android_client/` (409 L), `sdk/` (488 L incl. new §3.5), `gatekeeper/` (441 L), `ocr/` (449 L), `classifier/` (598 L), `context_agent/` (1019 L), `triage/` (478 L), `alerts/` (715 L), `server/` (~1180 L incl. new §9a). Same 11-section template every module. Context Agent adds §6.4 TokenManager (Protocol + SQLite + Prometheus + budget-exhausted fallback).

2. **OOP / ports-and-adapters enhancement pass** — every LLD gained an explicit §2.5 "Interface boundary & isolation guarantees" naming the Port (Protocol) + ≥2 concrete adapters. New `docs/design/README.md` (~17 KB) codifies the rule: `server/app/main.py` `lifespan()` is the **only** place concrete adapters are constructed → swapping Tesseract → EasyOCR, DictaBERT → DictaLM-2.0, GPT-4o-mini → Haiku is a **one-line change**.

3. **JSON task backlogs** at `docs/design/<module>/tasks.json` + `tasks_index.json` — rich schema (id, type, priority, estimate_hours, depends_on, acceptance_criteria, related_prd_section, related_nfr, related_files, phase, meeting, labels). Every module guarantees `*-IF-01` (Protocol), `CFG-01`, `LOG-01`, `MET-01`, `CT-01` (contract test), `UT-01`, `IT-01`, `DOC-01`, `FAIL-01`.

4. **Architecture review at `docs/design/review.md`** — coverage matrix against PRD §1-§15, all 3 Mermaid diagrams, locked decisions, plus 10 cross-cutting concerns walked end-to-end. Initial verdict: **Conditional Ready (3 Blockers · 7 Important · 5 Nice-to-have)** → upgraded to **Ready** after the 3 blockers were fixed.

5. **3 Blockers resolved (G-01, G-02, G-03):**
   - **G-01 — Audit Log was not a first-class module.** Created `docs/design/audit_log/` LLD (758 L) + 14 tasks. 5-table SQLite schema (`classifications`, `agent_traces`, `alerts`, `conversations`, `gold_set_metadata`) with the Meeting-8 ΔFPR query columns baked in (`gold_label`, `frontline_only_decision`, `context_agent_enabled` filter). WAL mode, `NullAuditStore` degraded-mode adapter, 7-day `RetentionSweeper`. `SERVER-LIFESPAN-01` and `CTX-TOOLS-01` now depend on `AUDIT-IF-01`.
   - **G-02 — Label spelling locked to `non_offensive`** (underscore — matches runtime in `schemas.py`/`prompt.py`). Updated `PRD.md` §8.1, `classifier/design.md` §1/§2.2/§5.2/§6.1/§8/§11, `classifier/tasks.json`. Remaining hyphenated mentions in `references.bib` + `literature_flagship.md` are intentional citations of SinaLab's upstream column name.
   - **G-03 — Confidence-direction footgun in triage**: `_decide_inner` now does Step A `prob_offensive = result.confidence if result.is_offensive else 1 - result.confidence` BEFORE Step B threshold routing. 6-row polarity test matrix added as mandatory contract test. Bug: `is_offensive=False, confidence=0.92` would have routed to `ALERT_DIRECT`; now correctly maps to `SILENT` (prob_offensive=0.08).

6. **Terminal SDK runner + Python dev tools** (6 new tasks):
   - **`SDK-CLI-01/02/03`** — new Gradle `:sdk-cli` subproject at `server/sdk/kotlin-cli/` wrapping `ShomerClient` (zero HTTP re-implementation). Subcommands: `classify` / `classify-image` / `health` / `info` / `demo` / `batch`. The `demo` subcommand runs a curated golden set; the `batch` subcommand runs JSONL inputs at bounded concurrency for Meeting-8 gold-set evaluation.
   - **`SERVER-DEV-CLI-01/02/03`** — `scripts/dev_client.py` (httpx dev CLI with `replay <trace_id>` regression mode), `scripts/inspect_audit.py` (read-only SQLite inspector), `scripts/load_test.py` (NFR validation with Markdown report). All three share the same `golden_inputs.jsonl` schema as the Kotlin CLI → cross-language wire-protocol contract test.
   - LLD additions: `sdk/design.md` §3.5, `server/design.md` §9a.

7. **12 design PDFs** at `docs/design/{README,review,*/design}.pdf` (~5.6 MB total) via `scripts/md_to_pdf.py`. Minor direction-agnostic CSS tweak (`text-align: start`, `padding-inline-start`, `border-inline-start`) so the script renders both Hebrew RTL docs and English LTR design docs correctly.

**Backlog stats (10 modules, 144 tasks):**

| Module | Tasks | Module | Tasks |
|---|---|---|---|
| alerts | 13 | gatekeeper | 11 |
| android_client | 16 | ocr | 12 |
| audit_log (NEW) | 14 | sdk | 16 |
| classifier | 13 | server | 20 |
| context_agent | 18 | triage | 11 |
| | | **Total** | **144** |

**Open / next session priorities (Meeting 4 → Meeting 5 ramp):**

1. **Meeting 4 (date TBD)** — present the package to Dr. Segal. PRD v1.0 + Architecture B + 144-task backlog + 12 design PDFs are ready. Decisions to confirm: Architecture B sign-off, RQ3 framing, deferral of 7 Important issues to week 1 of implementation.
2. **Sprint 1 (Meeting 5)** — the **10 `*-IF-01` Protocol-definition tasks** are the natural starting point; they have no upstream dependencies and unblock everything downstream. Recommended first: `AUDIT-IF-01` (it blocks `CTX-TOOLS-01`, `SERVER-LIFESPAN-01`, `ALERTS-DB-01`).
3. **Reconciliation pass (Important, not blocking sprint start):**
   - **G-04** Port-naming drift (`TriageRouter`↔`TriageEngine`, `NotificationService`↔`NotificationChannel`, `ContextAgentProtocol`↔`ContextReasoner`, `TokenManagerProtocol`↔`TokenBudgetGuard`) — pick one set + grep-replace, ~30 min.
   - **G-05** Android `ClassificationSource` (throws) vs SDK `ShomerApi` (returns `ShomerResult<T>`) error-model mismatch — pick one before `SDK-CLIENT-01` lands.
   - **G-06** PII scrub before LLM call — needs implementation owner (likely `context_agent`).
   - **G-07** Meeting 8 A/B evaluation procedure — needs a full doc.
   - **G-09** Slang Lexicon — needs its own LLD (currently only referenced as `SlangDB` C4 box + Context Agent's `lookup_slang` tool).
   - **G-12** `/health` rollup missing OCR + Context Agent checks.
   - **G-14** gold-set annotation procedure (partially answered by `AUDIT-GOLD-01`).
4. **Repo hygiene before Sprint 1:** recreate `server/.venv/` (stale paths); re-open `android_client/` in Android Studio from the new path; consider initial commit + tag `v0.4-design-frozen` once Meeting 4 signs off.

---

## Post-migration cleanup checklist

1. Close any terminal still sitting in `C:\Users\Dima\Projects\offensive-hebrew\`, then delete that empty folder.
2. Re-open the Android project in Android Studio from `C:\AIDevelopmentCourse\Shomer.AI\android\`. Let it re-sync Gradle. If it complains, **File → Invalidate Caches & Restart**.
3. Recreate the server venv (see table above).
4. Verify git still works from the new root: `git status` inside `C:\AIDevelopmentCourse\Shomer.AI\` should report the prototype's branch cleanly.
5. The prototype `README.md` is now at the workspace root next to `CLAUDE.md`. Decide whether to keep it as-is, merge its content into a single README, or move it under `plan-docs\`.

---

## Plan (high level)

The **master project plan** is **`plan-docs\Plan.md`** — a short overview of the 10 academic meetings, with one detail file per step in **`plan-docs\plan\`** (`00-poc-feasibility.md` … `10-defense-and-submission.md`). The POC is reframed there as **Step 0 — a feasibility check (done)**, not the whole project. The architecture (DictaBERT-vs-Qwen, agents-vs-single-server) is deliberately **left open until Meeting 4** — see `plan-docs\decisions\plan-structure.decision.md`.

`plan-docs\POC_Plan.md` is the **technical roadmap** for the app/server/image work — seven phases (0–6), tracked with checkboxes. It feeds steps 0, 5, 7, 8 of the master plan. Read it for the engineering breakdown.

Summary:
- **Phase 0** — recover the text stack on the stand-in model (post-migration smoke test).
- **Phase 1** — connection plumbing for text **and** image (image processor is a stub — just proves the wire).
- **Phase 2** — pluggable image backends (Tesseract OCR + vision LLM via Ollama) + strategy router (`ocr_only` / `vision_only` / `pipeline` / `parallel`).
- **Phase 3** — train the real Hebrew text classifier in WSL2, swap into Ollama.
- **Phase 4** — **architecture study**: A/B the image strategies on a labelled image set; pick the default. This is the academic contribution.
- **Phase 5** *(optional)* — promote `server/sdk/` from placeholder to real shared client library.
- **Phase 6** — evaluation + academic write-up.

**Image handling is dual-track on purpose:** the server supports OCR (for text-bearing images like screenshots/signs) AND a vision LLM (for real photos) AND combinations. Which one is the "right" default is decided empirically in Phase 4 — see `POC_Plan.md` §5 (decision D1).

## Academic framing

- **Research questions** (8 RQs, mapped to meetings): `plan-docs\research_questions.md`. Thesis spine = RQ3 + RQ4 (multimodal architecture study).
- **Flagship-paper anchors**: `plan-docs\related_work.md`. Two intentional anchors — SinaLab Offensive-Hebrew (dataset + task) and QLoRA (methodology). The multimodal-moderation axis is explicitly the project's own contribution.
- **Decision capturing both**: `plan-docs\decisions\research-framing.decision.md`.

---

## Decision capture — REQUIRED on every session

Any time you (Claude or a future assistant) prompt the user for a decision — model choice, library choice, architecture branch, default value, etc. — and they choose, capture it in a markdown file. This applies to **every session**, no exceptions, even tiny phases.

**File location and naming:**
- One file per phase / step: `plan-docs/decisions/<phase-or-step>.decision.md`.
- Examples already in place: `plan-docs/decisions/phase-1.decision.md`, `plan-docs/decisions/phase-2.decision.md`.
- If the decision is bigger than a phase (e.g. a project-wide convention), name it accordingly: `plan-docs/decisions/project-conventions.decision.md`.

**Per-decision structure** (copy from existing files for consistency):

```markdown
## D<id> — <short title>

**Question:** the original question put to the user.
**Choice:** what was decided.
**Why:** the user's stated reasoning + anything implicit but defensible.
**Alternatives considered:** other options that were on the table, briefly, with why each was passed over.
**Revisit:** condition under which this decision should be reopened (a Phase milestone, a metric threshold, a use-case change).
```

**When to write:**
- Right after the user answers a multi-option `AskUserQuestion`.
- After any back-and-forth dialogue where the user picks between two or more substantive paths.
- After a free-text instruction that locks an architectural direction ("we'll use Tesseract not PaddleOCR").

**When NOT to write:** routine clarifications (file paths, names), small formatting choices, things that are derivable from code or git history. The bar is "would future-me, reopening this in 6 months, want a one-paragraph explanation of why we picked this?"

**Backfill is allowed but mark it as backfill** — a note at the top of the file saying so, so the audit trail stays honest.

---

## Session prompts log — REQUIRED on every session

Every working session must leave behind a digest of what the user asked for and what was produced, dropped into `prompts/`. This is the audit trail for "what happened between meetings" — it makes it trivial to walk into the next meeting with a one-page recap, and it gives the next session's assistant a fast catch-up beyond what CLAUDE.md captures.

**File location and naming:**
- One file per working session: `prompts/YYYY-MM-DD_meeting-N.md`.
- `YYYY-MM-DD` is the session date (today's date, in absolute ISO form — convert any relative phrasing like "yesterday" or "Thursday" to the actual date).
- `N` is the **next upcoming meeting number** the session is preparing for. After a meeting just happened, `N` is the *following* meeting, not the one that passed. Example: today is 30/05/2026; Meeting 3 was on 28/05/2026; the upcoming meeting is Meeting 4 → today's file is `prompts/2026-05-30_meeting-4.md`.
- If multiple sessions happen on the same date for the same meeting, append `-2`, `-3`, … (e.g. `2026-05-30_meeting-4-2.md`).

**Per-session structure** (see `prompts/_template.md` for the copyable form):

```markdown
# Session prompts — YYYY-MM-DD · Meeting N prep

**Date:** YYYY-MM-DD
**Preparing for:** Meeting N (date if known)
**Session focus:** one-line headline of what dominated the session.

## Turn-by-turn digest

### 1. <short label for the prompt>
**Prompt (1-line restatement):** what the user asked, in your own words.
**Delivered:** what was produced — bullet list, links to files created/edited.
**Decisions / files of note:** any new `.decision.md` entries, new skills, new docs.

### 2. <next prompt label>
...

## Open / carry-over to next session
- Outstanding work, blockers, or follow-ups the next session should pick up.

## Files touched this session
- `path/to/file.md` — what changed
- `path/to/other.py` — created
```

**When to write:**
- Append turn entries *as the session progresses* (after each substantive user prompt and the response that closed it out). Don't try to reconstruct from scratch at session end — by then the early turns are blurry.
- The first prompt in a session creates the file; every subsequent prompt appends a new `### N. …` block.

**Restatement, not transcript:** the digest paraphrases the prompt and what was delivered. It is not a verbatim transcript — keep each turn entry short enough to scan in a glance (~3–6 lines per turn). Link out to the actual artifacts rather than quoting them.

**Relationship to decision files:** the prompts log records *what happened*; `plan-docs/decisions/*.decision.md` records *what was decided and why*. When a turn produces a decision, the digest entry should link to the decision file rather than restating the rationale.

**When NOT to write:** sessions consisting of one trivial question with no produced artifact (e.g., "what's the meeting date?"). Bar: if the session changed or created any file, log it.

## Conventions for this project

- **Don't assume training has run** — no GGUF exists yet; the stand-in path is the default.
- **Default to English** for code, comments, commit messages. Hebrew is the *domain language* (the text being classified), not the working language.
- **Hebrew Markdown docs must render RTL (MANDATORY).** Every **Hebrew-language** `.md` file authored for this project is wrapped so it renders right-to-left: first line `<div dir="rtl">` followed by a blank line, and `</div>` as the last line (preceded by a blank line). Markdown inside the wrapper still renders (keep blank lines after the opening and before the closing tag). Applies to new Hebrew docs under `plan-he/`, `docs/`, `plan-docs/m3/`, etc. **English-only `.md` files stay LTR — do not wrap them** (e.g. `plan-docs/plan/*`, `Plan.md`, `README.md`, this file).
- **Shell is PowerShell on Windows.** WSL2 is used only for training (Linux-first tools: Unsloth, bitsandbytes, llama.cpp). When invoking WSL paths from inside WSL, the new root is `/mnt/c/AIDevelopmentCourse/Shomer.AI/`.
- **Username on the machine is `Dima`; the user is Alona.** Don't conflate the two.
- Android emulator URL: `http://10.0.2.2:8000/`. Physical phone: `http://<PC-LAN-IP>:8000/` (firewall rule, one-time, elevated PowerShell: `New-NetFirewallRule -DisplayName "OffensiveHebrew" -Direction Inbound -LocalPort 8000 -Protocol TCP -Action Allow`).
- Anywhere docs or scripts still reference `C:\Users\Dima\Projects\offensive-hebrew\` or `/mnt/c/Users/Dima/Projects/offensive-hebrew/`, those paths are stale — update on sight.

---

## How to resume next session

1. Read this file.
2. Verify the post-migration checklist above is done — if not, finish it first.
3. Skim the most recent file under `prompts/` for the previous session's digest and carry-over items.
4. Continue from the current "Plan" step. Open today's prompts log (`prompts/YYYY-MM-DD_meeting-N.md`) on the first substantive prompt and append turn-by-turn as the session progresses (see "Session prompts log — REQUIRED on every session" above).
5. **2026-06-01 →:** see the "Session update — 2026-05-31 → 2026-06-01" block above. Design package is **Ready** at `docs/design/`. Meeting 4 awaits sign-off. Immediately after Meeting 4 sign-off, Sprint 1 = the **10 `*-IF-01` Protocol-definition tasks** (start with `AUDIT-IF-01` — it blocks the most downstream work). Track via `docs/design/tasks_index.json` (144 entries). Before any coding: recreate `server/.venv/` and re-open `android_client/` from the new path. The 7 Important review-issues (G-04, G-05, G-06, G-07, G-09, G-12, G-14) can be addressed in parallel with Sprint 1 — do not block on them.

<!-- Append resolution notes below this line as the project progresses. -->
