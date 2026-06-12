# Context → False-Positive Test Plan — proving the research question

**Status:** drafted 2026-06-08 (Meeting-7 prep). Working/analysis doc (English; Hebrew is the domain
language of the test items). Companion seed data: [`../../data/gold/context_eval_seed.jsonl`](../../data/gold/context_eval_seed.jsonl).
RQ source: [`research_question.md`](research_question.md) · literature: [`../literature/literature_flagship.md`](../literature/literature_flagship.md).

> **The research question (verbatim):** *To what extent does adding conversational context (the prior
> turns in the thread) to Hebrew bullying classification reduce the false-positive rate, vs. classifying
> the message in isolation — without hurting recall?*
> **Success =** a statistically-significant FPR drop with non-inferior recall, on a real gold set.

This document does three things you asked for:
1. **Analyses the existing flow** and shows the experiment apparatus is *already wired* (the
   `CONTEXT_AGENT_ENABLED` A/B switch) — plus three methodological footguns that flow creates.
2. **Specifies the test scenarios** (a 3-category matrix + a seeded gold set) that *prove* context cuts
   false positives without hurting recall.
3. **Maps each flagship paper to a concrete experiment** — what we must run to *contribute* to that
   literature rather than just cite it.

---

## 1. How the current flow already encodes the experiment

The pipeline is `classifier → triage → (context_agent) → alerts`. The classifier (**DictaBERT, D10**)
is **context-blind by construction** — it only ever sees the single message. *All* conversational
context enters at exactly one place: the **Context Agent**, and only for messages that triage routes to
it. The switch that turns context on/off already exists:

| Condition | Setting | What happens to a *borderline* message |
|---|---|---|
| **context-blind** (baseline) | `CONTEXT_AGENT_ENABLED=false` | Triage decides on the message alone via `baseline_threshold` (0.5). No history is ever read. |
| **context-aware** (treatment) | `CONTEXT_AGENT_ENABLED=true` | Triage escalates → Context Agent runs `read_history` (last 5 turns) → LLM judges *is_real_threat given context* → can downgrade an isolated-looking FP to `silent`. |

So the two arms of the RQ are **literally the same codebase with one env flag flipped**. This is the
product-level A/B (`scripts/eval_accuracy.py` already reads `frontline_only_decision` vs
`triage_decision` from the audit DB). The audit store even pre-exposes the eval hooks:
`query_for_evaluation()` + `set_gold_label()` (`server/app/audit_log/protocol.py`, tagged "Meeting-8
ΔFPR harness"). **The plumbing is done; the gold set and the experiment runner are the missing pieces.**

```
                                   prob_offensive
   message ──▶ DictaBERT ──▶ ┌──────────────────────────┐
              (context-blind)  │  ≤0.3 → SILENT            │  ← context never consulted
                               │  ≥0.7 → ALERT_DIRECT      │  ← context never consulted
                               │  0.3–0.7 BORDERLINE ──────┼──▶ CA reads history ──▶ keep / downgrade
                               └──────────────────────────┘       (THIS is where ΔFPR is born)
   violence → always ESCALATE_TO_CA   |   pornographic → always ALERT_DIRECT
```

---

## 2. Three methodological findings the flow forces (read before designing the run)

These are the things that, if ignored, will make the thesis numbers wrong or unconvincing.

**F1 — Context only acts inside the borderline band, so the *product* A/B under-measures the *scientific*
effect.** In production, a high-confidence false positive (`prob_offensive ≥ 0.7` on a benign sarcastic
line) goes straight to `ALERT_DIRECT` and never reaches the Context Agent — context gets *no chance* to
fix it. The measured ΔFPR is therefore bounded by "how many FPs happen to land in [0.3, 0.7]." → **For
the science run, route the entire gold set through the Context Agent** (or run the prompt-level A/B in
F2), so context's true ceiling is measured, not the production-tuned slice of it. Report both: "ΔFPR as
shipped" and "ΔFPR when context is always allowed to act."

**F2 — The cleanest comparison isolates *context*, not *the triage path*.** The product A/B changes two
things at once (context **and** the routing rule). The defensible scientific baseline is the **same LLM
judge, same prompt, history block empty vs. populated** — `build_user_prompt(..., conversation_history=[])`
vs `(..., conversation_history=turns)`. That makes context the *only* independent variable. Run **both**:
the prompt-level A/B is the thesis claim; the product A/B is the deployment validation. (`build_user_prompt`
in `server/app/context_agent/prompt.py` already takes history as a parameter — the empty-list arm is free.)

**F3 — "False positive" must be defined on the binary offensive/benign axis, paired per item.** FPR =
`FP / (FP + TN)` over items whose gold label is **benign**. The whole experiment is *paired* (every gold
item is scored by both arms), so the right significance test is **McNemar's**, not a two-sample test —
see §5.

---

## 3. The test-scenario matrix — what *proves* the claim

A gold item is a tuple `(history[ ], message, gold_is_offensive, isolated_appearance)`. The proof rests on
three deliberately-constructed categories. Seed examples for each are in
[`context_eval_seed.jsonl`](../../data/gold/context_eval_seed.jsonl).

### Category A — context **repairs** a false positive *(this is the headline; drives ΔFPR)*
Message looks **offensive in isolation**, is **benign in context**. If context works, the aware arm flips
these from "flag" → "silent". Subtypes (each a slice we report separately, per stretch RQ3):

| Subtype | Hebrew example (message) | Why it's benign in context |
|---|---|---|
| Friendly teasing | `"חחח אתה כזה מטומטם 😂"` | prior turns are mutual joking between friends |
| Sarcasm / irony | `"וואו, גאון אמיתי, כל הכבוד לך"` | prior turn was self-deprecating; this is supportive sarcasm |
| Quoting / reporting | `"הוא אמר לי 'תמות כבר' ונורא נפגעתי"` | child is *reporting* being hurt, not threatening |
| Self-directed | `"אני כזה לוזר היום, נכשלתי במבחן"` | target is the speaker themselves |
| Gaming / competitive banter | `"אני אהרוג אותך בסיבוב הבא במשחק"` | prior turns establish a video-game match |
| Reclaimed in-group slang | `"בוא הנה אחי המטורף שלי"` | affectionate in-group register |

### Category B — context **reveals** a true positive *(protects recall; the non-inferiority guard)*
Message looks **benign in isolation**, is **bullying in context**. If the aware arm naively trusts
context to "calm things down," it will *miss* these — so they are the recall trap that proves context
doesn't cost us recall.

| Subtype | Hebrew example (message) | Why it's offensive in context |
|---|---|---|
| Escalating pile-on | `"כולם מסכימים. תעלם כבר."` | prior turns are a coordinated pile-on against the child |
| Veiled / coded threat | `"אתה יודע מה מחכה לך מחר בהפסקה."` | prior turn made the threat explicit; this references it |
| Conditional resolved by history | `"אם לא תביא, אתה יודע מה יקרה."` | antecedent ("we'll hit you") is in the prior turn |
| Targeted continuation | `"וגם אמא שלך."` | benign words; completes a prior insult chain |

### Category C — context-**invariant** controls *(sanity / specificity; must not move)*
The call is the same with or without context. Three flavours:
- **C-benign:** clearly benign, benign history → stays `silent` (true negative both arms).
- **C-direct-offensive:** unambiguous abuse/threat, any history → stays flagged (true positive both arms).
- **C-always-alert:** `pornographic` / explicit `violence` → flagged regardless (tests the override rules).

**Why three categories and not one bucket:** they let us decompose the result the way the hypotheses
demand — **A** produces the ΔFPR (H1, H2), **B** proves recall survives (H1's "without hurting recall"),
**C** proves we didn't just globally desensitise the system (specificity unchanged). A single mixed set
would let a "context = trust everything" degenerate strategy *look* like success on FPR while silently
destroying recall on B.

### Target composition (gold set v1)
~150–200 items: **A ≈ 45%** (the effect lives here), **B ≈ 25%** (recall guard), **C ≈ 30%** (controls,
split ~半 benign / half offensive). Each item carries `isolated_appearance` so we can confirm the trap is
real: an item only counts as a valid Category-A test if a human (and ideally the context-blind model)
*does* read it as offensive in isolation.

---

## 4. The experiments — and exactly what each one proves

| # | Experiment | Arms | Metric | Proves |
|---|---|---|---|---|
| **E1** | **Primary ΔFPR** | blind vs aware, full gold set | FPR per arm + McNemar on benign items | **H1**: context lowers FPR significantly |
| **E2** | **Effect localisation** | both arms, sliced by category | ΔFPR on **A** vs on **C-benign** | **H2**: the drop is concentrated in context-flip cases, not a global shift |
| **E3** | **Recall non-inferiority** | both arms, on offensive items (B + C-offensive) | recall per arm; CI on Δrecall | the "**without hurting recall**" clause: recall_aware ≥ recall_blind − Y |
| **E4** *(stretch RQ2)* | **Context-window ablation** | k = 0, 1, 3, 5 prior turns | FPR & recall vs k | the precision/recall **Pareto** over context depth |
| **E5** *(stretch RQ3)* | **Mechanism / error analysis** | aware arm, per A-subtype | per-subtype repair rate | *which* linguistic cases context fixes (sarcasm✓ vs coded-threat✗ …) |
| **E6** *(contribution)* | **Selective-agent vs naive-concat** | blind / naive-concat-to-classifier / selective-CA | FPR, recall, **LLM cost** | our *selective* context beats Pavlopoulos's "naive concat = marginal" |

**Pre-registered thresholds (fill before the run — H1 needs X, Y fixed in advance to avoid p-hacking):**
- **X** = minimum FPR drop to claim success (proposal: ≥ 10 percentage points absolute, or ≥ 30% relative).
- **Y** = max tolerated recall loss for non-inferiority (proposal: ≤ 3 percentage points).
- **α** = 0.05, McNemar two-sided.

The headline thesis sentence the run must fill in:
> *"On a real Hebrew conversational gold set, adding ≤5 turns of context reduced the false-positive rate
> from **FPR_blind** to **FPR_aware** (−**Δ** pp, McNemar p = **p**), while recall changed by **Δr** pp
> (non-inferior at Y=3pp). 88% of the FP reduction came from Category-A context-flip items."*

---

## 5. Statistical method (paired design → McNemar)

Every gold item is scored by **both** arms, so the data is paired. For the FPR claim, build a 2×2 on the
**benign** items only:

```
                        aware: correct (TN)   aware: wrong (FP)
   blind: correct (TN)         a                    b
   blind: wrong   (FP)         c                    d
```
- `c` = FPs the **blind** arm made that **aware** fixed (the win).
- `b` = new FPs the aware arm introduced (the cost — should be ~0).
- **McNemar:** χ² = (|b − c| − 1)² / (b + c); report exact binomial if b+c < 25.
- Headline ΔFPR = (c − b) / (#benign items).

For recall (E3), the same paired table on **offensive** items; non-inferiority = upper CI bound of
(recall_blind − recall_aware) < Y. For per-class detail, keep the 5-label confusion matrices, but the RQ
is decided on the **binary** offensive/benign axis.

Report **inter-annotator agreement** (Cohen's κ) on the gold labels — Category A/B items are
intentionally ambiguous, so a defensible κ (≥ 0.6) is itself a thesis result.

---

## 6. How this contributes to the flagship literature

| Flagship | What it established | **What our test adds (the contribution)** | Experiment |
|---|---|---|---|
| **SinaLab / Hamad 2023** (Hebrew, isolated tweets) | 5-label schema + context-blind Hebrew baseline | We use their schema *and their isolated-message model as our blind baseline*, then add the conversational layer they lack. **First context-aware Hebrew offensive eval.** | E1 |
| **Pavlopoulos 2020** ("does context matter?") | Naïve context-concatenation gives only **marginal** gains; *how* to use context efficiently is open | We test a **selective, agentic** alternative to naive concat (escalate only ambiguous cases to a context-reasoning LLM) and show it beats both no-context *and* naive concat — a direct answer to their open problem, in Hebrew. | **E6**, E1 |
| **Sap 2019 / Davidson 2019** (FP / bias axis) | Context-blind classifiers false-flag up to ~50% of benign in-group/dialect text | We **quantify the correction**: how much of that FP load context recovers, in Hebrew, with κ-validated labels. | E1, E2 |
| **SynBullying 2025 / ToxiGen 2022** (synthetic data) | Synthetic conversational toxicity data is viable; train-on-synthetic works | We produce a **labeled Hebrew conversational set with explicit context-flip annotations** (Category A/B) — a reusable artifact extending SynBullying to Hebrew. | gold-set build |
| **"Synthetic vs. Gold" 2025** | Trust synthetic for *training*, evaluate on *real* | We honour it exactly: **train-on-synthetic, evaluate-on-real gold** — the gold set in §7 is the "real" half. | all |

**The single sentence for Related Work:** *no prior work measures whether conversational context reduces
false positives in **Hebrew** offensive-language detection, and Pavlopoulos's "context barely helps" result
was obtained with **naive concatenation** — we test a **selective-agent** context strategy in Hebrew and
isolate its effect on the **false-positive** axis specifically.* E6 is the experiment that turns this from
a citation into a contribution.

---

## 7. Gold-set construction (the one missing dependency)

Everything else is built; this is the blocker.

### 7.1 Gold set v1 — BUILT (status 2026-06-10)

The gold set is now **assembled and validated** — `data/gold/context_gold_v1.jsonl` (**34 non-synthetic
items**, the runner's `--gold` target). Synthetic `context_eval_seed.jsonl` (23) is held **out** of the
gold/eval split (train-only, per D-CFP-4). Sources + composition:

| Source file | n | Provenance | Role in the proof |
|---|---|---|---|
| `context_authored_seed.jsonl` | 20 | Authored from offensive/sarcasm screenshots (incl. Desktop `offensive.png`/`offensive2.png`) | A flip-cases + B pile-on reveals + C-offensive |
| `context_eval_real.jsonl` | 8 | Real bullying-thread screenshots (`cc.png`,`xx.png`), PII-scrubbed | B reveals + C controls |
| `context_humor_benign.jsonl` | 6 | Curated WhatsApp humor (`whatsapp_humor_examples.md`, with `#tags`) | **C-benign specificity controls** (the TN denominator) |

**Composition:** A 32% (11) · B 24% (8) · C-benign 24% (8) · C-offensive 21% (7) → **19 benign / 15
offensive**. The humor add lifted the benign FPR denominator from ~13 → 19 — the previously-thinnest slice.

**The contrastive backbone (the headline argument made concrete):** the WhatsApp humor items (`HU-*`) and
the `offensive2.png` pile-on items (`AU-19`/`AU-20`) are the **same surface form — a sarcastic put-down —
with opposite gold labels**, separated only by context (friends ribbing vs. a coordinated pile-on). That
pairing is exactly what proves context (not surface lexicon) carries the signal: a context-blind model
cannot tell `HU-04` ("יודע איפה כפתור ההפעלה") from `AU-20` ("מפתיע שהצלחת להגיע לבד"), but the
context-aware arm should. Each item carries a `tags` field (the chat's style tags) so per-tag repair/recall
can be sliced in E5.

**Still short of the §3 target (~150–200):** v1 is a high-quality, balanced *core*. To scale, fill the
remaining 44 placeholders in `whatsapp_humor_examples.md` (more benign controls) and add more real
context-flip screenshots (more Category A). Double-annotation for κ (D-CFP-3) is still outstanding.

1. **Schema** (already drafted in the seed file): `id, category, subtype, history[], message, gold_label,
   gold_is_offensive, isolated_appearance, rationale_he, rationale_en`.
2. **Sourcing** (per the reframe decision — train-on-synthetic / eval-on-real):
   - **Real (preferred for gold):** public Hebrew chat snippets, teen forums, scrubbed and consented;
     hand-curate the context-flip cases. *Ethics: public sources, minors handled carefully (RQ doc §open).*
   - **Synthetic seed (for scale + to guarantee the flip cases exist):** the `context_eval_seed.jsonl`
     here is the bootstrap — extend with Gemini synthesis the way `training/synthesize_*.py` already do,
     but **keep synthetic out of the gold split** (it may seed *training* conversations only).
3. **Double-annotate** for κ; resolve disagreements; an item only enters Category A if annotators agree it
   reads offensive *in isolation* and benign *in context*.
4. **Wire the runner:** small script over `ShomerApi` / `:sdk-cli batch` (SDK-CLI-03, still to build) that
   POSTs each item twice (history empty vs populated, F2) and once through the live pipeline with the flag
   on/off (F1), then writes the paired tables for §5. `query_for_evaluation()` + `set_gold_label()` are the
   audit-DB path for the product-level run.

---

## 8. What to do next (ordered)

1. **Lock X, Y, k** with Alona (and α) — *before* any run (pre-registration; H1 requires it).
2. **Build the gold set** (§7) — ~150–200 items, double-annotated, κ reported. *This is the critical path.*
3. **Build the paired runner** (prompt-level A/B = F2; product-level A/B = F1) → emits the §5 tables.
4. **Run E1–E3** (core thesis). Add **E6** if time — it is the strongest literature contribution.
5. **Decision file** once the methodology (prompt-level vs product-level as primary; X/Y/k values) is
   locked → `plan-docs/decisions/context-fp-experiment.decision.md`.

> **Bottom line:** the apparatus (`CONTEXT_AGENT_ENABLED` A/B, audit eval hooks, prompt with optional
> history) already exists. The thesis is one gold set + one paired runner away from a publishable
> ΔFPR number — and E6 (selective-agent vs naive-concat) is what makes it a *contribution* to
> Pavlopoulos's open question, not just the first Hebrew data point.
</content>
</invoke>
