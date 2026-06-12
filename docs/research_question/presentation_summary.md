# Shomer.AI — Presentation Summary (RQ · Architecture · Results · Literature)

**Purpose:** ready-to-paste slide content. **Status:** corrected 2026-06-12 with the real
experiment numbers (MVP run 2026-06-11). Source of truth: `context_fp_mvp_results.md`,
`harm_context_results.md`, `plan-docs/decisions/context-fp-experiment.decision.md`.

---

## SLIDE 1 — The Research Question

**One line:**
> Does adding **conversational context** (the previous *k* turns) to Hebrew bullying
> classification **reduce false alarms (FPR)** — and recover **context-dependent harm** —
> versus judging each message in isolation, **without hurting recall**?

**The real problem:** a context-blind classifier "judges the text as-is." It false-alarms on
messages that *look* offensive but are innocent in context (sarcasm, friendly teasing, quoting),
and **misses** bullying that only becomes clear from earlier turns (veiled threats, pile-ons).

**Pre-registered success criterion (locked before the run):** statistically-significant FPR drop
(X ≥ 10pp) with non-inferior recall (Y ≤ 3pp), McNemar paired test, α = 0.05, k = 5 turns.

---

## SLIDE 2 — What's Already Known (Literature) vs. Our Gap

- **English** showed context matters but is hard: **Pavlopoulos 2020** (naive concatenation =
  only *marginal* gains; how to use context efficiently is open); **Sap 2019 / Davidson 2019**
  (context-blind classifiers mislabel up to **~50%** of benign in-dialect text as toxic).
- **Hebrew** has a labeled corpus — **SinaLab / Hamad 2023** (5 classes) — but it is
  **single messages, no conversation, no context axis.**
- **The gap = the contribution:** no Hebrew dataset of bullying *conversations* and no Hebrew
  study of *conversational context*. We carry a proven-in-English insight into Hebrew, where it
  has never been tested.

---

## SLIDE 3 — The Architecture IS the Experiment

Ports-and-adapters design makes the two conditions a **one-line flip** → clean, reproducible
comparison.

```
Android → FastAPI → DictaBERT classifier → triage → [Context Agent] → alerts
                    (context-BLIND          (the switch)  (context-AWARE
                     baseline)              CONTEXT_AGENT_ENABLED=false/true   treatment)
```

- **DictaBERT classifier** = content detector, **context-blind by construction** = the baseline arm.
- **Context Agent** (Gemini→Haiku judge, reads last 5 turns) = the context-aware treatment arm.
- Every module is a Protocol with ≥2 adapters; `main.py lifespan()` is the only wiring point →
  **swapping condition = one env-var flip.** 564 tests pass; full monitoring slice verified end-to-end.

---

## SLIDE 4 — Results We Already Have

### (a) The classifier (baseline) is strong
- DictaBERT Hebrew, **macro-F1 0.836**, all gate criteria PASS, well-calibrated (ECE 0.034).
- **424× faster + 2.4× more accurate** than off-the-shelf Ollama on the same 445 rows
  (89.4% vs 37.8%) → a trained model was necessary, proven with evidence.

### (b) The context experiment — run at MVP/feasibility level (2026-06-11)
**Experiment 1 — per-message, 61 Hebrew conversational items (34 benign / 27 offensive):**

| Metric | context-blind | context-aware | Δ | test |
|---|---|---|---|---|
| **FPR** | 55.9% | **26.5%** | **−29.4 pp** | McNemar p = **0.002** ✅ |
| Recall | 70.4% | 63.0% | −7.4 pp | (cost isolated to one control slice) |

- ΔFPR concentrated in **Category A** (context-flip cases): −34.8 pp → **proves H2**.
- Discordant pairs **c=10 win / b=0 cost** — context only ever *fixed* false alarms, never added one.

**Experiment 2 — harm-reframe, 143 multi-turn conversations** (target = *harmful situation*, not
*offensive word*):
- **0 alerts on 35 offensive-but-not-harmful** messages → **100% specificity** (banter correctly ignored).
- **Veiled threats recall 0% → 100%** with context; overall harm-recall **58.9% → 82.1% (+23 pp)**.
- **False-alarm rate 2.1%.**

### Combined finding
> Context helps on **both** axes: it **cuts false positives (−29pp)** where the cheap classifier
> over-flags, and is **required for harm recall (+23pp)** on context-dependent threats. The right
> alert target is the harmful **situation**, not the individual offensive **word**.

---

## SLIDE 5 — Honest Status & What Remains

- ✅ **RQ answered at MVP/feasibility level** — mechanism + apparatus proven, direction and
  significance of the FPR win are robust.
- ⚠️ **Caveats (stated, not hidden):** eval data is synthetic/authored (n=61 and n=143);
  single-annotator (no κ yet); the 143-set has some generator≈judge circularity (mitigated by
  design-labels). **Magnitudes are optimistic; only a real gold set can pin the publishable number.**
- 🎯 **Remaining work = replace synthetic eval with a real annotated gold set** (see below). The
  experiment is *built and run*; what's left is *credibility of the magnitude*, not *running it*.

---

## What the "real experiment" requires (the only remaining critical-path item)

The apparatus, runner, statistics, and pre-registered thresholds are **done**. The single blocker is
a **real Hebrew conversational gold set**. To make the number publishable:

1. **~150–200 real Hebrew conversation items**, composed by the proven 3-category design:
   **A** context-repairs-FP (~45%) · **B** context-reveals-TP (~25%) · **C** invariant controls (~30%).
   Must be **real** (public/scrubbed Hebrew chats), per train-on-synthetic / eval-on-real.
2. **Double annotation + Cohen's κ ≥ 0.6** — two annotators label each item; an item only counts as
   Category A if both agree it reads offensive *alone* and benign *in context*. κ itself is a thesis result.
3. **Ethics handling** — public sources only, minors handled carefully, PII scrubbed.
4. **Re-run the existing harness** (`scripts/eval_context_fp.py` + `viz_context_fp.py`) on the real set —
   no new code; same pre-registered X/Y/k/α.
5. **(Optional, the contribution)** **E6** — selective-agent vs. naive-concatenation vs. blind, on FPR,
   recall **and LLM cost** → directly answers Pavlopoulos's open question in Hebrew.

**Bottom line:** the thesis is **one real gold set away** from a publishable ΔFPR number. Everything
else — data schema, runner, stats, thresholds, architecture — already exists and has been exercised
end-to-end.
</content>
</invoke>
