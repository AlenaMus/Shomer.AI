# Reframe reconciliation — Decisions

**Phase:** Meeting 4 (architecture freeze)
**Decided on:** 2026-05-30
**Decided by:** Alona
**Purpose:** Close the loop between the M3 reframe (`D-Reframe-2026-05-27`) and the M4 architecture freeze (`architecture.decision.md`). One-page note documenting what the reframe means for POC Phases 2/4 now that the architecture is locked.

---

## D-Reconcile — How the locked architecture serves the reframed RQ

**Question:** After reframing the headline RQ from multimodal image-routing to conversational-context FP-reduction (2026-05-27), and then locking Architecture B + single Context Agent + DictaBERT + GPT-4o-mini (2026-05-30), what happens to the original POC `POC_Plan.md` Phases 2 (pluggable image backends) and Phase 4 (image-architecture A/B study)?

**Choice:** **Phases 2 and 4 are retired from the thesis scope and replaced by Phase-equivalents aligned with the new architecture:**

| Old POC Phase | New status | What replaces it |
|---|---|---|
| **Phase 2** — Pluggable image backends (Tesseract + Vision LLM + 4-strategy router) | **Reduced to OCR-only** | New "Phase 2′": Tesseract OCR pipeline only. No vision LLM, no strategy router. Single path. |
| **Phase 4** — Image-architecture A/B study (compare 4 routing strategies) | **Retired** | Replaced by new "Phase 4′": **Context-aware vs context-blind A/B study** on Hebrew text. This is the experiment that answers the new headline RQ. |

The other POC phases (0, 1, 3, 5, 6) are largely intact:
- Phase 0 (text-only smoke test) — already done in spirit (POC validated end-to-end on 23/05).
- Phase 1 (connection plumbing) — already done.
- Phase 3 (train Hebrew text classifier) — unchanged; now uses DictaBERT-base instead of Qwen.
- Phase 5 (SDK promotion) — unchanged.
- Phase 6 (evaluation + write-up) — unchanged.

**Why this reconciliation:**

The reframe established that the headline contribution is **showing that conversational context reduces FP in Hebrew bullying detection**. That contribution does not depend on having a vision LLM — and including one would muddy the experimental signal (as documented in `architecture.decision.md` → D-Arch-Variant).

The chosen architecture (B + Context Agent) directly mirrors the RQ's experimental design:
- The "context-blind" condition = DictaBERT alone, no Context Agent
- The "context-aware" condition = DictaBERT + Context Agent
- ΔFPR between them = the RQ's measurement

This means the architecture itself **is the experiment**. The image-routing study (old RQ3) would have required a separate experiment that didn't serve the new RQ.

**Alternatives considered:**

- *Keep Phases 2 & 4 alongside the new context work* — rejected because (a) doubles the build surface in a 6-meeting window, (b) the image-router study would have negligible relevance to the FP-reduction thesis, (c) Architecture A was explicitly considered and rejected in `D-Arch-Variant` for cost/quality/RQ-clarity reasons.
- *Retire all of Phase 2 entirely (no OCR)* — rejected because Chat-OCR is the bridge that lets us cover image-borne text content (the most common form of "image" in a child's chat) without going to a full vision LLM. OCR survives because it's *text extraction*, not *image classification*.
- *Defer the reconciliation until Meeting 8* — rejected because Meeting 5 (DictaBERT fine-tune) needs to start with a clear picture of what's being built. Ambiguity now costs build time later.

**Revisit:**

- If, in Meeting 8 evaluation, the architecture-B Context Agent fails to deliver meaningful ΔFPR (< 5pp improvement), reopen and consider whether multimodal signal (Architecture A) would have helped. This is a real fallback path, not just a courtesy note.
- If parents report (via the gold-set construction process in Meeting 8) that many real harms are image-only (not screenshots) — that's also a signal to reopen.

---

## Where each pre-reframe artifact stands

| Artifact | Pre-reframe framing | Post-reframe status |
|---|---|---|
| `docs/research_question/research_question.md` | Multimodal image-routing (old RQ3) | ✅ Updated 27/05 — now context-aware FP RQ |
| `docs/literature_flagship.md` | LLaVA + Tesseract + SinaLab anchors | ✅ Updated 27/05 — anchors are Pavlopoulos + Sap + SinaLab + ToxiGen + QLoRA |
| `docs/preparatory_report/preparatory_report.md` | Outlined architecture options including A | ✅ Updated to reflect Architecture B locked (this PRD-day) |
| `docs/business_plan/business_plan.md` | Multimodal pricing model | ✅ Compatible — cost numbers in §6 already match Architecture B (single Context Agent) |
| `poc/POC_Plan.md` (7-phase technical roadmap) | Phases 2, 4 = image router + image-strategy study | ⚠️ Out of sync — flagged for cleanup in Meeting 5 prep. Phase 2 → OCR-only; Phase 4 → context A/B. |
| `plan-docs/plan-meetings/04-prd-and-architecture.md` | Architecture-decision placeholder | ✅ Satisfied by this M4 decision + `architecture.decision.md` |

---

## Linked artifacts

- `plan-docs/decisions/research-framing.decision.md` (`D-Reframe-2026-05-27`) — the upstream reframe decision
- `plan-docs/decisions/architecture.decision.md` (this session) — the downstream architecture freeze
- `docs/PRD.md` — the artifact that operationalizes both
- `docs/architecture_diagrams.md` — visual proof that the architecture mirrors the experiment
- `poc/POC_Plan.md` — needs a Meeting-5 update pass per the Phase 2/4 reconciliation above
