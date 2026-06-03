# Meeting 2 — Literature Review & First Baseline

**Phase:** A · Research · **Status:** ⬜ not started · **Source:** `Shomer_AI_10_Meeting_Plan` §2
> See also [`../Shomer_AI_Sources_Summary.md`](../Shomer_AI_Sources_Summary.md) for the curated papers + datasets.

## 🎯 Goal
A real literature review (15–20 sources, 2 anchor papers), the main datasets downloaded, and a
first **baseline** that isn't good yet — but proves the system is alive and gives a number to beat.

## 📋 Before
- Skim the literature already in the proposal — it's the starting point, not the end.
- Install `transformers torch datasets scikit-learn pandas jupyter`.
- Connect to free GPU (Google Colab or Kaggle).

## ⚙️ Steps
| # | Action | Output |
|---|--------|--------|
| 2.1 | Collect 15–20 sources; filter to 8 core + 2 anchor papers | `docs/literature_review.md` |
| 2.2 | Comparison table (method, dataset, F1, language, gap) → name **your gap** | table in review |
| 2.3 | Download datasets: **OffensiveHebrew** (primary), Davidson (English baseline) | `data/raw/` |
| 2.4 | EDA: label balance, text lengths, examples per category | `notebooks/01_eda.ipynb` |
| 2.5 | Simple baseline: TF-IDF + Logistic Regression on OffensiveHebrew; record F1/P/R | `notebooks/02_baseline.ipynb` |
| 2.6 | Start the preparatory report (answer Dr. Segal's slide questions) | `docs/preparatory_report.md` v0.1 |

## 📦 Deliverables
`literature_review.md`, EDA notebook with charts, baseline notebook with a **specific** F1, datasets local with a `data/README.md`.

## ✅ Done when
- You can say in one sentence: "Anchor papers reached X; I'll aim for Y using Z."
- Baseline F1 is logged as a concrete number (not "about 70%").
- Tag **v0.2** "Research Foundation".

## ⚠️ Risks
- Dataset access → use the HuggingFace mirror; fall back to HASOC Hebrew.
- Baseline fails badly → that's fine, it justifies the fine-tuned model. Document the loss.
