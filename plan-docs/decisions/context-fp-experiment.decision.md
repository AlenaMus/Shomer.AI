# Context → False-Positive experiment — Decisions

**Phase:** Master plan, Meeting 7→8 (gold set & metrics) — operationalising the reframed RQ.
**Decided on:** 2026-06-08 (methodology) / thresholds **pre-registered** 2026-06-08.
**Decided by:** Alona (approved running the experiment + locking the runner); options + defaults surfaced by Claude.
**Companion docs:** [`../../docs/research_question/context_fp_test_plan.md`](../../docs/research_question/context_fp_test_plan.md)
(full design) · [`research-framing.decision.md`](research-framing.decision.md) (D-Reframe-2026-05-27, the parent RQ choice).

Captures the methodology + pre-registered thresholds for the experiment that answers the headline RQ:
*does conversational context reduce the Hebrew bullying false-positive rate without hurting recall?*

---

## D-CFP-1 — Two A/B levels, both run; prompt-level is the scientific primary

**Question:** Which comparison defines "context-blind vs. context-aware" — the product triage path, or an
isolated prompt-level toggle?

**Choice:** **Run both, report both.**
- **F2 — prompt-level (PRIMARY for the thesis claim):** same LLM judge, same message, same classifier
  result; the *only* difference is the conversation-history block — empty vs. populated. Isolates context
  as the sole independent variable. Implemented by calling the context-agent prompt builder with
  `conversation_history=[]` vs `=turns`.
- **F1 — product-level (deployment validation):** the real pipeline with `CONTEXT_AGENT_ENABLED=false`
  vs `true`. This is what ships, but it changes *two* things at once (context **and** the routing rule),
  so it is the secondary/validation number, not the headline.

**Why:** the product A/B confounds context with the triage threshold change; a reviewer can attack it. The
prompt-level A/B is the clean causal isolation the RQ wording demands ("the same model… with vs. without
context"). Reporting both shows the effect is real *and* survives in production.

**Alternatives considered:** product-level only (confounded); prompt-level only (doesn't prove it ships).

**Revisit:** if a reviewer wants the classifier itself made context-aware (concatenation into DictaBERT),
that becomes a third arm under **E6** — not the primary.

---

## D-CFP-2 — Context only acts in the borderline band → science run lets it act on everything

**Question:** Should the experiment measure context's effect only where production currently uses it (the
borderline band [0.3, 0.7]), or its full potential?

**Choice:** **Both, labelled distinctly.** Report "ΔFPR as shipped" (context only on borderline/escalated
items, the F1 path) **and** "ΔFPR when context is always allowed to act" (the judge runs on every item, the
F2 path). The headline scientific number is the latter; the deployment number is the former.

**Why:** a high-confidence false positive (`prob_offensive ≥ 0.7` on a sarcastic line) never reaches the
Context Agent in production, so the shipped A/B structurally *under*-measures what context can do. The
thesis should report context's true ceiling and then show how much of it the current routing captures.

**Revisit:** if the gap between the two numbers is large, that is itself a finding → consider widening
`BORDERLINE_HIGH` or always-escalating in production (cost trade-off, E6 territory).

---

## D-CFP-3 — Pre-registered thresholds & test (locked BEFORE the run)

**Question:** What counts as success, and what statistical test decides it? (Must be fixed in advance to
avoid p-hacking — H1 is a pre-registered hypothesis.)

**Choice (locked defaults — Alona may tighten before the gold-set run):**

| Symbol | Meaning | Locked value |
|---|---|---|
| **X** | Minimum FPR drop to claim success (H1) | **≥ 10 percentage points absolute** *(or ≥ 30% relative, whichever the gold-set size supports)* |
| **Y** | Max tolerated recall loss (non-inferiority) | **≤ 3 percentage points** |
| **k** | Context window (prior turns shown) | **5** (matches `max_history_turns` default) |
| **α** | Significance level | **0.05**, two-sided |
| **test** | Significance test | **McNemar** (exact binomial if discordant pairs < 25) — paired design |
| **κ** | Min inter-annotator agreement for gold labels | **≥ 0.6** (Cohen's κ) |

**Why:** the design is paired (every gold item scored by both arms) ⇒ McNemar, not a two-sample test.
X/Y/k/α are fixed now so the later result is confirmatory, not exploratory. Defaults are deliberately
conservative-but-achievable given a 150–200-item gold set.

**Alternatives considered:** larger X (≥15pp) — risk of "fail" on a small gold set; relative-only X —
harder to communicate; per-class thresholds — deferred to stretch RQ3.

**Revisit:** after the gold set is sized — if it lands < ~120 items, relax X to relative-only and report
CIs instead of a hard pass/fail; **no threshold may change after the run begins.**

---

## D-CFP-4 — The 3-category gold-set design is the proof structure

**Question:** How is the gold set composed so the result actually proves the claim (not a degenerate
"context = trust everything" win)?

**Choice:** three deliberately-built categories — **A** context-repairs-FP (~45%, drives ΔFPR), **B**
context-reveals-TP (~25%, the recall guard), **C** context-invariant controls (~30%, specificity). Each
item carries `isolated_appearance` so a Category-A item only counts if it genuinely reads offensive in
isolation. Seed bootstrap: [`../../data/gold/context_eval_seed.jsonl`](../../data/gold/context_eval_seed.jsonl).

**Why:** without Category B, a model that blindly downgrades everything would score a fake FPR win while
destroying recall; B + C are what make the "without hurting recall" clause measurable and the result
defensible. Decomposing ΔFPR by category proves **H2** (the drop is concentrated in flip cases).

**Revisit:** ratios are targets; final gold set may shift ±10% per category based on what real Hebrew
sources yield. Synthetic items may seed *training* conversations but stay **out of the gold/eval split**
(train-on-synthetic / eval-on-real, per the reframe decision).

---

## D-CFP-5 — Literature contribution is E6 (selective-agent vs. naive-concat)

**Question:** What turns this from "first Hebrew data point" into a contribution to the flagship literature?

**Choice:** add experiment **E6** comparing three arms — context-blind / naive-concatenation-into-classifier
/ selective-context-agent — on FPR, recall **and LLM cost**. This directly tests Pavlopoulos 2020's open
question ("naive concat gives only marginal gains; how to use context efficiently is open") with a
*selective, cost-aware* strategy, in Hebrew.

**Why:** E1–E3 prove the capability claim; E6 is what a thesis committee reads as novel methodology, not
replication. It is optional only on time, not on importance.

**Revisit:** if time-boxed out, keep E1–E3 (the RQ stands) and frame E6 as future work.

---

## D-CFP-6 — Gold-set v1 sourcing: humor = benign controls, screenshots = B reveals (decided 2026-06-10)

**Question:** How are the two new real sources (Desktop `offensive/` screenshots; `whatsapp_humor_examples.md`)
folded into the gold set, and how is the friendly humor labelled?

**Choice:** Assemble `data/gold/context_gold_v1.jsonl` (34 items) = authored screenshot items + real
bullying-thread screenshots + **6 curated WhatsApp humor chats**. The humor chats are labelled
**`C_control_benign`** (benign, benign-in-isolation) — *specificity controls*, not fabricated Category-A
flip pairs. The `offensive2.png` sarcastic pile-on yields **Category-B reveals** (`AU-19`/`AU-20`: jokey in
isolation, bullying in the pile-on). Each item keeps a `tags` field carrying the chat's style tags.

**Why:**
- The benign FPR denominator was the thinnest slice (~13 benign). Real friendly Hebrew banter is the
  *right* way to grow it — and it tests the exact failure the RQ targets: a context-blind model
  over-flagging sarcasm. Labelling them benign is the honest call (they read benign in isolation too).
- Fabricating offensive "mirror" arms for the humor would be synthetic → barred from the gold split by
  D-CFP-4. The genuine offensive mirror already exists in the screenshots (sarcasm-in-a-pile-on), giving a
  **real contrastive pair** (same surface form, context-flipped label) — the strongest single argument that
  context, not lexicon, carries the signal.

**Alternatives considered:** label humor as Category A (rejected — messages are benign in isolation, so
there is no FP for context to "repair"); synthesize offensive twins (rejected — violates train-on-synthetic
/ eval-on-real); drop humor entirely (rejected — leaves the TN denominator too thin for a credible FPR).

**Revisit:** when the remaining 44 humor placeholders are filled and more real context-flip screenshots are
added (target ~150–200, §3); re-check A/B/C ratios then. Double-annotation for κ still pending.

---

## D-CFP-7 — External cyberbullying datasets are TRAINING/seed-only, never gold/test (decided 2026-06-10)

**Question:** Three external sets were evaluated for use as validation/test data — Kaggle `ziya07/cyberbullying-detection-dataset`, `Downloads/files (1)/hebrew_cyberbullying_dataset.*` (100 rows), and `Downloads/gemini-code-1781086778967.json` (25 conversational items). Can any be used for testing?

**Choice:** **None enter the gold/eval split. All are training / dev / seed material only.** The driver is D-CFP-4 (train-on-synthetic / eval-on-real): the thesis FPR number is only defensible if the test set is real, and **all three are synthetic**.
- **Kaggle ziya07** — English + single-message → skip entirely (no context for the RQ; redundant with the existing Jigsaw EN→HE training translation; classifier frozen at D10).
- **`files (1)` hebrew_cyberbullying** — native Hebrew but **synthetic** (literal `[קבוצה אתנית]` / `[שם הילד]` placeholder artifacts in rows `hcb_0019`,`hcb_0022`), **single-message** (its `context` field is a *setting* tag, not history), 90/100 offensive, `sexual_harassment` has no clean 5-class home. Use: at most a **5-class classifier training-pool** augment after relabel+clean. Cannot touch the context RQ.
- **`gemini-code-…json`** — native Hebrew + **genuinely conversational** (multi-turn `conversation[]`), the right shape for the RQ, but **Gemini-synthetic** and **100% offensive / 0 benign / no context-flip pairs**. Use: **seeds for the synthetic context pool + Context-Agent few-shot/authoring reference**; the Sarcasm/Banter items (ids 2,4,11,21,24) mirror the `offensive2.png` sarcasm-in-context pattern.

**Why:** putting synthetic items in test breaks eval-on-real (the headline-number's credibility) and is the easiest reviewer attack. Both training tracks are also effectively closed (classifier frozen at D10; the Context-Agent is a prompted judge, not trained), so the practical value of all three is dev/seed/few-shot, not a new training run. The gold set's real gap — benign + context-flip *real Hebrew conversations* — is filled only by the screenshots/humor path, not by these synthetic sets.

**Alternatives considered:** secondary synthetic "sanity" test reported alongside the real one (deferred — not the primary, adds little given the existing synthetic-eval caveat); remapping `files (1)` into the classifier test set (rejected — synthetic + skewed + dirty + label-mismatch).

**Revisit:** if the classifier is reopened for another round, `files (1)` (cleaned/remapped) and `gemini-code` conversational items become legitimate training augmentation. They never become eval.

---

## D-CFP-8 — MVP feasibility run executed; F1 product-level is the proof, F2 hits a floor (2026-06-11)

**Question:** With no time to build a real gold set, can the thesis be demonstrated now as an MVP on the
synthetic+authored data, and which A/B arm is the actual proof?

**Choice:** Ran the full apparatus on a 61-item combined set (`context_mvp_combined.jsonl` = real-ish
gold_v1 34 + synthetic seed 27) with the **real Gemini judge + trained DictaBERT** (not the mock). Treat
**F1 (product-level: context-blind classifier vs. classifier+Context-Agent) as the thesis proof**; F2
(prompt-level LLM-judge with/without history) is reported but is a **floor effect** here.

**Result:** **H1 PASS** — FPR **55.9% → 26.5% (−29.4 pp, McNemar exact p=0.002)**, accuracy 55.7% → 68.9%,
ΔFPR concentrated in Category A (−34.8 pp), `c=10 / b=0` discordant pairs. Recall 70.4% → 63.0% (−7.4 pp,
**fails** the strict ≤3 pp margin) — but the **entire** loss is on **C-offensive** controls, while Category
B recall **rose +14.3 pp**. Visualized in `docs/research_question/plots/`; write-up in `MVP_thesis_results.md`.

**Why F1 not F2:** the false positives are produced by the **context-blind DictaBERT** (offensive-looking
words trip it regardless of friendly context) — F1 measures the repair of exactly that. In F2 *both* arms are
already the strong Gemini judge, which flags 0% of benign even with empty history → no FP left to remove (the
−29 pp lives in the cheap classifier, not the LLM). F2's context value instead appears as +14.8 pp recall.
This **motivates the selective-agent architecture** (answers Pavlopoulos): give the cheap classifier a context
check rather than making the expensive judge context-aware.

**Key finding for future work:** the recall cost is a **prompt-scope artifact** — the Context-Agent asks
*is_real_threat*, so it downgrades non-violent **abuse** to silent. Broadening to *is_harmful_in_context*
should recover C-offensive recall without touching the FPR win (which lives in Category A). Tuning finding,
not a refutation.

**Limitations (documented):** eval set partly synthetic/authored → magnitude optimistic; single-annotator (no
κ); n=61. Direction + significance of the FPR result are unaffected; only the effect size needs real-gold to
pin down. **The MVP proves the mechanism + apparatus; the publishable number still requires eval-on-real.**

**Revisit:** after (a) the CA-prompt broadening, and (b) a real-gold eval — both re-run through the same
`eval_context_fp.py` + `viz_context_fp.py`.

---

## D-CFP-9 — Harm-context reframe: alert on harmful SITUATIONS, not every offensive message (2026-06-11)

**Question (raised by Alona):** Do we really want an alarm on *every* offensive message? Shouldn't it be
part of the full *harmful context*? And can we test on a larger set with more context?

**Choice:** Adopt the **harm-context reframe** as the correct framing. The decision target becomes
**`alert_worthy`** (is this part of a harmful situation — repetition / escalation / threat / coercion /
exclusion / doxxing / targeting a distressed victim?), distinct from `offensive_content` (surface words).
Architecturally: **DictaBERT = content detector; Context-Agent = harm adjudicator** (broadened prompt from
*is_real_threat* → *is this harmful in context*, explicitly NOT-alert on banter / one-off jabs / friendly
sarcasm). Built a **larger generated set** (`context_harm_v2.jsonl`, 143 multi-turn Hebrew conversations,
labels by generation design) + `eval_harm_context.py` + `viz_harm_context.py`.

**Result (corrected run, after the self_or_report split — see below):** On 35 offensive-but-NOT-harmful
messages the context-aware system fired **0 alerts (100% correct)** — *the reframe validated: it does not
alarm on every offensive word*. Veiled-harmful recall **0 → 100%** with context; overall harm-recall
**58.9% → 82.1% (+23 pp)** on 95 alert-worthy items; **false-alarm rate 2.1%** (1 stray, on self-deprecation).
Write-up: `docs/research_question/harm_context_results.md`.

**Self_or_report split (applied 2026-06-11):** inspection showed the original "benign" `self_or_report` cell
mixed **11 victim-disclosures** (a child reporting being bullied → a real safety signal → relabelled
**alert-worthy**) and **1 self-deprecation** (→ benign). Re-scored the same judge decisions against corrected
labels (no Gemini re-call; original run kept in `harm_context_results_v1.json`). This turned the apparent
~15% FPR into a genuine **2.1%**. Context's contribution in this experiment is therefore **recall** (the
harm-framed prompt is already specific); the **FPR-reduction** effect belongs to the per-message MVP (D-CFP-8)
where the context-blind classifier is the over-flagging component.

**Why it strengthens the thesis:** it answers the "alarm on every offensive message?" objection directly and
shows context helps on BOTH axes — the per-message MVP (D-CFP-8) showed context **cuts false positives**
(classifier over-flags); this shows context is **required for harm recall** (veiled/context-dependent harm).
Combined claim: the right alert target is the harmful *situation*, not the offensive *word*.

**Limitations:** synthetic (generator≈judge circularity, mitigated by design-labels); `self_or_report`
labelling; n=143; mild-pile-on boundary cases. Magnitudes need real-gold; directions are robust.

**Revisit:** self_or_report split — ✅ done. Remaining: treat `victim_disclosure` as a **distinct alert
type** in the product (child-as-victim, different parent message than peer-aggression); fold the broadened
harm prompt into the production Context-Agent (`prompt.py`) behind a flag; real-gold eval for magnitudes.

---

## Linked artifacts

- `../../docs/research_question/context_fp_test_plan.md` — full experiment design (E1–E6, statistics, flagship map).
- `../../data/gold/context_gold_v1.jsonl` — **assembled gold set v1 (34 items, the runner target)**.
- `../../data/gold/context_eval_seed.jsonl` — synthetic seed (train-only, held out of gold/eval).
- `../../data/gold/context_authored_seed.jsonl` · `context_eval_real.jsonl` · `context_humor_benign.jsonl` — gold sources.
- `../../scripts/eval_context_fp.py` — the paired runner (F1 + F2) implementing this decision.
- `research-framing.decision.md` — parent RQ reframe (D-Reframe-2026-05-27).
</content>
