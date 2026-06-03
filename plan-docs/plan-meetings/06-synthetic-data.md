# Meeting 6 — Synthetic Data & Augmentation

**Phase:** C · Development · **Status:** ⬜ not started · **Source:** `Shomer_AI_10_Meeting_Plan` §6
> This is the proposal's headline contribution: closing the **current-slang** gap that
> OffensiveHebrew (2023, formal Twitter) misses.

## 🎯 Goal
Generate 2,000+ contemporary-Hebrew synthetic examples, quality-filter them, retrain, and show a
**measurable F1 lift** on a slang test set.

## 📋 Before
- Read the LLM-augmentation papers (Lippmann 2024, Long 2024).
- Define a 5–7 category taxonomy (exclusion, ridicule, threats, sexual harassment, identity-based, self-harm, neutral).
- API key with a small budget ($20–30 is enough).

## ⚙️ Steps
| # | Action | Output |
|---|--------|--------|
| 6.1 | Generator using an LLM with 4 strategies (zero-shot, few-shot seeded, adversarial, back-translation) | `src/data_aug/` |
| 6.2 | Generate ~2,500 examples (5 cats × 500); log every prompt | `data/synthetic/v1.jsonl` |
| 6.3 | Quality filter: diversity (cosine), human review of 10%, adversarial validation | `data/synthetic/v1_filtered.jsonl` |
| 6.4 | Retrain on OffensiveHebrew + synthetic (weighted loss on synthetic) | model v2 |
| 6.5 | Ablation: v1 (no synth) vs v2 (with synth) on original + slang test sets | `results/ablation_study.png` |
| 6.6 | Cost tracking vs theoretical human-annotation cost | `results/synth_cost_analysis.md` |

## 📦 Deliverables
2,000+ filtered synthetic examples, prompt book with 15+ documented prompts, model v2 with a +5pp F1 on slang, ablation chart.

## ✅ Done when
- You can say: "2,000 synthetic examples raised F1 by X% on slang for $Y."
- Every prompt in the book has goal / model / result / decision.
- Tag **v0.6** "Data Augmentation".

## ⚠️ Risks
- Poor synthetic quality (English instead of Hebrew, shallow) → few-shot with real seeds, aggressive filtering, 10% manual check.
- Synthetic hurts real-data performance (distribution shift) → weighted loss or 70/30 real/synth mix.
