# Decision — Frontline classifier: our fine-tuned DictaBERT, not Ollama / off-the-shelf models

**Date:** 2026-06-08
**Phase/Step:** POC Phase 3 (frontline classifier) → server integration
**Status:** Active — wired live (`CLASSIFIER_MODEL_VERSION=v1.1-dictabert`)
**Related:** `plan-docs/decisions/data-pipeline.decision.md` (D1–D12, how the model was built),
`docs/research_question/research_question.md` (the context-FP contribution), `docs/accuracy_eval/ollama_vs_dictabert.*` (evidence).

---

## D-CLF-1 — The production frontline classifier is the fine-tuned DictaBERT (in-process, HuggingFace adapter)

**Question:** What runs the frontline 5-label Hebrew offensive classification (`abusive · hate · violence ·
pornographic · non_offensive`) — (a) our own fine-tuned **DictaBERT** (`v1.1-dictabert`), (b) the **Ollama
prompted-LLM stand-in** (`v1.0-standin`), or (c) an **existing off-the-shelf trained model**?

**Choice:** **(a) Our fine-tuned DictaBERT D10**, served in-process via the `HuggingFaceClassifier` adapter
behind the `TextClassifier` port (`server/app/classifier/`). The Ollama stand-in is retained **only as a
selectable fallback**; no off-the-shelf model is used as the production frontline.

**Why — head-to-head evidence (same 445 test rows, one harness, `scripts/eval_ollama_vs_dictabert.py`):**

| Metric | Ollama stand-in (`offensive-hebrew:v1`) | **DictaBERT D10** | Δ |
|---|---|---|---|
| 5-class accuracy | 37.8 % | **89.4 %** | +51.7 pp |
| Binary (offensive vs not) | 47.0 % | **90.3 %** | +43.3 pp |
| Macro-F1 | 0.373 | **0.836** | +0.463 |
| Mean latency / call | 7,222 ms | **17 ms** | ~424× faster |
| Per-class F1 (non_off / abusive / hate / violence / porn) | 0.45 / 0.33 / 0.17 / 0.30 / 0.62 | **0.93 / 0.83 / 0.74 / 0.71 / 0.97** | — |

Beyond the numbers, a discriminative encoder is the **right tool**: it emits a real, thresholdable 5-class
softmax the triage engine can route on; a generative LLM classifies as a fragile generation side-effect
(slower, format-dependent, uncalibrated). It also runs **locally** (184 M params, sub-second CPU, no per-call
cost, no chat text leaving the device) — the project's core privacy requirement — and is **fine-tunable /
ablatable**, which the research question's context-on-vs-off A/B requires.

---

## D-CLF-2 — Why we fine-tune our own model instead of using existing trained models (the unique-solution argument)

This is the explanation to use whenever asked "why not just use an existing Hebrew offensive-content model?"

**1. No existing trained offensive-Hebrew model can even run in the intended path.** Every published one
(SinaLab / Hamad et al. 2023; HeBERT offensive/hate; AlephBERT-based classifiers) is a **BERT encoder
classifier** — the same family as ours — so none are servable by Ollama (Ollama only runs generative GGUF
models). The only Ollama-runnable option is a *prompted generative LLM* (DictaLM 2.0, Gemma 2, Qwen2.5),
which **is** our `v1.0-standin` baseline — and it scores 37.8 % (above).

**2. The existing trained models don't fit the problem off the shelf:**
- **SinaLab / HeBERT** are trained on **isolated tweets** with **severe class imbalance** (raw SinaLab:
  pornographic = 4, abusive = 119 real examples) → a vanilla fine-tune has near-zero recall on the rare,
  highest-stakes classes (hate / violence / porn). They also report on their own balanced splits, not the
  realistic prevalence the product faces.
- **Multilingual toxicity models** (Perspective API, Detoxify-multilingual, XLM-R toxic) are English-centric,
  weak on Israeli-Hebrew slang and morphology, and use a **different (usually binary) taxonomy** — not our
  5-label schema that the triage engine depends on.
- **Prompted generative LLMs** are slow, uncalibrated, cloud-dependent (breaks local-first privacy), and —
  as measured — far less accurate on this distribution.

**3. Our solution is the combination none of them provide:**
- **Hebrew-native encoder** (DictaBERT) → better Hebrew tokenization/morphology than multilingual models.
- **Fine-tuned on the exact 5-label product schema.**
- **A 6-round data pipeline (D1–D12) that fixes SinaLab's imbalance** — prevalence-aware sampling + Focal
  loss + class weights + targeted synthesis/translation — giving usable recall on the rare classes
  (hate 0.74, violence 0.71) instead of ~0.
- **Calibration + an explicit ship gate** (macro-F1 ≥ 0.78, violence recall, non-offensive precision) and
  stylistic robustness probes — engineering rigor most published baselines don't ship.
- **Local, fast, private, in-process** serving via the ports-&-adapters `HuggingFaceClassifier`.
- **Ablatable** — the frontline model is the substrate for the thesis's real contribution: **adding
  conversational context to reduce false positives in Hebrew** (a prompted black-box LLM can't be ablated
  that way). The differentiator is *the context layer + privacy architecture + product*, with a competitive
  Hebrew-tuned frontline — not a leaderboard win.

**Bottom line for the thesis/pitch:** we did not "skip" existing models — none of them is a Hebrew-native,
correctly-taxonomized, imbalance-corrected, calibrated, locally-servable, ablatable classifier. Building that
stack **is** the unique solution.

---

## Alternatives considered

- **Ollama prompted LLM (`v1.0-standin`)** — rejected as production: 37.8 % / macro-F1 0.373, ~7 s/call,
  uncalibrated, cloud-ish. Kept as a fallback adapter and as the documented baseline.
- **Existing Hebrew encoders (SinaLab / HeBERT / AlephBERT)** — rejected: wrong/imbalanced training
  distribution, near-zero rare-class recall, not the realistic-prevalence setup; would still need our data
  pipeline to be usable.
- **Multilingual toxicity APIs/models (Perspective / Detoxify / XLM-R)** — rejected: not Hebrew-tuned, wrong
  taxonomy, and (Perspective) a cloud call that breaks local-first privacy.

## Honest caveats / limitations (do NOT over-claim)

1. **In-distribution vs OOD inflation.** D10 was evaluated on **its own held-out split** from the same data
   pipeline it trained on; the Ollama model saw that distribution cold. The 51-pp gap is real but **partly
   inflated** by in-distribution vs out-of-distribution.
2. **Synthetic minority test data.** `pornographic` test ≈ 100 % synthetic; `hate`/`violence` partly
   Jigsaw-translated; ~33 support/class. Minority per-class numbers (esp. porn 0.97) should be read with this
   caveat for BOTH models.
3. **No real natural-Hebrew gold-set benchmark yet** — the truly fair, defensible comparison for the thesis.
4. **Serve-time calibration not yet wired** (the isotonic calibrator wasn't persisted at train time) → the
   live server currently serves raw softmax and over-escalates some benign text to the Context Agent.

## Revisit

- After a **real natural-Hebrew gold-set** head-to-head (would make the superiority claim defensible — or
  temper it).
- After the **calibration fix** (fit + pickle `IsotonicRegression` on the 888 val rows).
- If a markedly stronger Hebrew offensive model is published, re-run the same `scripts/eval_ollama_vs_dictabert.py`
  harness against it before reconsidering.
