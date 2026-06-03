# Meeting 5 — Fine-tune the Hebrew Classifier

**Phase:** C · Development · **Status:** ⬜ not started · **Source:** `Shomer_AI_10_Meeting_Plan` §5
> Base model is whatever Step 4 froze. Technical detail for the local pipeline lives in
> [`../POC_Plan.md`](../POC_Plan.md) (Phase 3).

## 🎯 Goal
Replace the stand-in model with a **real fine-tuned Hebrew classifier**, evaluate it against the
Meeting-2 baseline, and get an F1 you can defend.

## 📋 Before
- Allocate GPU (Colab Pro / Kaggle / local CUDA via WSL2).
- Install training stack (`transformers`, `accelerate`, `peft`, MLflow).
- Clean dataset: tokenize, split 70/15/15.

## ⚙️ Steps
| # | Action | Output |
|---|--------|--------|
| 5.1 | Data pipeline: load, clean, tokenize, split, balance | `src/data/` + tests |
| 5.2 | Training script with config + MLflow logging | `src/training/` |
| 5.3 | First training run (checkpoint best) | trained model |
| 5.4 | Evaluation: F1/P/R, confusion matrix, error analysis | `notebooks/03_evaluation.ipynb` |
| 5.5 | 2–3 hyperparameter runs; compare in MLflow | `results/hyperparam_results.md` |
| 5.6 | Wrap winning model behind the server's `/classify` (swap out the stand-in) | updated server |
| 5.7 | Unit tests + edge cases (empty, very long, emoji-only) | `tests/` |

## 📦 Deliverables
Working classifier (`text → {is_offensive, category, confidence}`), a significant F1 (≥ baseline + ~10%), confusion matrix + error analysis, 3+ logged experiments.

## ✅ Done when
- The Android app gets responses from the **real** model on text (and OCR'd text).
- `evaluate.py` reports macro-F1 ≥ 0.70 on the balanced split; F1 saved to `results/metrics.json`.
- Tag **v0.5** "Classifier v1".

## ⚠️ Risks
- GPU OOM → gradient accumulation, smaller batch, fp16, or LoRA/QLoRA.
- Weak F1 (<0.7) → check class imbalance, weighted loss, more data (Meeting 6 helps).
- Model too big for GitHub → HuggingFace Hub / GGUF + git-lfs.

## Note (divergence)
Proposal = DictaBERT. POC prototype = Qwen 2.5 7B (QLoRA → GGUF → Ollama). Use the Step-4 decision.
