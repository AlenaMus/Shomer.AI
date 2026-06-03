# Plan structure & POC framing — Decisions

**Scope:** project-wide planning convention (bigger than a single phase)
**Decided on:** 2026-05-24
**Decided by:** Alona, with options presented by Claude

---

## D-Plan-Shape — How the project plan is structured

**Question:** Should the plan be one document, or a short master plan plus a detail file per item?

**Choice:** **Short, clear master plan (`plan-docs/Plan.md`) + one detail file per meeting in `plan-docs/plan/`** (`00-poc-feasibility.md` … `10-defense-and-submission.md`).

**Why:** Alona asked for a plan that is "clear and short" with "all relevant steps elaborated" and "additional md files related to each item." A thin master that links out keeps the overview scannable while each meeting's detail stays editable in isolation.

**Alternatives considered:**
- *Single master file only:* loses the per-item detail Alona explicitly asked for.
- *One file per deliverable (finer than per-meeting):* too many files and cross-links for a 10-meeting project; per-meeting is the natural unit.

**Revisit:** if a meeting grows large enough to warrant sub-files, split that one meeting then.

---

## D-Plan-POC-Framing — What the POC is, and where it sits

**Question:** Is the POC the whole project roadmap, or just the first step?

**Choice:** **The POC is Step 0 — a feasibility check only** ("can an Android app call a server on my computer and get a Hebrew answer back"). It is recorded as a *summary of what was built and the results* in `plan/00-poc-feasibility.md`, placed as the first step of the plan, and explicitly marked as subject to change once the full plan is approved.

**Why:** Alona clarified the POC was "only first meeting requirement … to see if its possible to create app and call my server," not the final architecture. Framing it as a done feasibility step (and the "Doable" evidence for Meeting 1) keeps it useful without freezing any design choices around it.

**Alternatives considered:**
- *Treat the 7-phase `POC_Plan.md` as the master plan:* too long and too narrow (image/app focused); it is kept instead as the **technical roadmap** that feeds steps 0, 5, 7, 8.

**Revisit:** never for the framing; the POC summary itself gets superseded as real steps replace the stand-in pieces.

---

## D-Plan-Architecture-Open — Architecture basis left undecided

**Question:** Should the plan follow the approved proposal (DictaBERT + 3 agents + RAG) or the current POC prototype (Qwen 2.5 via Ollama, single server, image-strategy study)?

**Choice:** **Neither yet — left open.** The plan keeps the proposal's academic structure and deliverables, but technical steps (5–8) are provisional, and the model/architecture choice is **deferred to Meeting 4** (`plan/04-prd-and-architecture.md`), to be recorded in `decisions/architecture.decision.md`.

**Why:** Alona stated the plan "is still not approved." Locking DictaBERT-vs-Qwen or agents-vs-single-server now would pre-empt a decision that belongs at the design-freeze meeting and likely needs mentor sign-off.

**Alternatives considered:**
- *Match current build now:* cleanest, but drops the mentor-approved agent design without his input.
- *Keep proposal as-is now:* would make the working prototype "off-plan" with no rationale recorded.

**Revisit:** **Meeting 4** — architecture freeze. That decision unblocks steps 5–8.

---

## Linked artifacts

- Master plan: `plan-docs/Plan.md`. Detail files: `plan-docs/plan/00`…`10`.
- POC evidence: `integration/results/integration-1/` (emulator + Huawei P20 Pro, both PASS); `server/logs/audit-2026-05-23.jsonl`.
- Open architecture decision will live in: `plan-docs/decisions/architecture.decision.md` (to be written at Meeting 4).
