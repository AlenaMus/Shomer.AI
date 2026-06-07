# Baseline Accuracy — Summary (no data changes, no DictaBERT training)

**Date:** 2026-06-06 · **Classifier:** Ollama `v1.0-standin` · **Full charts:** `meeting6_accuracy_report.pdf`
**Data:** 200 text + 300 image samples (stratified) from `data/ocr_validation/`
(1040 labelled Hebrew sentences; gold `none → non_offensive`). Raw metrics:
`accuracy_eval/results.json`.

This is the **pre-training baseline** — the number the DictaBERT fine-tune has to
beat. Metric = the classifier's predicted category vs. gold (independent of the
Context Agent, which only affects borderline triage routing).

## Headline

| Split | 5-class accuracy | Binary (offensive vs not) | macro-F1 | scored |
|---|---|---|---|---|
| **TEXT** (`/classify`) | **69.5 %** | **79.5 %** | 0.49 | 200/200 |
| **IMAGE** (`/classify-image`, OCR→classifier) | **66.3 %** | **80.3 %** | 0.46 | 300/300 |

0 request failures. **Image ≈ Text** → the Tesseract OCR path is *not* the
bottleneck (OCR fidelity is high; CER is low in `metrics.csv`); the **classifier**
is what limits accuracy.

## Per-class F1 (text / image)

| Label | F1 text | F1 image | Recall text | Recall image |
|---|---|---|---|---|
| non_offensive | 0.83 | 0.82 | 0.93 | 0.87 |
| abusive | 0.65 | 0.59 | 0.79 | 0.79 |
| **hate** | **0.16** | **0.20** | **0.09** | **0.11** |
| violence | 0.44 | 0.41 | 0.30 | 0.26 |
| pornographic | 0.38 | 0.27 | 0.25 | 0.24 |

## What the confusion matrices show

- The stand-in reliably separates **offensive vs. clean** (~80 %), which is why
  the binary number is much higher than the 5-class number.
- It **collapses fine-grained categories into `abusive`/`non_offensive`**:
  - `hate` is almost never predicted (recall ≈ 0.09–0.11) — gold `hate` lands in
    `non_offensive` or `abusive`.
  - `violence` gold frequently → `abusive`.
  - `pornographic` gold frequently → `non_offensive`.
- `non_offensive` and `abusive` are the only classes with usable recall.

## Takeaway

The current pipeline is a working **end-to-end baseline** but a weak fine-grained
classifier — strong, quantified motivation for the DictaBERT fine-tune (target
F1 ≥ 0.78 per the architecture doc). Re-running this same harness after flipping
`CLASSIFIER_MODEL_VERSION=v1.1-dictabert` turns this into the trained-vs-baseline
comparison. OCR needs no work for this dataset.

## With the real Context Agent (Gemini) enabled

Re-running the same 200 + 300 samples with `CONTEXT_AGENT_ENABLED=true` and real
Gemini (`gemini-2.5-flash` primary, Anthropic `haiku-4.5` fallback). Full report:
`meeting6_accuracy_report.pdf`; raw `accuracy_eval/results_with_ca.json`.

- **Classifier accuracy is unchanged** — TEXT 69.5 %→69.5 %, IMAGE 66.3 %→66.0 %.
  The CA never edits the classifier's label; it only resolves *escalated* cases.
- **CA invoked only on escalations** (violence always escalates), all via Gemini:
  TEXT **9** samples (7 judged threat / 2 not), IMAGE **12** (8 / 4).
- **End-to-end decision improves** (flag-offensive vs gold), frontline-only → with-CA:

  | Split | decision acc | recall on offensive | FPR |
  |---|---|---|---|
  | TEXT | 77.0 % → **80.5 %** (+3.5 pp) | 57.3 % → **64.6 %** (+7.3 pp) | 4.8 % → 4.8 % |
  | IMAGE | 77.0 % → **79.7 %** (+2.7 pp) | 66.0 % → **71.5 %** (+5.6 pp) | 12.8 % → 12.8 % |

The Context Agent lifts end-to-end recall on offensive content **with zero added
false positives** — exactly its designed role.

**Reproduce:**
```powershell
# baseline (classifier accuracy is CA-independent):
server\.venv\Scripts\python.exe scripts\eval_accuracy.py --server http://localhost:8000 --n-text 200 --n-image 300
# with the real Context Agent + audit read-back (server started with CONTEXT_AGENT_ENABLED=true):
server\.venv\Scripts\python.exe scripts\eval_accuracy.py --server http://localhost:8080 --db server/data/audit_eval_ca.db
```
