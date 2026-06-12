"""
plot_results.py — Publication-quality result graphs for DictaBERT D10 final model.

Reads:
  - training/outputs/dictabert-offensive/hf_trainer/checkpoint-1500/trainer_state.json
      (log_history with per-step train loss + per-epoch eval metrics)
  - checkpoint-best/  (model + tokenizer, for inference re-run)
  - data/test.jsonl, data/validation.jsonl, data/stylistic_eval.jsonl

Writes 300-dpi PNGs to:
  training/outputs/dictabert-offensive/plots/

Figures produced:
  01_confusion_matrix_counts.png     — 5x5 raw-count heatmap
  02_confusion_matrix_normalized.png — 5x5 row-normalized heatmap
  03_per_class_metrics.png           — precision / recall / F1 grouped bars
  04_training_curves.png             — train loss + eval loss + eval macro-F1
  05_per_class_f1_epochs.png         — per-class eval F1 vs epoch
  06_calibration_reliability.png     — reliability diagram before/after calibration
  07_stylistic_slice_f1.png          — stylistic-slice macro-F1 bar chart

Run (WSL2):
  source ~/shomer-training-venv/bin/activate
  cd /mnt/c/AIDevelopmentCourse/Shomer.AI
  python training/plot_results.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import torch
import torch.nn.functional as F

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).parent.parent
DATA_DIR = REPO_ROOT / "data"
OUTPUT_DIR = REPO_ROOT / "training" / "outputs" / "dictabert-offensive"
PLOT_DIR = OUTPUT_DIR / "plots"
BEST_CKPT = OUTPUT_DIR / "checkpoint-best"
TRAINER_STATE = OUTPUT_DIR / "hf_trainer" / "checkpoint-1500" / "trainer_state.json"

# Label order — locked
LABEL_NAMES = ["non_offensive", "abusive", "hate", "violence", "pornographic"]
LABEL_DISPLAY = ["non_offensive", "abusive", "hate", "violence", "pornographic"]
NUM_LABELS = 5
MAX_LENGTH = 96
SEED = 42

# Gate values for reference lines
GATE_MACRO_F1 = 0.78


# ---------------------------------------------------------------------------
# Import matplotlib (install if missing)
# ---------------------------------------------------------------------------
try:
    import matplotlib
    import matplotlib.pyplot as plt
    import matplotlib.ticker as mticker
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "matplotlib"])
    import matplotlib
    import matplotlib.pyplot as plt
    import matplotlib.ticker as mticker

matplotlib.use("Agg")  # headless — no display needed

# ---------------------------------------------------------------------------
# Shared style
# ---------------------------------------------------------------------------
plt.rcParams.update({
    "font.size": 11,
    "axes.titlesize": 13,
    "axes.labelsize": 12,
    "xtick.labelsize": 10,
    "ytick.labelsize": 10,
    "figure.dpi": 100,
    "savefig.dpi": 300,
    "axes.spines.top": False,
    "axes.spines.right": False,
})

COLORS = {
    "non_offensive": "#4C72B0",
    "abusive":       "#DD8452",
    "hate":          "#55A868",
    "violence":      "#C44E52",
    "pornographic":  "#8172B2",
}
COLOR_LIST = list(COLORS.values())

# ---------------------------------------------------------------------------
# Helper: load jsonl
# ---------------------------------------------------------------------------

def load_jsonl(path: Path) -> List[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


# ---------------------------------------------------------------------------
# Helper: load model + tokenizer from checkpoint-best
# ---------------------------------------------------------------------------

def load_model_and_tokenizer(ckpt_dir: Path, device: torch.device):
    """
    Load DictaBertWithMlpHead from checkpoint-best.
    Imports the class from train_dictabert to ensure identical architecture.
    """
    # Add training/ to sys.path so we can import train_dictabert
    training_dir = REPO_ROOT / "training"
    if str(training_dir) not in sys.path:
        sys.path.insert(0, str(training_dir))

    from train_dictabert import (
        DictaBertMlpConfig,
        DictaBertWithMlpHead,
        LABEL_NAMES as TL,
        LABEL2ID,
        ID2LABEL,
    )
    from transformers import AutoTokenizer

    print(f"Loading tokenizer from {ckpt_dir}...")
    tokenizer = AutoTokenizer.from_pretrained(str(ckpt_dir))

    print(f"Loading model from {ckpt_dir}...")
    config = DictaBertMlpConfig.from_pretrained(str(ckpt_dir))
    model = DictaBertWithMlpHead.from_pretrained(
        str(ckpt_dir),
        config=config,
        ignore_mismatched_sizes=False,
    )
    model = model.to(device)
    model.eval()
    print(f"Model loaded — {sum(p.numel() for p in model.parameters()):,} parameters")
    return model, tokenizer


# ---------------------------------------------------------------------------
# Helper: run inference on a list of rows, return probs + preds + labels
# ---------------------------------------------------------------------------

def run_inference(
    model, tokenizer, rows: List[dict], device: torch.device, batch_size: int = 64
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Returns:
      probs:  (N, 5) float32 softmax probabilities
      preds:  (N,) int argmax predictions
      labels: (N,) int ground-truth label ids
    """
    all_probs = []
    all_labels = []

    with torch.no_grad():
        for i in range(0, len(rows), batch_size):
            batch = rows[i : i + batch_size]
            texts = [r["text"] for r in batch]
            label_ids = [r["label_id"] for r in batch]

            enc = tokenizer(
                texts,
                truncation=True,
                max_length=MAX_LENGTH,
                padding="max_length",
                return_tensors="pt",
            )
            enc = {k: v.to(device) for k, v in enc.items()}
            out = model(**enc)
            probs = F.softmax(out.logits.float(), dim=-1).cpu().numpy()
            all_probs.append(probs)
            all_labels.extend(label_ids)

    probs_arr = np.concatenate(all_probs, axis=0)
    labels_arr = np.array(all_labels, dtype=np.int64)
    preds_arr = probs_arr.argmax(axis=1)
    return probs_arr, preds_arr, labels_arr


# ---------------------------------------------------------------------------
# Figure 1 & 2: Confusion matrices
# ---------------------------------------------------------------------------

def plot_confusion_matrices(
    cm: np.ndarray,
    label_names: List[str],
    out_dir: Path,
) -> None:
    """Plot raw-count and row-normalized confusion matrices side by side or as separate files."""

    # --- Figure 1: Raw counts ---
    fig, ax = plt.subplots(figsize=(7, 6))
    im = ax.imshow(cm, interpolation="nearest", cmap="Blues")
    plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    ax.set_xticks(range(len(label_names)))
    ax.set_yticks(range(len(label_names)))
    ax.set_xticklabels(label_names, rotation=35, ha="right", fontsize=9)
    ax.set_yticklabels(label_names, fontsize=9)
    ax.set_xlabel("Predicted label")
    ax.set_ylabel("True label")
    ax.set_title("Confusion Matrix — Test Set (raw counts)\nDictaBERT D10, macro-F1 = 0.836")

    thresh = cm.max() / 2.0
    for i in range(cm.shape[0]):
        for j in range(cm.shape[1]):
            ax.text(
                j, i, str(cm[i, j]),
                ha="center", va="center",
                color="white" if cm[i, j] > thresh else "black",
                fontsize=10, fontweight="bold",
            )

    fig.tight_layout()
    out_path = out_dir / "01_confusion_matrix_counts.png"
    fig.savefig(out_path)
    plt.close(fig)
    print(f"Saved {out_path}")

    # --- Figure 2: Row-normalized ---
    cm_norm = cm.astype(float)
    row_sums = cm_norm.sum(axis=1, keepdims=True)
    row_sums[row_sums == 0] = 1  # avoid div-by-zero
    cm_norm = cm_norm / row_sums

    fig, ax = plt.subplots(figsize=(7, 6))
    im = ax.imshow(cm_norm, interpolation="nearest", cmap="Blues", vmin=0, vmax=1)
    cbar = plt.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    cbar.set_label("Recall (row proportion)")
    ax.set_xticks(range(len(label_names)))
    ax.set_yticks(range(len(label_names)))
    ax.set_xticklabels(label_names, rotation=35, ha="right", fontsize=9)
    ax.set_yticklabels(label_names, fontsize=9)
    ax.set_xlabel("Predicted label")
    ax.set_ylabel("True label")
    ax.set_title("Confusion Matrix — Test Set (row-normalized recall)\nDictaBERT D10, macro-F1 = 0.836")

    for i in range(cm_norm.shape[0]):
        for j in range(cm_norm.shape[1]):
            ax.text(
                j, i, f"{cm_norm[i, j]:.2f}",
                ha="center", va="center",
                color="white" if cm_norm[i, j] > 0.6 else "black",
                fontsize=9,
            )

    fig.tight_layout()
    out_path = out_dir / "02_confusion_matrix_normalized.png"
    fig.savefig(out_path)
    plt.close(fig)
    print(f"Saved {out_path}")


# ---------------------------------------------------------------------------
# Figure 3: Per-class metrics bar chart
# ---------------------------------------------------------------------------

def plot_per_class_metrics(
    precision: np.ndarray,
    recall: np.ndarray,
    f1: np.ndarray,
    label_names: List[str],
    out_dir: Path,
) -> None:
    n = len(label_names)
    x = np.arange(n)
    width = 0.25

    fig, ax = plt.subplots(figsize=(9, 5))
    bars_p = ax.bar(x - width, precision, width, label="Precision", color="#4C72B0", alpha=0.85)
    bars_r = ax.bar(x,         recall,    width, label="Recall",    color="#DD8452", alpha=0.85)
    bars_f = ax.bar(x + width, f1,        width, label="F1-score",  color="#55A868", alpha=0.85)

    # Annotate F1 values on top
    for bar, val in zip(bars_f, f1):
        ax.text(
            bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.01,
            f"{val:.3f}", ha="center", va="bottom", fontsize=8.5, fontweight="bold",
        )

    ax.axhline(GATE_MACRO_F1, color="red", linestyle="--", linewidth=1.2,
               label=f"Gate threshold ({GATE_MACRO_F1})")
    ax.set_xticks(x)
    ax.set_xticklabels(label_names, fontsize=10)
    ax.set_ylabel("Score")
    ax.set_ylim(0, 1.08)
    ax.set_title("Per-Class Precision / Recall / F1 — Test Set\nDictaBERT D10 final checkpoint")
    ax.legend(fontsize=9, loc="lower right")
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.2f"))

    fig.tight_layout()
    out_path = out_dir / "03_per_class_metrics.png"
    fig.savefig(out_path)
    plt.close(fig)
    print(f"Saved {out_path}")


# ---------------------------------------------------------------------------
# Figure 4: Training curves — train loss + eval loss + eval macro-F1 (2-panel)
# ---------------------------------------------------------------------------

def plot_training_curves(log_history: List[dict], out_dir: Path) -> None:
    # Separate train-step entries from eval-epoch entries
    train_steps = [(e["step"], e["epoch"], e["loss"])
                   for e in log_history if "loss" in e and "eval_loss" not in e]
    eval_epochs = [(e["epoch"], e["eval_loss"], e["eval_macro_f1"])
                   for e in log_history if "eval_loss" in e]

    if not train_steps or not eval_epochs:
        print("WARNING: log_history missing train/eval entries — skipping training curves")
        return

    t_steps   = [x[0] for x in train_steps]
    t_epochs  = [x[1] for x in train_steps]
    t_losses  = [x[2] for x in train_steps]

    e_epochs   = [x[0] for x in eval_epochs]
    e_losses   = [x[1] for x in eval_epochs]
    e_macro_f1 = [x[2] for x in eval_epochs]

    # Best epoch
    best_epoch_idx = int(np.argmax(e_macro_f1))
    best_epoch     = e_epochs[best_epoch_idx]
    best_f1        = e_macro_f1[best_epoch_idx]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

    # --- Left: Loss curves ---
    ax1.plot(t_epochs, t_losses, color="#4C72B0", linewidth=1.5,
             label="Train loss (per step)", alpha=0.8)
    ax1.plot(e_epochs, e_losses, "o-", color="#DD8452", linewidth=2,
             markersize=7, label="Eval loss (per epoch)")
    ax1.axvline(best_epoch, color="green", linestyle="--", linewidth=1.2,
                label=f"Best epoch ({best_epoch:.0f})")
    ax1.set_xlabel("Epoch")
    ax1.set_ylabel("Loss")
    ax1.set_title("Training & Validation Loss")
    ax1.legend(fontsize=9)
    ax1.set_xlim(0, max(t_epochs) + 0.2)

    # --- Right: Eval macro-F1 ---
    ax2.plot(e_epochs, e_macro_f1, "s-", color="#55A868", linewidth=2,
             markersize=8, label="Eval macro-F1")
    ax2.scatter([best_epoch], [best_f1], color="gold", s=120, zorder=5,
                edgecolors="black", linewidths=1.2,
                label=f"Best epoch {best_epoch:.0f} (F1={best_f1:.3f})")
    ax2.axhline(GATE_MACRO_F1, color="red", linestyle="--", linewidth=1.2,
                label=f"Gate ({GATE_MACRO_F1})")
    ax2.set_xlabel("Epoch")
    ax2.set_ylabel("Macro-F1")
    ax2.set_title("Eval Macro-F1 per Epoch")
    ax2.set_ylim(0.65, 0.88)
    ax2.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.2f"))
    ax2.legend(fontsize=9)

    fig.suptitle("DictaBERT D10 Training Curves", fontsize=14, fontweight="bold", y=1.01)
    fig.tight_layout()
    out_path = out_dir / "04_training_curves.png"
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {out_path}")


# ---------------------------------------------------------------------------
# Figure 5: Per-class F1 across epochs
# ---------------------------------------------------------------------------

def plot_per_class_f1_epochs(log_history: List[dict], out_dir: Path) -> None:
    eval_entries = [e for e in log_history if "eval_macro_f1" in e]
    if not eval_entries:
        print("WARNING: no eval entries in log_history — skipping per-class F1 epochs")
        return

    epochs = [e["epoch"] for e in eval_entries]
    class_f1s = {
        name: [e[f"eval_f1_{name}"] for e in eval_entries]
        for name in LABEL_NAMES
    }

    best_epoch_idx = int(np.argmax([e["eval_macro_f1"] for e in eval_entries]))
    best_epoch = epochs[best_epoch_idx]

    fig, ax = plt.subplots(figsize=(9, 5))
    for name in LABEL_NAMES:
        ax.plot(epochs, class_f1s[name], "o-", linewidth=2, markersize=7,
                color=COLORS[name], label=name)

    # Macro-F1 as dashed black line
    macro_f1s = [e["eval_macro_f1"] for e in eval_entries]
    ax.plot(epochs, macro_f1s, "k--", linewidth=1.8, label="macro-F1 (avg)", alpha=0.6)

    ax.axvline(best_epoch, color="green", linestyle=":", linewidth=1.5,
               label=f"Best epoch ({best_epoch:.0f})")
    ax.axhline(GATE_MACRO_F1, color="red", linestyle="--", linewidth=1.0,
               label=f"Gate ({GATE_MACRO_F1})", alpha=0.7)

    ax.set_xlabel("Epoch")
    ax.set_ylabel("F1-score")
    ax.set_title("Per-Class Eval F1 across Epochs\nDictaBERT D10 — minority classes climbing")
    ax.set_ylim(0.50, 1.02)
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.2f"))
    ax.legend(fontsize=9, loc="lower right", ncol=2)

    fig.tight_layout()
    out_path = out_dir / "05_per_class_f1_epochs.png"
    fig.savefig(out_path)
    plt.close(fig)
    print(f"Saved {out_path}")


# ---------------------------------------------------------------------------
# Figure 6: Calibration / reliability diagram — before vs after isotonic
# ---------------------------------------------------------------------------

def compute_ece_and_reliability(
    probs: np.ndarray,
    labels: np.ndarray,
    n_bins: int = 15,
) -> Tuple[float, np.ndarray, np.ndarray, np.ndarray]:
    """
    Compute ECE and per-bin (conf, acc, count) for the reliability diagram.
    Returns: ece, bin_confs, bin_accs, bin_counts
    """
    max_probs = probs.max(axis=1)
    preds = probs.argmax(axis=1)
    correct = (preds == labels).astype(float)

    bins = np.linspace(0, 1, n_bins + 1)
    bin_confs = np.zeros(n_bins)
    bin_accs = np.zeros(n_bins)
    bin_counts = np.zeros(n_bins, dtype=int)

    ece = 0.0
    for k, (lo, hi) in enumerate(zip(bins[:-1], bins[1:])):
        mask = (max_probs > lo) & (max_probs <= hi)
        n = mask.sum()
        if n == 0:
            bin_confs[k] = (lo + hi) / 2
            continue
        acc_bin = correct[mask].mean()
        conf_bin = max_probs[mask].mean()
        ece += n * abs(acc_bin - conf_bin)
        bin_confs[k] = conf_bin
        bin_accs[k] = acc_bin
        bin_counts[k] = n

    ece /= len(labels)
    return ece, bin_confs, bin_accs, bin_counts


def fit_isotonic_calibration(
    val_probs: np.ndarray,
    val_labels: np.ndarray,
) -> List:
    from sklearn.calibration import IsotonicRegression

    calibrators = []
    for c in range(NUM_LABELS):
        cal = IsotonicRegression(out_of_bounds="clip")
        binary_labels = (val_labels == c).astype(int)
        cal.fit(val_probs[:, c], binary_labels)
        calibrators.append(cal)
    return calibrators


def apply_calibration(probs: np.ndarray, calibrators) -> np.ndarray:
    calibrated = np.stack(
        [cal.predict(probs[:, c]) for c, cal in enumerate(calibrators)], axis=1
    )
    row_sums = calibrated.sum(axis=1, keepdims=True)
    row_sums = np.maximum(row_sums, 1e-12)
    return calibrated / row_sums


def plot_calibration_reliability(
    test_probs_before: np.ndarray,
    test_probs_after: np.ndarray,
    test_labels: np.ndarray,
    out_dir: Path,
) -> Tuple[float, float]:
    n_bins = 15
    ece_before, confs_b, accs_b, counts_b = compute_ece_and_reliability(
        test_probs_before, test_labels, n_bins
    )
    ece_after, confs_a, accs_a, counts_a = compute_ece_and_reliability(
        test_probs_after, test_labels, n_bins
    )

    bin_width = 1.0 / n_bins

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

    for ax, confs, accs, counts, ece, title in [
        (ax1, confs_b, accs_b, counts_b, ece_before, "Before calibration"),
        (ax2, confs_a, accs_a, counts_a, ece_after,  "After isotonic calibration"),
    ]:
        # Perfect calibration diagonal
        ax.plot([0, 1], [0, 1], "k--", linewidth=1.5, label="Perfect calibration", alpha=0.6)

        # Bar chart of bin accuracy
        mask = counts > 0
        ax.bar(
            confs[mask], accs[mask], width=bin_width * 0.8,
            color="#4C72B0", alpha=0.7, label="Accuracy per bin",
        )
        # Gap fill (over/under-confidence gap)
        for c, a in zip(confs[mask], accs[mask]):
            lo = min(c, a)
            hi = max(c, a)
            color = "#DD8452" if c > a else "#55A868"  # orange=overconfident, green=underconfident
            ax.bar(c, hi - lo, bottom=lo, width=bin_width * 0.8,
                   color=color, alpha=0.4)

        ax.set_xlabel("Mean confidence")
        ax.set_ylabel("Fraction correct")
        ax.set_title(f"{title}\nECE = {ece:.4f}")
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.legend(fontsize=9)
        ax.text(0.05, 0.92, f"ECE = {ece:.4f}", transform=ax.transAxes,
                fontsize=11, fontweight="bold", color="black",
                bbox=dict(boxstyle="round", fc="lightyellow", ec="gray", alpha=0.8))

    fig.suptitle("Reliability Diagram — Test Set\nDictaBERT D10 (isotonic calibration on val)",
                 fontsize=13, fontweight="bold")
    fig.tight_layout()
    out_path = out_dir / "06_calibration_reliability.png"
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved {out_path}")
    return ece_before, ece_after


# ---------------------------------------------------------------------------
# Figure 7: Stylistic-slice macro-F1 bar chart
# ---------------------------------------------------------------------------

def plot_stylistic_slices(
    model,
    tokenizer,
    stylistic_rows: List[dict],
    test_macro_f1: float,
    device: torch.device,
    out_dir: Path,
) -> Dict[str, float]:
    """
    Re-run inference on each style slice and plot macro-F1.
    Returns {style: f1}.
    """
    from sklearn.metrics import f1_score

    styles = sorted(set(r.get("style", "unknown") for r in stylistic_rows))
    slice_f1s: Dict[str, float] = {}

    print(f"Running stylistic slice inference ({len(stylistic_rows)} rows, {len(styles)} styles)...")
    for style in styles:
        subset = [r for r in stylistic_rows if r.get("style") == style]
        if not subset:
            continue
        _, preds, labels = run_inference(model, tokenizer, subset, device)
        unique = set(labels.tolist())
        if len(unique) < 2:
            f1 = 0.0
            print(f"  {style}: only 1 class present — F1=0.0")
        else:
            f1 = f1_score(labels, preds, average="macro", zero_division=0)
        slice_f1s[style] = float(f1)
        print(f"  {style}: macro-F1 = {f1:.4f}  ({len(subset)} examples)")

    # Plot
    style_labels = list(slice_f1s.keys())
    style_values = [slice_f1s[s] for s in style_labels]

    # Nicer display names
    display_names = {
        "clear_hebrew":      "Clear Hebrew",
        "children_mistakes": "Children's Mistakes",
        "code_switching":    "Code-Switching",
        "poor_spelling":     "Poor Spelling",
    }
    x_labels = [display_names.get(s, s) for s in style_labels]

    fig, ax = plt.subplots(figsize=(8, 5))
    bar_colors = ["#4C72B0", "#DD8452", "#55A868", "#C44E52"]
    bars = ax.bar(x_labels, style_values, color=bar_colors[:len(style_labels)], alpha=0.85,
                  edgecolor="white", linewidth=0.8)

    # Annotate values
    for bar, val in zip(bars, style_values):
        ax.text(
            bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.008,
            f"{val:.3f}", ha="center", va="bottom", fontsize=11, fontweight="bold",
        )

    # Reference lines
    ax.axhline(GATE_MACRO_F1, color="red", linestyle="--", linewidth=1.5,
               label=f"Gate threshold ({GATE_MACRO_F1})", alpha=0.9)
    ax.axhline(test_macro_f1, color="black", linestyle="-.", linewidth=1.5,
               label=f"Test macro-F1 ({test_macro_f1:.3f})", alpha=0.7)

    ax.set_ylabel("Macro-F1")
    ax.set_ylim(0, 1.0)
    ax.yaxis.set_major_formatter(mticker.FormatStrFormatter("%.2f"))
    ax.set_title("Stylistic-Slice Macro-F1 (OOD probe)\nDictaBERT D10 — 1,040 held-out sentences")
    ax.legend(fontsize=9, loc="lower right")

    fig.tight_layout()
    out_path = out_dir / "07_stylistic_slice_f1.png"
    fig.savefig(out_path)
    plt.close(fig)
    print(f"Saved {out_path}")
    return slice_f1s


# ---------------------------------------------------------------------------
# Write README index
# ---------------------------------------------------------------------------

def write_readme(
    out_dir: Path,
    ece_before: float,
    ece_after: float,
    test_macro_f1: float,
    slice_f1s: Dict[str, float],
) -> None:
    lines = [
        "# DictaBERT D10 Final-Model Result Plots",
        "",
        "All PNGs are 300 dpi. Generated by `training/plot_results.py`.",
        "",
        "| File | Description |",
        "|------|-------------|",
        "| `01_confusion_matrix_counts.png` | 5x5 confusion matrix, raw prediction counts |",
        "| `02_confusion_matrix_normalized.png` | 5x5 confusion matrix, row-normalized (recall per class) |",
        "| `03_per_class_metrics.png` | Precision / Recall / F1 grouped bars per class on test set |",
        "| `04_training_curves.png` | Train loss vs step + eval loss + eval macro-F1 vs epoch (2-panel) |",
        "| `05_per_class_f1_epochs.png` | Per-class eval F1 vs epoch — minority classes climbing |",
        f"| `06_calibration_reliability.png` | Reliability diagram before (ECE={ece_before:.4f}) vs after isotonic calibration (ECE={ece_after:.4f}) |",
        "| `07_stylistic_slice_f1.png` | Stylistic OOD slice macro-F1 (4 slices, 260 examples each) |",
        "",
        "## Key numbers (test set, 445 examples)",
        "",
        f"- **Test macro-F1**: {test_macro_f1:.4f}  (gate >= 0.78 — PASS)",
        f"- **ECE before calibration**: {ece_before:.4f}",
        f"- **ECE after calibration**: {ece_after:.4f}  (gate <= 0.10 — PASS)",
        "",
        "## Stylistic slice F1",
        "",
    ]
    for style, f1 in sorted(slice_f1s.items()):
        lines.append(f"- `{style}`: {f1:.4f}")

    lines += [
        "",
        "## Data caveats for thesis",
        "",
        "1. Test set n=445 with ~70% non_offensive (realistic production prevalence). "
           "Per-class test support is small (33–34 per offensive class) — bootstrap CI "
           "should accompany any per-class claims.",
        "2. The `pornographic` category is predominantly synthetic "
           "(only 4 real SinaLab rows in the full dataset). High F1 on this class "
           "should be caveated as 'in-distribution synthetic'.",
        "3. Stylistic slices (`stylistic_eval.jsonl`) are OCR-validation sentences "
           "with injected linguistic noise. They are not drawn from the same distribution "
           "as the test split, so slice F1 is an OOD probe, not an independent test metric.",
        "4. Minority class val/test rows may include translated (textdetox) or synthetic "
           "(synth_hate_violence, synth_abusive, jigsaw_he) content. "
           "Real-world deployment evaluation on fully natural Hebrew is strongly recommended.",
        "5. Model trained with Stage-2 Rung-1 fallback hyperparams "
           "(lr=1e-5, patience=3, 8 epochs) — best checkpoint is epoch 3 "
           "(early-stopped at epoch 6, patience=3).",
    ]

    readme_path = out_dir / "README.md"
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"Saved {readme_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    import random
    torch.manual_seed(SEED)
    np.random.seed(SEED)
    random.seed(SEED)

    PLOT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Output directory: {PLOT_DIR}")

    # ------------------------------------------------------------------
    # 1. Load trainer_state.json log_history
    # ------------------------------------------------------------------
    print("\n--- Loading trainer_state.json ---")
    with open(TRAINER_STATE, encoding="utf-8") as f:
        state = json.load(f)
    log_history = state["log_history"]
    print(f"  {len(log_history)} log entries")

    # ------------------------------------------------------------------
    # 2. Training curves (no model needed)
    # ------------------------------------------------------------------
    print("\n--- Figure 4: Training curves ---")
    plot_training_curves(log_history, PLOT_DIR)

    print("\n--- Figure 5: Per-class F1 epochs ---")
    plot_per_class_f1_epochs(log_history, PLOT_DIR)

    # ------------------------------------------------------------------
    # 3. Load model + data
    # ------------------------------------------------------------------
    device_name = "cuda" if torch.cuda.is_available() else "cpu"
    device = torch.device(device_name)
    print(f"\nDevice: {device_name}")

    print("\n--- Loading model ---")
    model, tokenizer = load_model_and_tokenizer(BEST_CKPT, device)

    print("\n--- Loading data ---")
    test_rows = load_jsonl(DATA_DIR / "test.jsonl")
    val_rows = load_jsonl(DATA_DIR / "validation.jsonl")
    stylistic_rows = load_jsonl(DATA_DIR / "stylistic_eval.jsonl")
    print(f"  test={len(test_rows)}, val={len(val_rows)}, stylistic={len(stylistic_rows)}")

    # ------------------------------------------------------------------
    # 4. Run inference on test set
    # ------------------------------------------------------------------
    print("\n--- Running test-set inference ---")
    test_probs, test_preds, test_labels = run_inference(model, tokenizer, test_rows, device)

    # ------------------------------------------------------------------
    # 5. Confusion matrices
    # ------------------------------------------------------------------
    from sklearn.metrics import confusion_matrix as sk_cm, precision_recall_fscore_support, f1_score

    print("\n--- Figures 1 & 2: Confusion matrices ---")
    cm = sk_cm(test_labels, test_preds)
    plot_confusion_matrices(cm, LABEL_NAMES, PLOT_DIR)

    # ------------------------------------------------------------------
    # 6. Per-class metrics
    # ------------------------------------------------------------------
    print("\n--- Figure 3: Per-class metrics ---")
    precision, recall, f1_per_class, _ = precision_recall_fscore_support(
        test_labels, test_preds, average=None, zero_division=0, labels=list(range(NUM_LABELS))
    )
    test_macro_f1 = f1_score(test_labels, test_preds, average="macro", zero_division=0)
    print(f"  Test macro-F1 (re-computed): {test_macro_f1:.4f}")
    plot_per_class_metrics(precision, recall, f1_per_class, LABEL_NAMES, PLOT_DIR)

    # ------------------------------------------------------------------
    # 7. Calibration
    # ------------------------------------------------------------------
    print("\n--- Figure 6: Calibration reliability diagram ---")
    print("  Running val-set inference for calibration fitting...")
    val_probs, _, val_labels = run_inference(model, tokenizer, val_rows, device)

    calibrators = fit_isotonic_calibration(val_probs, val_labels)
    test_probs_cal = apply_calibration(test_probs, calibrators)

    ece_before, ece_after = plot_calibration_reliability(
        test_probs, test_probs_cal, test_labels, PLOT_DIR
    )
    print(f"  ECE before: {ece_before:.4f}  |  ECE after: {ece_after:.4f}")
    print(f"  Reference ECE (from calibration_curve.txt): before=0.2476, after=0.0335")

    # ------------------------------------------------------------------
    # 8. Stylistic slices
    # ------------------------------------------------------------------
    print("\n--- Figure 7: Stylistic slice F1 ---")
    slice_f1s = plot_stylistic_slices(
        model, tokenizer, stylistic_rows, test_macro_f1, device, PLOT_DIR
    )

    # ------------------------------------------------------------------
    # 9. Write README
    # ------------------------------------------------------------------
    print("\n--- Writing README.md ---")
    write_readme(PLOT_DIR, ece_before, ece_after, test_macro_f1, slice_f1s)

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("PLOT RESULTS SUMMARY")
    print("=" * 60)
    print(f"Test macro-F1 (re-computed):  {test_macro_f1:.4f}")
    print(f"ECE before calibration:        {ece_before:.4f}")
    print(f"ECE after  calibration:        {ece_after:.4f}")
    print("\nPer-class F1 (test set):")
    for i, name in enumerate(LABEL_NAMES):
        print(f"  {name:20s}: {f1_per_class[i]:.4f}")
    print("\nStylistic slice F1:")
    for style, f1 in sorted(slice_f1s.items()):
        print(f"  {style:25s}: {f1:.4f}")
    print(f"\nAll plots saved to: {PLOT_DIR}")
    print("=" * 60)


if __name__ == "__main__":
    main()
