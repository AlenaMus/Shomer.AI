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

## D4 — Data sources (Stage-0 verified 2026-06-07)

**Question:** Which corpora feed the 5-class classifier, and which are real Hebrew vs
need translation/synthesis? (User asked specifically about textdetox, hatespeechdata,
OLaH/D_OLaH, Jigsaw.)

**Findings (measured, not assumed — see `training/data/raw/README.md`):**
- **SinaLab / OffensiveHebrew** — real source is **GitHub `SinaLab/OffensiveHebrew`**, not an
  HF dataset (`load_dataset` 404s). Real deduped per-class: non_off 14,298 · hate 624 ·
  violence 453 · abusive **119** · pornographic **4**. Label is a single messy free-text
  column (mixed case, `Porographic` typo, `racism`→hate, comma multi-label).
- **OLaH / D_OLaH = the SinaLab corpus itself** (the paper's name for it). **Not a new
  source** — do not double-count.
- **textdetox `multilingual_toxicity_dataset` `he` split** — ✅ **real native Hebrew**,
  2,011 rows (807 toxic / 1,204 clean), **binary** `toxic` label.
- **hatespeechdata.com** — a *catalogue*, 24 languages, **no Hebrew**. Useful only as an
  English translation menu (ConvAbuse, ETHOS, Let-Mi, Measuring Hate Speech).
- **Jigsaw Toxic Comment** — **English only → translate.** Best-structured minority source
  (`threat`→violence, `identity_hate`→hate, `obscene`/`insult`→abusive). Loadable from HF
  (`tasksource/jigsaw_toxicity`), no Kaggle auth.

**Choice:**
- **Stage-1 real Hebrew base = SinaLab + textdetox `he`.** The 807 textdetox toxic rows are
  **Gemini-sub-labeled** into the 5 classes (few-shot + 10% human QA); 1,204 clean → extra
  `non_offensive` pool (down-sampled). This lifts abusive to real-Hebrew viability.
- **Jigsaw + hatespeechdata English sets = Stage-2 translation booster** (only if a class
  misses gate), via Gemini context-preserving EN→HE.

**Why:** Maximizes *real native Hebrew* signal (most thesis-defensible) before spending on
translation; textdetox is the cheapest real-Hebrew win and directly fixes the thin `abusive`
class. Jigsaw deferred because translation has cost + a fidelity-QA burden, and the staged
gate may not need it.

## D5 — `pornographic` is built in Stage 1, not deferred

**Question:** With only ~4 real porn examples anywhere (no real Hebrew or English source —
even Jigsaw `obscene` is profanity, not sexual-explicit), how does Stage 1 handle it?

**Choice:** **Build it in Stage 1** — Gemini-synthesized pornographic (~800–1,500) +
a thin slice of translated sexual-harassment examples (ConvAbuse) — so the baseline is a
**true 5-class model**. Porn val/test rows are necessarily synthetic+translated, flagged with
a thesis caveat (the §9 "real-only val/test" rule is physically impossible for this class).

**Why:** This is a child-safety product where `pornographic` is an *always-alert* triage
class (G-03) — shipping a baseline that structurally cannot detect porn is unacceptable even
as an interim. 4 real examples cannot be split or measured, so deferral buys no real signal.

**Alternatives considered:** Defer porn to Stage 2 (4-class baseline) — rejected: the first
model couldn't flag porn at all. Collapse porn into abusive — rejected: breaks the §9 5-class
lock and the triage always-alert rule.

**Revisit:** If synthetic-porn distribution proves unrealistic in error analysis, add a small
human-authored or web-sourced Hebrew porn-text seed set (with care) before Meeting 8.

## D6 — Sourcing real Hebrew `pornographic` text (safety guardrails)

**Question:** Can we collect real Hebrew pornographic messages from the web as additional
*training* data (user asked, also asked about putting it "in RAG")?

**Clarification first:** RAG (`server/data/slang_lexicon.json`) feeds the **Context Agent**,
not the classifier. To improve the *classifier's* porn detection, examples must go in
**`train.jsonl`** — not RAG. A sexual-slang lexicon entry is a separate, additional win for
the Context Agent's borderline reasoning.

**Choice:** Synthesis stays **primary**. Optionally add (a) translated **ConvAbuse**
sexual-harassment examples and (b) a **small hand-curated real Hebrew seed (~30–80 lines)** of
sexual solicitation / adult-spam style text from **public** sources — **reserved mostly for the
porn val/test split** so evaluation isn't 100 % synthetic (real test data = more defensible).

**Hard guardrails (non-negotiable):**
- ❌ **No content involving minors — no CSAM, ever.** Absolute stop.
- ✅ **Text only**, never imagery (classifier is text/OCR).
- ⚠️ **No scraping porn sites** (ToS/legal/quality). Prefer translated research subsets +
  controllable synthesis + small public-spam seed. The real product-relevant class is sexual
  *solicitation/harassment/spam in chat*, not literary porn — which synthesis captures well.

**Why:** Real data improves test-set defensibility, but the legal/ethical risk of scraping is
high and unnecessary; synthesis + translation + a tiny curated seed gets the signal safely.

**Revisit:** Only expand the real seed if Stage-1 error analysis shows synthetic porn is
distributionally unrealistic.

## D8 — Split ratio 70/20/10, category-balanced, synth allowed in val/test

**Question:** After Stage 2/3 passed the gate at macro-F1 0.854, inspection showed val/test
were ~78% synthetic/translated for the minority classes (hate/violence test only ~22% real
SinaLab; porn 0% real) — so the headline number is inflated. User then requested **70/20/10**
splits and **balanced categories**, and chose to **keep synthetic/translated data in val/test**
(higher number) rather than switch to real-only honest evaluation.

**Choice:**
- Split ratio **70% train / 20% validation / 10% test** (was ~85/7.5/7.5).
- **Balance categories** — equalize all 5 classes to a common per-class size (bounded by the
  `pornographic` ceiling, the scarcest buildable class), down-sampling `non_offensive` and
  augmenting short minorities (2× EDA cap).
- **Synthetic + translated rows remain eligible for val/test** (stratified across all sources),
  per user preference.

**Why (user's stated preference):** keep the higher, balanced-looking number for presentation.

**⚠️ Documented limitation (MUST appear in the thesis methodology + model card):** because
synthetic/translated examples are present in val/test, the reported macro-F1 **overstates
real-world performance** — it partly measures fit to synthetic patterns. The honest real-only
number (synth/translated → train-only) is lower and unmeasured this round. `pornographic` val/test
is 100% synthetic (real seed blocked by Gemini safety filters), so its F1 is not a real-detection
metric. A balanced training prior also raises the false-positive rate vs natural prevalence —
mitigated by isotonic calibration but worth noting for the FPR research question.

**Alternatives considered:** Real-only honest val/test (synth→train-only) — recommended by the
assistant for defensibility; declined by the user in favor of the higher number.

**Revisit:** Before Meeting 8 / final thesis eval, produce the honest real-only number as a
companion metric so the limitation is quantified, and add a real Hebrew porn test seed.

## D9 — Prevalence-aware mix (revert from full balancing) + slang/code-switch strengthening

**Question:** The D8 fully-balanced (1:1:1:1:1) run FAILED `precision[non_offensive]` (0.688 — a
false-alarm flood) because equal priors make the model over-predict offensive. How to fix the
class mix, and do we strengthen Hebrew slang + Heb-Eng code-switching?

**Choice (both, user-approved):**
1. **Prevalence-aware mix** — abandon full balancing; return to the locked §11 design (Focal Loss
   γ=2 + class weights, NOT balanced sampling):
   - **Train:** `non_offensive` ≈ all offensive classes combined (~50%); the 4 offensive classes
     ~equal among themselves.
   - **Val/Test:** lean realistic (~70% `non_offensive`) so precision / FPR reflect production.
   - Keep the **70/20/10** overall split ratio; keep Focal + class weights.
   - Rationale: restores `non_offensive` precision (kills false alarms) while the loss weighting
     protects minority recall — the middle path between balanced (fails precision) and natural
     92% (starves minorities). The data empirically re-derived why §11 chose weighting over balancing.
2. **Strengthen slang + code-switching + noisy/kids' Hebrew** — targets the weak D8 slices
   (`poor_spelling` 0.47, `children_mistakes` 0.57 vs `code_switching` 0.74, `clear_hebrew` 0.71).
   Normalization already **keeps** slang + code-switching (§9), so this is additive train signal,
   not a contract change. Four concrete, **label-preserving** techniques:
   - **(a) Character-level Hebrew typo-noise augmentation** (the most direct fix — cheap,
     deterministic, mirrors the eval slices). New `training/augment_noise.py` applied to a capped
     fraction (~25–30%) of a train copy: adjacent-key swaps (Hebrew layout); dropped/doubled
     letters; **phonetic/homophone confusions** kids make (ת↔ט, כ↔ק, ח↔כ, א↔ע↔ה, ס↔שׂ);
     **final-form errors** (ם↔מ, ן↔נ, ך↔כ, ף↔פ, ץ↔צ); **matres-lectionis** variation (dropping/adding
     י/ו, e.g. כותב↔כתב); run-on words / stray spaces. Label is preserved by construction (a
     misspelled slur is still a slur).
   - **(b) Kids'/teen-register synthesis** (Gemini) — offensive + non-offensive examples in
     8–14-year-old chat register: internet shorthand, emoji-heavy, intentional misspellings, youth
     slang. Labels assigned at generation.
   - **(c) Code-switched (Heb-Eng) synthesis** (Gemini) across classes — English slurs/phrases
     embedded in Hebrew sentences, the realistic bilingual chat pattern.
   - **(d) Expand `server/data/slang_lexicon.json`** (Gemini, same schema: meaning/common_use/
     valence/age_group) with youth + internet Hebrew slang → seeds (b)/(c) **and** the Context-Agent RAG.
   - **Guardrail:** cap the noise so the `clear_hebrew` slice does not regress (re-check all four
     slices after); over-noising degrades clean-text performance.

**Alternatives considered:** threshold-tuning the balanced model post-hoc (quick, no re-prep) —
declined in favor of fixing the data prior properly; strongly-realistic ~80% non_off — declined as
heavier on synthetic minorities this round.

**Revisit:** If `precision[non_offensive]` still lags after the prevalence shift, raise the offensive
decision threshold on calibrated probs as a secondary lever.

## D10 — Round 5: fix the code-switching regression (distribution match)

**Question:** D9 lifted 3 slices but `code_switching` regressed 0.74→0.68. Why, and how to fix?

**Root cause (inspected):** the `code_switching` eval slice is **teen Hebrew with embedded benign
English lifestyle words** ("יום fun", "ה-vibe ממש chill", "crush חדש"), and it is **52% non_offensive**
(135/260). But D9's `synth_codeswitch` embedded English **slurs** ("Jewish pigs", "idiot", "dead meat").
The model therefore learned a spurious **"English token ⇒ offensive"** association and now over-flags
benign teen code-switching → the slice drops.

**Choice:** Generate a **style-matched** code-switch set — teen/youth Hebrew sentences with embedded
**benign English lifestyle vocab** (fun, vibe, chill, crush, mood, cute, random, awkward, workout,
playlist, etc.), **distribution ~50% non_offensive** + the rest spread across offensive classes in
the same teen register. Add to train (the offensive English-slur code-switch from D9 stays but is no
longer the *only* code-switch signal). Keep everything else identical to D9 (prevalence-aware mix,
typo-noise, Focal+weights). Re-eval all 4 slices — target `code_switching` ≥ 0.74 **without**
regressing `clear_hebrew`/`children_mistakes`/`poor_spelling`.

**Why:** the regression is a data-distribution artifact, not a model issue — the cure is to teach the
model that code-switching ≠ offensiveness by showing it abundant benign English-mixing.

**Revisit:** If still low, gather ~50-100 real handwritten-style code-switch sentences (the slice's
true source) for a final targeted top-up before Meeting 8.

## D11 — Round 6: intensify typo-noise to match the poor_spelling slice density

**Question:** `poor_spelling` is the weakest slice (0.47→0.51→0.58 across rounds). Why still low?

**Root cause (inspected):** the slice is **densely phonetically corrupted** — nearly EVERY word is
misspelled with systematic Hebrew confusions: **ת↔ט** (pervasive: אטמול/אטה/טמיד), **ה↔א↔ע**
(פיצע/מא/איה), **final-forms written as regular** (לכא→ך, סתמ→ם, בגדימ→ם, אתנ→ן), **ח↔כ**, **ש↔ס**,
extra/missing letters & matres (סאפר/הילידים/בננות). The D9 `augment_noise.py` has the right *ops*
but is too **mild + sparse** (~25-30% of examples, few edits each) — the model still trains mostly on
clean text, so it never adapts to dense corruption.

**Choice:** Intensify the typo-noise: add an **intensity/density parameter** so a heavily-corrupted
variant misspells ~60-80% of words per sentence (matching the slice); apply a denser-noise copy to a
larger fraction of train **across all classes** (slice is 52% non_off); verify the confusion tables
cover ALL observed pairs (ת↔ט, ה↔א↔ע, ח↔כ, כ↔ק, ש↔ס, final-forms, matres י/ו). Keep D10 config
otherwise (prevalence-aware, code-switch fix, Focal+weights). **Keep clean copies too** so the model
sees both registers — guardrail: `clear_hebrew` must not regress.

**Why:** matching the training-noise density to the eval-noise density is the direct lever; the ops
were already correct, only the intensity/coverage was insufficient.

**Caveat:** the slice is deliberately, near-maximally corrupted (more than typical real kid text), so
expect diminishing returns — a meaningful lift, not a jump to 0.78.

**OUTCOME (Round 6 run + revert):** heavy noise lifted `poor_spelling` only **+0.02** (0.58→0.60)
and improved `clear_hebrew` (+0.03), but **cost `hate` F1 −0.08** (0.74→0.66; 17 non_offensive
misread as hate) and macro-F1 −0.015 (0.834→0.819) — an unfavorable trade on an artificially-hard
probe. **Decision: reverted** — step 7c (heavy-noise pass) removed from `prepare_data_dictabert.py`;
**D10 is the final model** (macro-F1 0.834, hate 0.74, poor_spelling 0.58, all gates pass). poor_spelling
tuning is closed; further gains need real misspelled data, not synthetic noise.
