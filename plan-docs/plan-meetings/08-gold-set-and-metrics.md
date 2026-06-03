# Meeting 8 — Gold Set, Measurement & Quality

**Phase:** C · Development · **Status:** ⬜ not started · **Source:** `Shomer_AI_10_Meeting_Plan` §8
> Evidence, not feelings. If the image-strategy study is in scope, this is where its numbers land
> (see [`../POC_Plan.md`](../POC_Plan.md) Phase 4 / `Architecture_Study.md`).

## 🎯 Goal
Build a hand-labelled **gold set** (300–500 examples), run the full system on it, get final metrics
(F1, FPR, latency, cost), and fix the 3–5 worst problems found.

## 📋 Before
- Recruit 2–3 volunteers for independent labelling (inter-annotator agreement).
- Prepare a labelling template (Google Sheets / Label Studio).
- Collect ~500 real raw messages (with permission) from Israeli forums / Reddit.

## ⚙️ Steps
| # | Action | Output |
|---|--------|--------|
| 8.1 | Build gold set, 3 labellers, Cohen's Kappa | `data/gold_set/v1.jsonl` |
| 8.2 | Run full system on gold set; collect F1/P/R/FPR/latency/cost | `results/gold_set_metrics.json` |
| 8.3 | Error analysis on 20–30 misses; classify error types | `results/error_analysis.md` |
| 8.4 | Fix top 3 issues (prompt / model / data); re-run; compare | v2 metrics |
| 8.5 | Sensitivity analysis (short, long, emoji, mixed-language) | `results/sensitivity.png` |
| 8.6 | Compare results vs anchor papers | `results/flagship_comparison.png` |
| 8.7 | Code quality: lint, tests with coverage, security scan | green CI |

## 📦 Deliverables
Gold set with agreement score, the 4 required charts (baseline comparison, model benchmark, sensitivity, anchor-paper gap), final metrics, green CI.

## ✅ Done when
- Every KPI in the PRD has a real measured value.
- Cohen's Kappa ≥ 0.65. All charts reproducible from a script.
- Tag **v1.0** "Production Ready".

## ⚠️ Risks
- Too few labellers → label alone, but get one or two people to label 50 for a quality check.
- Worse-than-expected results → explain what didn't work; that's part of the research.
- F1 up but FPR up too → show precision-recall + ROC, tune the threshold.
