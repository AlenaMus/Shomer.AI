# Research framing — Decisions

**Phase:** master plan, Meeting 02 (Literature & baseline) framing.
**Decided on:** 2026-05-24
**Decided by:** Alona, with options surfaced by `ai-researcher-developer` agent (proxied via Claude).

Captures the explicit decisions made when the academic framing of the project was first formalised. Future Meetings 02–10 build on these; revisit conditions are listed per decision.

---

## D-Research-Anchors — Which paper(s) anchor the thesis intellectually

**Question:** "What flagship paper(s) should the thesis anchor on as the primary intellectual reference?"

**Choice:** **Two anchors, intentionally**:
1. **SinaLab Offensive-Hebrew dataset** (Jarrar et al., SinaLab/Birzeit) — dataset + task anchor; defines the schema and the baseline numbers.
2. **QLoRA** (Dettmers, Pagnoni, Holtzman, Zettlemoyer, NeurIPS 2023, arXiv:2305.14314) — methodology anchor; defines the fine-tuning recipe.

**Why:** the project sits at an intersection (low-resource Hebrew offensive classification + parameter-efficient fine-tuning + multimodal moderation + local deployment) that no single 2022+ paper covers. Forcing one anchor would either make the dataset choice look arbitrary or make the QLoRA-shaped methodology look orphaned. Two anchors, each owning a different axis, is honest. The multimodal-moderation axis is explicitly framed as the contribution — no anchor needed, because none exists.

**Alternatives considered:**
- *Anchor on LLaVA (Liu et al., 2023):* establishes the multimodal LLM paradigm but doesn't say anything about Hebrew, offensive content, OR fine-tuning. Becomes a supporting citation, not an anchor.
- *Anchor on a Hebrew NLP general-survey paper:* too broad — would frame the thesis as "applied Hebrew NLP" instead of "multimodal Hebrew moderation".
- *Anchor on OLID / HatEval (English offensive-classification benchmarks):* gives a methodology template but bypasses the Hebrew-specificity, weakening the dataset story.

**Revisit:** if Meeting 02's full literature review surfaces a 2024+ paper that genuinely covers multimodal Hebrew moderation, promote it as the third anchor (or replace one of the two).

---

## D-Research-Questions — Which RQs the thesis attempts to answer

**Question:** "Which research questions should structure the thesis, given the existing 7-phase POC plan and a budget of a single graduate student?"

**Choice:** **8 RQs adopted**, organised by intellectual altitude (descriptive / comparative / mechanistic / practical). See `../research_questions.md` for full text. Headline contribution = **RQ3 + RQ4** (the multimodal architecture study).

Thesis structure recommended:
- **Foundation chapter** (Meeting 05): RQ1 + RQ2.
- **Spine / multimodal architecture** (Meeting 08): RQ3 + RQ4.
- **Deployment chapter** (Meetings 08–09): RQ5 + RQ7.
- **Stretch / optional**: RQ6 + RQ8.

**Why:** the 8 RQs map cleanly to the existing meeting plan (`plan/02-…` through `plan/10-…`), so no additional infrastructure is needed to answer them. Mixing intellectual altitudes (descriptive → mechanistic → practical) makes the thesis feel substantive rather than just empirical.

**Alternatives considered:**
- *A single overarching RQ:* cleaner narrative but loses the per-chapter structure that makes a thesis defensible.
- *More RQs (12+):* maps better onto every plan-doc line but creates a too-thin contribution per RQ.
- *Fewer RQs (3–4):* defensible if the multimodal study is rich enough, but loses the "different intellectual altitudes" framing.

**Revisit:**
- After Meeting 04 (PRD & architecture) — if scope tightens, RQ6 and RQ8 are the explicit drop candidates.
- After Meeting 08 (gold set built) — **no new RQs may be added** to avoid data dredging; only RQs already on this list get answered.
- If the gold set turns out smaller than ~80 images (instead of the planned 100–200), reconsider RQ3's bucket-level claims.

---

## D-Reframe-2026-05-27 — Headline RQ changed: multimodal routing → conversational context

**Decided on:** 2026-05-27. **Decided by:** Alona, in dialogue (Claude surfaced the options + literature).

**Question:** "Does the research question have to be tied to the implementation/architecture, or can it instead measure how many false positives the system produces and how well it actually detects bullying — given that context is often misunderstood and the architecture isn't locked yet?"

**Choice:** **Yes — the RQ is reframed.** The headline RQ is no longer the multimodal image-routing study (former RQ3). The new primary RQ is a *capability/measurement* question, architecture-agnostic:

> *To what extent does adding conversational context (prior turns in the thread) to Hebrew bullying classification reduce the false-positive rate, vs. classifying the message in isolation — without hurting recall?*

Of the three candidate phrasings offered, Alona picked **option A** (context ↔ false positives) as primary. Options B (precision/recall Pareto vs. context window *k*) and C (which linguistic case-types context repairs) were judged **too complex** and demoted to **optional/stretch sub-questions** (kept, not deleted). The multimodal image axis is demoted from "thesis spine" to a **secondary/optional track** (engineering already built; images do appear in chat).

**Why:** (1) Alona has *not* locked the network architecture, and a capability question lets the architecture stay open — consistent with `plan-structure.decision.md` (architecture deferred to Meeting 4). (2) It matches her actual product vision — "analyze a conversation coming from chat and its context." (3) An empirical capability claim ("context cuts FP by X% in Hebrew") is a stronger, more architecture-robust scientific contribution than an engineering A/B. (4) The context-vs-FP problem is well-grounded in the literature yet **unexplored for Hebrew** = a real gap.

**Data implication (decided in same session):** No Hebrew conversational bullying corpus exists (SinaLab is isolated tweets). Strategy = **synthesize** multi-turn Hebrew conversations for training (precedents: SynBullying 2025, ToxiGen 2022), with deliberate "context-flip" cases, + build a **small real gold set for evaluation** (train-on-synthetic / evaluate-on-real, per Synthetic-vs-Gold 2025). Machine-translation-from-English considered but rejected as a *primary* source (mangles slang/code-switching); allowed only as post-edited augmentation. *Not yet fully locked — revisit when building the dataset (Meeting 6).*

**New flagship anchors added** (`docs/literature_flagship.md`, `docs/references.bib`): Pavlopoulos et al. 2020 (context); Sap et al. 2019 + Davidson et al. 2019 (false positives); SynBullying + ToxiGen + "Synthetic vs. Gold" (synthetic data). SinaLab (Hebrew) and QLoRA (method) retained. **Hebrew availability is honest:** only SinaLab + the Hebrew encoders/LLMs are Hebrew; all context/FP work is English — which is the stated gap.

**Alternatives considered:**
- *Keep RQ3 (multimodal routing) as headline:* requires locking the architecture now, which Alona explicitly is not ready to do; also drifts from her chat-centric product vision.
- *Option B / C as primary:* richer but flagged too complex for a single-student scope.
- *Drop the image axis entirely:* rejected — the engineering exists and images occur in chats; kept as a secondary track.

**Revisit:**
- **Meeting 4 (architecture):** reconcile this reframe with the 7-phase POC plan (Phases 2/4 are image-built) and with the 8-RQ catalog (`research_questions.md` still names RQ3 as spine — now superseded; update there).
- **Meeting 6 (data):** lock the synthetic-vs-translation-vs-real mix.
- If a real Hebrew *conversational* corpus surfaces, prefer it over synthetic for at least the gold set.

> **Note:** this decision *supersedes* the "headline = RQ3 + RQ4" choice recorded in **D-Research-Questions** below (2026-05-24). That section is left intact for the audit trail; read it together with this one.

---

## D-Research-Output-Location — Where these artifacts live

**Question:** "Where should the RQs and the flagship-paper writeup live in the repo?"

**Choice:** **Standalone files at `plan-docs/` root**: `research_questions.md` and `related_work.md`. Both link out to `decisions/research-framing.decision.md` (this file) and inward to relevant meeting detail files under `plan-docs/plan/`.

**Why:** keeps the artifacts independently citeable (one file ≈ one purpose), avoids fragmenting them across the 10 meeting detail files, and respects the existing `decisions/<phase>.decision.md` convention from CLAUDE.md.

**Alternatives considered:**
- *Embed RQs inside `plan/01-research-foundation.md` and `plan/02-literature-and-baseline.md`:* tighter coupling to the meeting structure but harder to cite as a single artifact.
- *Put them in the proposal docx directly:* breaks the principle that the working source-of-truth lives in markdown next to code.

**Revisit:** if the meeting detail files grow to include their own RQ pointers that drift from this file, reconcile.

---

## Linked artifacts

- `../research_questions.md` — the 8 RQs in full.
- `../related_work.md` — the two flagship anchors + supporting-citation guidance.
- `../Plan.md` — master plan; meetings reference these RQs.
- `../plan/02-literature-and-baseline.md` and `../plan/08-gold-set-and-metrics.md` — most affected meeting detail files.
