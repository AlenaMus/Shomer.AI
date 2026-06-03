# Architecture freeze — Decisions

**Phase:** Meeting 4 (PRD + architecture freeze)
**Decided on:** 2026-05-30 (one day before Meeting 4 on 2026-05-31)
**Decided by:** Alona, in dialogue (Claude surfaced options + literature + cost analysis)
**Predecessor decisions:**
- `plan-structure.decision.md` → `D-Plan-Architecture-Open` — explicitly deferred the architecture choice here.
- `research-framing.decision.md` → `D-Reframe-2026-05-27` — reframed the headline RQ from multimodal image-routing to conversational-context bullying + FP reduction. This decision shapes everything below.

This file captures the four sub-decisions Alona made during Phase 0 deliberation on 2026-05-30, plus the rolled-in engineering defaults.

---

## D-Arch-Variant — Overall architecture shape

**Question:** Which architecture variant best serves the new RQ (context-aware FP reduction in Hebrew) within the project's budget and timeline?

**Choice:** **B — Text + Chat-OCR only** (no offensive-image classifier)

**Why** (in Alona's voice from Phase 0):
> *"I need something concrete I can execute with viable cost and accuracy — not promises for the future. I'm willing to give up complexity in exchange for something better and more accurate on what we do build."*

The chosen architecture:
- Frontline text classifier (DictaBERT-base — see `D-Arch-Model`)
- Chat-screenshot path: Tesseract OCR (heb+eng) extracts text → text flows through the same frontline classifier
- Single Context Agent (see `D-Arch-Form`, `D-Arch-LLM`) for borderline cases
- Push notification to parent with explanation + quote

**Alternatives considered:**
- **A — Multimodal** (text + OCR + offensive-image vision-LLM): rejected — adds significant cost (~$0.008+/interaction if image traffic >5%), introduces vision-LLM evaluation risk (open vision models are weak in Hebrew per available benchmarks), and muddies the RQ experimental signal by conflating context-FP reasoning with image-classification noise.
- **C — Original proposal** (DictaBERT + 3 agents [Triage/Context/Alert] + RAG): rejected — multiplies cost ~1.9–3× over single-agent (~$5,674–$8,910/month vs ~$2,970), Triage and Alert can be replaced by deterministic code with no quality loss, build complexity high for the 4-week window.
- **D — Current POC as-is** (Qwen + single FastAPI, no agents): rejected — no FP-reduction layer to measure, doesn't satisfy the course agent mandate, doesn't advance Pavlopoulos et al. 2020.
- **Hybrid** (B + A as future-stretch): considered, rejected because "promises for the future" don't satisfy the project's need for concrete deliverables within the thesis timeline.

**Defense for "why not A?":** *"The risk isn't worth it — open vision LLMs are weak in Hebrew, which muddies the RQ and blows the budget. The multimodal promise becomes future work if the product proves itself."*

**Revisit:**
- After Meeting 8 (gold-set evaluation): if text+OCR coverage of real harms is >85% of parent-reported incidents → B is locked.
- If parents report many missed image-only harms (raw photos with nudity/violence, not screenshots) → reopen for Phase 9 stretch.

---

## D-Arch-Model — Base model for frontline classifier

**Question:** Which model maximizes Hebrew classification accuracy per dollar for the frontline classifier?

**Choice:** **DictaBERT-base** (`dicta-il/dictabert`, ~110M params, Hebrew-pretrained encoder)

**Why:**
- Best Hebrew accuracy in the lightweight class (estimated F1 0.78–0.82 on SinaLab vs HeBERT baseline 0.74 reported in Hamad et al. 2023).
- Runs on CPU (~50ms inference), free of GPU constraints for the frontline path — RTX 5080 stays available for training and Context-Agent work.
- Fine-tune is easy (no QLoRA needed) — fits the 4-week build window between Meetings 5–8.
- Aligns with the original proposal (mentor familiarity).
- The "no generation capability" limitation is irrelevant in the chosen architecture: the Context Agent (external LLM, see `D-Arch-LLM`) provides reasoning when needed.

**Alternatives:**
- **DictaBERT-large** (~330M): kept as a viable upgrade if base fine-tune at Meeting 5 doesn't cross F1 0.78. Same family, no migration cost.
- **AlephBERT** (~110M): older Hebrew encoder, generally outperformed by DictaBERT on recent Hebrew benchmarks (estimated F1 0.74–0.78).
- **DictaLM 2.0** (generative 7B, Hebrew-pretrained): better ceiling (~0.80–0.85) but overkill for the task — 60× memory, requires GPU, QLoRA needed. Kept as "if maximum Hebrew accuracy is needed for the headline metric" fallback.
- **Qwen2.5-7B** (current POC): multilingual not Hebrew-pretrained, weaker on Hebrew tasks (~0.72–0.78). POC ran on it for convenience; no reason to stay with it when a Hebrew-specific encoder is available.

**Quality-per-cost:** DictaBERT-base gives the highest F1-per-dollar in the lightweight class. Total inference cost is effectively $0 (CPU, no per-token charge), so the optimization reduces to "best Hebrew accuracy at acceptable hardware footprint" — DictaBERT-base wins clearly.

**Revisit:**
- Meeting 5: if DictaBERT-base fine-tune on SinaLab doesn't cross F1 0.78 → upgrade to DictaBERT-large.
- Meeting 8: if gold-set evaluation reveals systematic failures the encoder can't capture (e.g., requires very long context) → consider DictaLM 2.0.

---

## D-Arch-Form — System form (how many agents)

**Question:** How many agents and what shape?

**Choice:** **Single Context Agent** (hybrid: deterministic classifier + 1 LLM-agent) running in the same FastAPI process.

**Why** (in Alona's voice):
> *"Only the Context Agent does the cognitive heavy lifting that matters for the RQ. Triage and Alert add cost without adding accuracy meaningfully — they can be replaced by deterministic code. With one Context Agent I get ~95% of the accuracy benefit at ~50% of the cost."*

Concretely:
- 1 paid LLM call per borderline case (vs 3 calls in the proposal's design)
- ~$2,970/month at SOM scale (5K users) vs ~$5,674–$8,910 for 3 agents — ≥1.9× cheaper
- Satisfies the course "agent mandate": a single agent with tools, memory, and stop-conditions is a qualifying agent per the `software-architect` and `ml-architect` skill conventions
- Directly aligns with the new RQ: the Context Agent IS the FP-reduction mechanism the RQ measures

**Alternatives:**
- **3 agents (Triage / Context / Alert) + RAG:** the original proposal's design. Higher build complexity, marginal accuracy gain over single agent, ~1.9–3× higher recurring LLM cost.
- **0 agents (current POC):** no FP-reduction layer; doesn't satisfy agent mandate; doesn't advance Pavlopoulos et al. 2020 (would just reproduce the naive context-blind baseline).

**Defense for "why not 3 agents?":** *"Triage and Alert can be replaced by deterministic code without quality loss; the ~$2,500–5,900/month savings doesn't justify a marginal accuracy improvement. The agent mandate is satisfied with one well-designed agent."*

**Revisit:**
- Meeting 8: if per-slice evaluation reveals the Context Agent specifically struggles with certain case types (e.g., sarcasm), consider a second specialist agent.

---

## D-Arch-LLM — LLM behind the Context Agent

**Question:** Which paid LLM runs the Context Agent reasoning?

**Choice:** **GPT-4o-mini as primary, Claude Haiku 4.5 as documented fallback** (test-cheap-first strategy)

**Why** (in Alona's voice):
> *"Quality-per-cost wins — start with cheap and upgrade based on data from Meeting 8. If GPT-4o-mini meets accuracy targets, we keep it (saves $2,500/month at SOM scale). If not, we move to Haiku and still stay under budget."*

**Concrete numbers** (from `docs/business_plan/business_plan.md` §6):

| Model | Cost/1M | Per call (×2 multiplier) | SOM monthly (675K calls) | Thesis total (~10K calls) |
|---|---|---|---|---|
| **GPT-4o-mini (primary)** | $0.15 / $0.60 | $0.00057 | ~$385 | ~$6 |
| **Haiku 4.5 (fallback)** | $1 / $5 | $0.0044 | ~$2,970 | ~$44 |

Both well below the $0.005/interaction budget cap (proposal §11.3). Multi-provider strategy (OpenAI for agent + DictaBERT/Tesseract local for frontline) provides operational redundancy.

**Alternatives:**
- **Haiku 4.5 as primary:** stronger nuanced reasoning, safety-aligned to child-safety domain. Higher quality, ~7× cost. Demoted to fallback because the quality-per-dollar analysis (Haiku ~19,318 quality-units/$ vs mini ~131,579) favors mini under test-then-measure strategy.
- **Gemini 2.5 Flash:** 1M token context window (advantage for long chat history); middling cost (~$0.0019/call); less benchmarked publicly on Hebrew reasoning specifically.
- **Local LLM** (DictaLM 2.0 via Ollama for the Context Agent): keeps everything fully on-device, but introduces GPU contention with the frontline classifier and complicates fine-tuning. Saved as "if cost ever matters more than quality, and Haiku is still too expensive" deep fallback.

**Revisit:**
- Meeting 8 (gold-set evaluation): measure GPT-4o-mini's F1 + Δ-FPR on the gold set. If below the target → switch primary to Haiku; mini becomes fallback.
- If quality threshold is crossed in production (user complaints about miss rate) → immediate upgrade to Haiku without further measurement.

---

## D-Arch-OCR — OCR engine for chat screenshots

**Question:** Which OCR engine extracts Hebrew text from chat screenshots?

**Choice:** **Tesseract** (with `heb` + `eng` language packs)

**Why:**
- Free, runs locally — preserves the privacy promise (images don't leave the local server)
- Adequate quality on clean text (~80–90%); known to degrade on noisy chat screenshots, but acceptable for proof-of-concept
- Supports Hebrew + English mixed text (code-switching is common in Israeli teen chat)
- Easy to swap for EasyOCR or MLKit on-device if Meeting-8 evaluation reveals OCR is the bottleneck — no architecture change needed

**Alternatives:**
- **EasyOCR:** ~5–7% better than Tesseract on noisy images, heavier dependency. Documented as the first upgrade candidate.
- **MLKit on-device** (Android): runs OCR on the child's phone before sending to server — best privacy + zero server load. Saved as a future-work upgrade (would require Android client refactoring).
- **Google Cloud Vision / Azure AI Vision:** highest quality (~95%+) but cloud-based — breaks the local-first privacy commitment. Rejected on principle.

**Revisit:**
- Meeting 8: measure OCR error rate separately from classifier F1. If OCR is the F1 bottleneck → upgrade to EasyOCR (drop-in) or plan MLKit migration.

---

## Architecture defaults (rolled-in without separate sub-decisions)

These are sensible engineering defaults that ship with the chosen architecture. They are not Alona-debated choices and can be revisited later, but they don't need Phase-0-level deliberation now.

- **Context Agent location:** runs in the same FastAPI process as the frontline classifier. Async call to the GPT-4o-mini API.
  *Rationale:* simplicity at this scale; no microservice overhead needed.
- **Privacy boundary for the paid LLM call:** current message + up to 5 prior turns, no PII (no user IDs, no contact info).
  *Rationale:* minimal context needed for FP-reduction reasoning per Pavlopoulos 2020; minimizes exposure of children's content to external APIs.
- **Logging:** full reasoning trace + decision logged for every Context Agent invocation.
  *Rationale:* required for per-slice evaluation at Meeting 8 (Sap et al. 2019 mandates measuring FPR per sub-population).
- **Initial Context Agent tools:** `read_conversation_history`, `lookup_slang`, `check_age_appropriateness`.
  *Rationale:* minimum viable set to demonstrate context-aware reasoning; expand based on Meeting 7 needs.
- **API fallback** (Context Agent LLM unreachable): return frontline classification + flag the case as "needs human review" — do **not** block the parent alert.
  *Rationale:* graceful degradation; never silently lose an alert in a child-safety system.
- **Confidence threshold for Context Agent escalation:** TBD — default 0.3–0.7 borderline zone, to be empirically tuned at Meeting 8 based on the gold-set FP/FN curve.

---

## Linked artifacts

- **This decision:** `plan-docs/decisions/architecture.decision.md`
- **Predecessor decisions:** `plan-structure.decision.md` (deferred here), `research-framing.decision.md` (reframed the RQ which shaped this)
- **Follow-up decisions to be written next:**
  - `reframe-reconciliation.decision.md` — one-page note on how the chosen architecture serves the reframed RQ and what happens to POC Phases 2/4
  - `data-strategy.decision.md` (Meeting 6) — final mix of synthetic + real + translated training data
- **Diagrams documenting the chosen architecture:** `docs/architecture_diagrams.md`
- **PRD instantiating this architecture:** `docs/PRD.md`
- **Open product/UX questions deferred to follow-up sessions:** `docs/open_questions.md` (7 items)

---

## Open items remaining after this decision (NOT blocking PRD or Meeting 4)

The following surfaced during Phase 0.5 (product-questions phase) but were intentionally deferred for focus on Meeting 4 deliverables. Each will be addressed in a follow-up session before Meeting 5 (build phase start):

1. **MoSCoW prioritization** of features (15 candidate features need M/S/C/W tagging)
2. **Confidence threshold tuning** (numerical thresholds for Context Agent escalation)
3. **Push notification format** (depth of explanation, quote inclusion, dashboard linking)
4. **Conversation history storage** (retention period, deletion semantics, GDPR posture)
5. **Offline mode behavior** (which features degrade, which fail outright)
6. **Single-child vs family-account model** (data-model implications)
7. **Quiet hours / DND controls** (parent-side scheduling)

All seven are documented in `docs/open_questions.md` with proposed defaults so the build can start with reasonable assumptions, and each default is flagged for explicit review before lock-in.
