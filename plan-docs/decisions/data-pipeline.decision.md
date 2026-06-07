# Training Data Pipeline — Decision

Three choices locked on 2026-06-07 when planning the `train / validation / test`
dataset build for the DictaBERT 5-class Hebrew classifier. This activates the
EN→HE translation + LLM synthesis the Meeting-5 §11 stack deferred to Meetings 6–8.
Plan file: `~/.claude/plans/prepare-plan-for-data-wiggly-storm.md`.

## D1 — Generation engine for translation + synthesis: Cloud Gemini

**Question:** Translation (EN→HE) and synthetic example generation both need an LLM.
Cloud Gemini, local-only (NLLB/Ollama), or hybrid?

**Choice:** **Cloud `gemini-2.5-flash`** for both — key already in `server/.env`,
same provider the Context Agent uses (see [[gemini-context-agent]]).

**Why:** Best, most natural Hebrew of the options; fastest wall-clock; a few-dollar
API cost on ~10–15K examples is negligible versus the days of human-QA time saved by
weaker local Hebrew. Reuses an already-configured key and the existing `openai`-SDK
call shape — no new dependency.

**Alternatives considered:**
- *Local-only (NLLB on GPU + Ollama synthesis)* — zero cost, but weaker/less idiomatic
  Hebrew and slower iteration; the quality hit lands exactly on the minority classes
  we most need to get right.
- *Hybrid (translate local, synthesize cloud)* — viable cost saver, but adds a second
  toolchain (NLLB) for marginal benefit at this corpus size.

**Revisit:** If API cost grows past trivial at larger scale, move bulk translation to a
local NLLB pass and keep Gemini for synthesis only.

## D2 — Build strategy: Staged (baseline first), not full-corpus-first

**Question:** Build the entire expanded corpus before the first training run, or train a
real-data baseline first and expand only where weak?

**Choice:** **Staged.** Stage 1 trains on **SinaLab + EDA augmentation only**, measures
macro-F1 + per-class recall against the gate, *then* Stages 2–3 (translation, synthesis)
target only the classes that miss.

**Why:** Matches the architecture's locked fallback chain (try the cheap thing, measure,
escalate). Avoids spending days translating/synthesizing classes that may already clear
0.78. Gives an honest baseline number for the thesis. Lowest risk.

**Alternatives considered:**
- *Full corpus first* — one big training run, but 3–5 days of up-front generation before
  any signal; risks over-investing in classes that didn't need it.

**Revisit:** If the Stage-1 baseline misses the gate on *every* minority class at once,
collapse Stages 2+3 into a single full-expansion pass rather than iterating per-class.

## D3 — Scope this round: single-message classifier only

**Question:** Include multi-turn conversational data (for the FPR / context research
question RQ3/RQ4) in this data round?

**Choice:** **No — single-message 5-class data only**, which is exactly what the DictaBERT
classifier consumes (`{text, label}`).

**Why:** Conversational context is the *Context Agent's* job in the pipeline, not the
classifier's. Mixing multi-turn synthesis into the classifier corpus now would blur the
data contract (§9) and the gate signal. Conversational synthesis is a separate later round
feeding the Context Agent eval + thesis spine.

**Alternatives considered:**
- *Include conversational now* — parallelizes thesis work, but couples two independent
  deliverables and complicates the classifier's clean single-message benchmark.

**Revisit:** After the classifier ships (gate passed), open a dedicated conversational-data
round for the Context Agent / RQ3-RQ4 study.
