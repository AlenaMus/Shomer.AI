# Decision — `plan-he/` course-alignment

> Captured 2026-05-24, same session the folder was created. Not a backfill.
> Triggered by Alona's instruction: compare the existing `plan/` summaries to Dr. Segal's
> final-project PDF and create a Hebrew per-meeting plan in a new `plan-he/` folder.

## D1 — Structure `plan-he/` on Dr. Segal's official 10-meeting roadmap (not the existing 0–10)

**Question:** Should the Hebrew plan follow the existing `plan-docs/plan/` numbering (Step 0 POC + Meetings 1–10, where dev = meetings 5–8 and presentation = 9–10), or Dr. Segal's official course roadmap from the final-project PDF (10 meetings, dev = 5–7, promo video = 8, report = 9, defense = 10)?

**Choice:** Follow Dr. Segal's **official 10-meeting roadmap**. `plan-he/` is the "course-aligned view"; `plan-docs/plan/` (English) remains the technical source of record. Consequences applied:
- The POC (old Step 0) is folded into Meeting 1's "Doable" evidence — no standalone file.
- Development is compressed into Meetings 5–7. The old `08-gold-set-and-metrics` content moves **into Meeting 7 (בדיקות)**.
- **Meeting 8 = promo video only** (Nano Banana + SUNO), not gold-set/metrics.
- Old `09-production-and-marketing` is split: video → Meeting 8, report+deck → Meeting 9.

**Why:** Alona's phrasing was "כל מפגש בקורס" (each meeting in the course) and the comparison anchor is the course PDF, so the deliverable must mirror the examiner's own structure. The existing plan over-packed development (4 dev meetings) and pushed the video to Meeting 9, which contradicts the PDF that makes the video Meeting 8.

**Alternatives considered:**
- *Keep the existing 0–10 numbering, just translate to Hebrew* — rejected: it would not surface the structural gaps the user asked to find ("תשווה"), and would leave the plan misaligned with how Dr. Segal grades.
- *One merged bilingual file set* — rejected: keeps English `plan/` as source of record and avoids drift; the Hebrew set is a derived course-facing view.

**Revisit:** If Dr. Segal issues a revised meeting schedule, or if Meeting 4 freezes an architecture that needs more than three development meetings (5–7) — then re-balance the dev/presentation split.

## D2 — Promote SDK, AI-Agent mandate, and SUNO/Nano-Banana from "optional" to mandatory

**Question:** The PDF makes SDK (single entry point), meaningful AI-Agent use, and the SUNO theme song hard requirements. The existing plan treats SDK as optional (POC_Plan Phase 5), leaves agents undecided, and marks the theme song "(Optional)". Honor the PDF or the existing plan?

**Choice:** Honor the PDF. `plan-he/` flags all three as **mandatory** and assigns owners:
- **SDK** → Meeting 5 (`05-שלד-מערכת`): real single-entry core, all clients route through it.
- **Agent mandate** → Meeting 4 (`04-ארכיטקטורה`): must be satisfied via Path A (Claude Code as documented dev tool) and/or Path B (context/alert step as a product agent), regardless of the DictaBERT-vs-Qwen / agents-vs-single-server outcome.
- **SUNO + Nano Banana** → Meeting 8: first-class deliverables.

**Why:** These are pass/fail criteria in Dr. Segal's guide ("חוק הזהב: סוכני AI הם חובה"; "SDK הוא שער הכניסה היחיד"). Leaving them optional risks the defense.

**Alternatives considered:** *Defer SDK to a stretch goal* — rejected: the PDF explicitly schedules SDK at Meeting 5 and forbids bypassing it.

**Revisit:** The agent-mandate framing depends on the Meeting 4 architecture decision (`architecture.decision.md`); reconcile once that is frozen.
