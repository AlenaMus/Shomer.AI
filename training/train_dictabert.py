"""
train_dictabert.py — Fine-tune DictaBERT for 5-class Hebrew offensive-content detection.

Architecture: LOCKED per docs/concepts/dictabert_classifier_architecture.md
  Backbone:   dicta-il/dictabert (fully fine-tuned, BF16)
  Head:       [CLS] -> Dropout(0.1) -> Linear(768->256) -> GELU -> Dropout(0.1) -> Linear(256->5)
  Loss:       Focal Loss (gamma=2.0, alpha=class_weights) + label_smoothing=0.05 (C4 from data techniques §11)
  Optimizer:  AdamW (lr=2e-5, beta=(0.9,0.999), weight_decay=0.01)
  Schedule:   Cosine warmup_ratio=0.1
  Batch:      32, epochs=5, BF16, seed=42
  max_length: 96 (B1 from data techniques §11 p99.5 analysis — overrides arch doc §8.1 estimate of 128)

Data: data/train.jsonl (11,434) · data/validation.jsonl (1,127) · data/test.jsonl (1,127)
      data/class_weights.json · data/stylistic_eval.jsonl (1,040 held-out)

Outputs: training/outputs/dictabert-offensive/
  checkpoint-best/        <- best val macro-F1 checkpoint (model + tokenizer)
  training_log.jsonl      <- per-epoch metrics
  metadata.json           <- hyperparams + label order + final metrics
  eval_report.txt         <- test set evaluation + gate verdict
  confusion_matrix.txt    <- 5x5 confusion matrix
  calibration_curve.txt   <- ECE before/after isotonic calibration
  stylistic_eval_report.txt <- per-style macro-F1

Run from WSL2:
  source ~/shomer-training-venv/bin/activate
  cd /mnt/c/AIDevelopmentCourse/Shomer.AI
  python training/train_dictabert.py
"""

import json
import logging
import math
import os
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from datasets import Dataset, load_dataset
from sklearn.calibration import IsotonicRegression
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
)
from torch.optim import AdamW
from transformers import (
    AutoConfig,
    AutoModelForSequenceClassification,
    AutoTokenizer,
    BertConfig,
    BertModel,
    BertPreTrainedModel,
    EarlyStoppingCallback,
    Trainer,
    TrainingArguments,
    set_seed,
)
from transformers.modeling_outputs import SequenceClassifierOutput

# ---------------------------------------------------------------------------
# Constants (locked — do NOT change without updating the arch doc)
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).parent.parent
DATA_DIR = REPO_ROOT / "data"
OUTPUT_DIR = REPO_ROOT / "training" / "outputs" / "dictabert-offensive"

BASE_MODEL = "dicta-il/dictabert"
LABEL_NAMES = ["non_offensive", "abusive", "hate", "violence", "pornographic"]
LABEL2ID = {"non_offensive": 0, "abusive": 1, "hate": 2, "violence": 3, "pornographic": 4}
ID2LABEL = {v: k for k, v in LABEL2ID.items()}
NUM_LABELS = 5

# Locked hyperparameters (arch §8.1 + data techniques §11)
MAX_LENGTH = 96          # B1: p99.5 of token counts on actual SinaLab data
BATCH_SIZE = 32
NUM_EPOCHS = 8           # Stage-2 Rung-1 fallback: 5→8 to allow cosine tail exploration
LR = 1e-5                # Stage-2 Rung-1 fallback: 2e-5→1e-5 (D7 decision — val/test gap narrowing)
WARMUP_RATIO = 0.1
WEIGHT_DECAY = 0.01
FOCAL_GAMMA = 2.0
LABEL_SMOOTHING = 0.05   # C4 from data techniques §11
SEED = 42
EARLY_STOPPING_PATIENCE = 3  # Stage-2 Rung-1: 2→3 (gives model more time past epoch-2 peak)

# Ship gate criteria (arch §10.2 + eval prompt)
GATE_MACRO_F1 = 0.78
GATE_RECALL_VIOLENCE = 0.50
GATE_PRECISION_NON_OFFENSIVE = 0.75

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Model: DictaBERT with 2-layer MLP head (Option B, arch §5)
# [CLS] -> Dropout(0.1) -> Linear(768->256) -> GELU -> Dropout(0.1) -> Linear(256->5)
# ---------------------------------------------------------------------------

class DictaBertMlpConfig(BertConfig):
    """BertConfig extended with MLP head dimensions."""
    model_type = "dictabert_mlp"

    def __init__(self, classifier_hidden_dim: int = 256, classifier_dropout: float = 0.1, **kwargs):
        super().__init__(**kwargs)
        self.classifier_hidden_dim = classifier_hidden_dim
        self.classifier_dropout = classifier_dropout


class DictaBertWithMlpHead(BertPreTrainedModel):
    """
    DictaBERT backbone + 2-layer MLP classification head.

    Architecture per docs/concepts/dictabert_classifier_architecture.md §5:
      pooled_output (768)
        -> Dropout(0.1)
        -> Linear(768, 256)
        -> GELU
        -> Dropout(0.1)
        -> Linear(256, num_labels)
        -> logits
    """

    config_class = DictaBertMlpConfig

    def __init__(self, config: DictaBertMlpConfig):
        super().__init__(config)
        self.num_labels = config.num_labels
        self.bert = BertModel(config)

        hidden_dim = getattr(config, "classifier_hidden_dim", 256)
        drop_p = getattr(config, "classifier_dropout", 0.1)

        self.pre_dropout = nn.Dropout(drop_p)
        self.fc1 = nn.Linear(config.hidden_size, hidden_dim)
        self.act = nn.GELU()
        self.mid_dropout = nn.Dropout(drop_p)
        self.fc2 = nn.Linear(hidden_dim, config.num_labels)

        self.post_init()

    def forward(
        self,
        input_ids=None,
        attention_mask=None,
        token_type_ids=None,
        position_ids=None,
        head_mask=None,
        inputs_embeds=None,
        labels=None,
        output_attentions=None,
        output_hidden_states=None,
        return_dict=None,
    ) -> SequenceClassifierOutput:
        return_dict = return_dict if return_dict is not None else self.config.use_return_dict

        outputs = self.bert(
            input_ids=input_ids,
            attention_mask=attention_mask,
            token_type_ids=token_type_ids,
            position_ids=position_ids,
            head_mask=head_mask,
            inputs_embeds=inputs_embeds,
            output_attentions=output_attentions,
            output_hidden_states=output_hidden_states,
            return_dict=return_dict,
        )

        # pooled_output is [CLS] after Linear(768->768) + tanh (BERT pooler)
        pooled_output = outputs[1]  # shape (B, 768)

        # MLP head
        x = self.pre_dropout(pooled_output)
        x = self.fc1(x)
        x = self.act(x)
        x = self.mid_dropout(x)
        logits = self.fc2(x)  # shape (B, num_labels)

        loss = None
        if labels is not None:
            # Loss is computed in FocalTrainer.compute_loss — this branch
            # is reached only when the trainer delegates to the model itself.
            loss = F.cross_entropy(logits, labels)

        return SequenceClassifierOutput(
            loss=loss,
            logits=logits,
            hidden_states=outputs.hidden_states if output_hidden_states else None,
            attentions=outputs.attentions if output_attentions else None,
        )


# ---------------------------------------------------------------------------
# Focal Loss with class weights + label smoothing (arch §7.3 + data techs C2+C4)
# ---------------------------------------------------------------------------

class FocalLoss(nn.Module):
    """
    Focal Loss: FL = -alpha_t * (1 - p_t)^gamma * log(p_t)

    With label smoothing C4 (epsilon=0.05): soft targets instead of one-hot.

    Unit test parity:
      gamma=0, alpha=uniform, epsilon=0 → equivalent to cross_entropy (within 1e-5)
    """

    def __init__(
        self,
        alpha: torch.Tensor,
        gamma: float = 2.0,
        label_smoothing: float = 0.0,
        num_classes: int = 5,
    ):
        super().__init__()
        self.register_buffer("alpha", alpha)
        self.gamma = gamma
        self.label_smoothing = label_smoothing
        self.num_classes = num_classes

    def forward(self, logits: torch.Tensor, targets: torch.Tensor) -> torch.Tensor:
        """
        Args:
            logits: (B, C) raw unnormalized scores
            targets: (B,) integer class indices
        Returns:
            scalar loss
        """
        B, C = logits.shape

        # Compute log-softmax and softmax
        log_probs = F.log_softmax(logits, dim=-1)   # (B, C)
        probs = log_probs.exp()                      # (B, C)

        # p_t: probability of the true class
        p_t = probs.gather(dim=1, index=targets.unsqueeze(1)).squeeze(1)  # (B,)

        # Focal term: (1 - p_t)^gamma
        focal_term = (1.0 - p_t).pow(self.gamma)                         # (B,)

        # Alpha per sample: class weight of the true class
        alpha_t = self.alpha[targets]                                     # (B,)

        if self.label_smoothing > 0.0:
            # Label-smoothed log probability for true class
            # Formula: (1-eps)*log(p_t) + eps/C * sum_all(log(p_j))
            # = (1-eps)*log_p_t + eps * mean_log (scaled)
            eps = self.label_smoothing
            log_p_t = log_probs.gather(dim=1, index=targets.unsqueeze(1)).squeeze(1)  # (B,)
            mean_log_p = log_probs.mean(dim=-1)                          # (B,)
            smooth_log = (1.0 - eps) * log_p_t + eps * mean_log_p       # (B,)
            loss = -alpha_t * focal_term * smooth_log                    # (B,)
        else:
            log_p_t = log_probs.gather(dim=1, index=targets.unsqueeze(1)).squeeze(1)  # (B,)
            loss = -alpha_t * focal_term * log_p_t                       # (B,)

        return loss.mean()


def unit_test_focal_loss():
    """
    Verify: gamma=0, alpha=uniform, epsilon=0 matches torch cross_entropy within 1e-5.
    Runs before training — if it fails, the loss implementation is broken.
    """
    torch.manual_seed(0)
    B, C = 16, 5
    logits = torch.randn(B, C)
    targets = torch.randint(0, C, (B,))
    alpha_uniform = torch.ones(C) / C * C  # uniform weights = 1.0 per class

    focal = FocalLoss(alpha=alpha_uniform, gamma=0.0, label_smoothing=0.0, num_classes=C)
    focal_loss_val = focal(logits, targets)
    ce_val = F.cross_entropy(logits, targets)

    diff = (focal_loss_val - ce_val).abs().item()
    assert diff < 1e-5, (
        f"FocalLoss unit test FAILED: focal={focal_loss_val:.6f}, ce={ce_val:.6f}, diff={diff:.2e}"
    )
    logger.info(f"FocalLoss unit test PASSED (diff={diff:.2e})")


# ---------------------------------------------------------------------------
# Custom Trainer with Focal Loss
# ---------------------------------------------------------------------------

class FocalTrainer(Trainer):
    """Trainer subclass that injects Focal Loss in place of the model's own loss."""

    def __init__(self, *args, focal_loss_fn: FocalLoss, **kwargs):
        super().__init__(*args, **kwargs)
        self.focal_loss_fn = focal_loss_fn

    def compute_loss(self, model, inputs, return_outputs=False, **kwargs):
        labels = inputs.pop("labels")
        outputs = model(**inputs)
        logits = outputs.logits
        loss = self.focal_loss_fn(logits, labels)
        return (loss, outputs) if return_outputs else loss


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def compute_metrics(eval_pred):
    logits, labels = eval_pred
    preds = np.argmax(logits, axis=-1)

    macro_f1 = f1_score(labels, preds, average="macro", zero_division=0)
    weighted_f1 = f1_score(labels, preds, average="weighted", zero_division=0)
    acc = accuracy_score(labels, preds)
    per_class_f1 = f1_score(labels, preds, average=None, zero_division=0)

    result = {
        "eval_macro_f1": float(macro_f1),
        "eval_weighted_f1": float(weighted_f1),
        "eval_accuracy": float(acc),
    }
    for name, val in zip(LABEL_NAMES, per_class_f1):
        result[f"eval_f1_{name}"] = float(val)

    return result


# ---------------------------------------------------------------------------
# Data loading and tokenization
# ---------------------------------------------------------------------------

def load_jsonl(path: Path) -> List[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def build_hf_dataset(rows: List[dict], tokenizer, max_length: int) -> Dataset:
    """Tokenize text and return a HuggingFace Dataset with input_ids, attention_mask, labels."""
    texts = [r["text"] for r in rows]
    labels = [r["label_id"] for r in rows]

    encodings = tokenizer(
        texts,
        truncation=True,
        max_length=max_length,
        padding="max_length",
        return_tensors=None,   # keep as lists for Dataset
    )

    dataset = Dataset.from_dict({
        "input_ids": encodings["input_ids"],
        "attention_mask": encodings["attention_mask"],
        "labels": labels,
    })
    dataset.set_format("torch")
    return dataset


# ---------------------------------------------------------------------------
# Isotonic calibration
# ---------------------------------------------------------------------------

def calibrate_and_evaluate(
    model: DictaBertWithMlpHead,
    tokenizer,
    val_rows: List[dict],
    test_rows: List[dict],
    device: torch.device,
    output_dir: Path,
) -> Dict:
    """
    1. Collect val logits/probs.
    2. Fit IsotonicRegression calibrator per class on val.
    3. Evaluate ECE (approximate) before and after calibration on test.
    Returns dict of calibration metrics.
    """
    logger.info("Running calibration...")

    def collect_probs(rows):
        model.eval()
        all_probs = []
        all_labels = []
        with torch.no_grad():
            for i in range(0, len(rows), 64):
                batch_rows = rows[i:i+64]
                texts = [r["text"] for r in batch_rows]
                labels = [r["label_id"] for r in batch_rows]
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
                all_labels.extend(labels)
        return np.concatenate(all_probs, axis=0), np.array(all_labels)

    val_probs, val_labels = collect_probs(val_rows)
    test_probs, test_labels = collect_probs(test_rows)

    # ECE (15-bin) — approximate via reliability diagram bucketing
    def compute_ece(probs, labels, n_bins=15):
        max_probs = probs.max(axis=1)
        preds = probs.argmax(axis=1)
        correct = (preds == labels).astype(float)
        bins = np.linspace(0, 1, n_bins + 1)
        ece = 0.0
        for lo, hi in zip(bins[:-1], bins[1:]):
            mask = (max_probs > lo) & (max_probs <= hi)
            if mask.sum() == 0:
                continue
            acc_bin = correct[mask].mean()
            conf_bin = max_probs[mask].mean()
            ece += mask.sum() * abs(acc_bin - conf_bin)
        return ece / len(labels)

    ece_before = compute_ece(test_probs, test_labels)

    # Fit isotonic calibrator on val (one per class, Platt/isotonic on class probs)
    calibrators = []
    for c in range(NUM_LABELS):
        cal = IsotonicRegression(out_of_bounds="clip")
        binary_labels = (val_labels == c).astype(int)
        cal.fit(val_probs[:, c], binary_labels)
        calibrators.append(cal)

    def apply_calibration(probs):
        calibrated = np.stack(
            [cal.predict(probs[:, c]) for c, cal in enumerate(calibrators)], axis=1
        )
        # Renormalize rows
        row_sums = calibrated.sum(axis=1, keepdims=True)
        row_sums = np.maximum(row_sums, 1e-12)
        return calibrated / row_sums

    test_probs_cal = apply_calibration(test_probs)
    ece_after = compute_ece(test_probs_cal, test_labels)

    logger.info(f"ECE before calibration: {ece_before:.4f}")
    logger.info(f"ECE after  calibration: {ece_after:.4f}")

    calib_report = (
        f"Isotonic Calibration Report\n"
        f"===========================\n"
        f"ECE before calibration (15-bin): {ece_before:.4f}\n"
        f"ECE after  calibration (15-bin): {ece_after:.4f}\n"
        f"\nGate: ECE <= 0.10 (arch §10.4)\n"
        f"ECE after gate: {'PASS' if ece_after <= 0.10 else 'FAIL (above 0.10)'}\n"
    )

    with open(output_dir / "calibration_curve.txt", "w", encoding="utf-8") as f:
        f.write(calib_report)

    return {
        "ece_before": float(ece_before),
        "ece_after": float(ece_after),
    }


# ---------------------------------------------------------------------------
# Full evaluation on test + stylistic eval
# ---------------------------------------------------------------------------

def run_evaluation(
    model: DictaBertWithMlpHead,
    tokenizer,
    test_rows: List[dict],
    stylistic_rows: List[dict],
    output_dir: Path,
    device: torch.device,
) -> Dict:
    """
    Evaluate on test split and stylistic_eval.
    Prints and saves: macro-F1, per-class table, confusion matrix, ship gate verdict.
    """
    logger.info("Running test set evaluation...")

    model.eval()
    all_preds = []
    all_labels = []
    all_logits = []

    with torch.no_grad():
        for i in range(0, len(test_rows), 64):
            batch = test_rows[i:i+64]
            texts = [r["text"] for r in batch]
            labels = [r["label_id"] for r in batch]
            enc = tokenizer(
                texts,
                truncation=True,
                max_length=MAX_LENGTH,
                padding="max_length",
                return_tensors="pt",
            )
            enc = {k: v.to(device) for k, v in enc.items()}
            out = model(**enc)
            logits = out.logits.float().cpu().numpy()
            preds = logits.argmax(axis=-1)
            all_preds.extend(preds.tolist())
            all_labels.extend(labels)
            all_logits.append(logits)

    all_labels = np.array(all_labels)
    all_preds = np.array(all_preds)
    all_logits = np.concatenate(all_logits, axis=0)

    macro_f1 = f1_score(all_labels, all_preds, average="macro", zero_division=0)
    per_class_f1 = f1_score(all_labels, all_preds, average=None, zero_division=0)
    report = classification_report(
        all_labels, all_preds, target_names=LABEL_NAMES, digits=4, zero_division=0
    )
    cm = confusion_matrix(all_labels, all_preds)

    # Per-class recall and precision for gate checks
    from sklearn.metrics import precision_recall_fscore_support
    precision, recall, _, _ = precision_recall_fscore_support(
        all_labels, all_preds, average=None, zero_division=0
    )
    recall_violence = recall[LABEL2ID["violence"]]
    precision_non_offensive = precision[LABEL2ID["non_offensive"]]

    # Ship gate verdict
    gate_pass = (
        macro_f1 >= GATE_MACRO_F1
        and recall_violence >= GATE_RECALL_VIOLENCE
        and precision_non_offensive >= GATE_PRECISION_NON_OFFENSIVE
    )

    gate_lines = [
        "\n" + "=" * 60,
        "SHIP GATE VERDICT",
        "=" * 60,
        f"macro-F1 >= {GATE_MACRO_F1}:              {macro_f1:.4f}  -> {'PASS' if macro_f1 >= GATE_MACRO_F1 else 'FAIL'}",
        f"recall[violence] >= {GATE_RECALL_VIOLENCE}:        {recall_violence:.4f}  -> {'PASS' if recall_violence >= GATE_RECALL_VIOLENCE else 'FAIL'}",
        f"precision[non_offensive] >= {GATE_PRECISION_NON_OFFENSIVE}: {precision_non_offensive:.4f}  -> {'PASS' if precision_non_offensive >= GATE_PRECISION_NON_OFFENSIVE else 'FAIL'}",
        "",
        f"OVERALL GATE: {'*** PASS ***' if gate_pass else '*** FAIL ***'}",
        "=" * 60,
    ]

    # Confusion matrix formatted
    cm_lines = ["\nConfusion Matrix (rows=true, cols=pred):"]
    header = "{:>20s}".format("") + "".join(f"{n:>16s}" for n in LABEL_NAMES)
    cm_lines.append(header)
    for i, row_name in enumerate(LABEL_NAMES):
        row_str = f"{row_name:>20s}" + "".join(f"{cm[i,j]:>16d}" for j in range(NUM_LABELS))
        cm_lines.append(row_str)

    # Stylistic eval
    style_lines = ["\nStylistic Eval (per-style macro-F1 on 1,040 held-out sentences):"]
    style_f1s = {}
    if stylistic_rows:
        styles = sorted(set(r.get("style", "unknown") for r in stylistic_rows))
        for style in styles:
            style_subset = [r for r in stylistic_rows if r.get("style") == style]
            if not style_subset:
                continue
            s_preds = []
            s_labels = []
            with torch.no_grad():
                for i in range(0, len(style_subset), 64):
                    batch = style_subset[i:i+64]
                    texts = [r["text"] for r in batch]
                    labels_s = [r["label_id"] for r in batch]
                    enc = tokenizer(
                        texts,
                        truncation=True,
                        max_length=MAX_LENGTH,
                        padding="max_length",
                        return_tensors="pt",
                    )
                    enc = {k: v.to(device) for k, v in enc.items()}
                    out = model(**enc)
                    preds_s = out.logits.float().argmax(dim=-1).cpu().numpy()
                    s_preds.extend(preds_s.tolist())
                    s_labels.extend(labels_s)
            # NOTE: stylistic_eval is a linguistic-style probe set (OCR validation sentences).
            # It does NOT contain all 5 offensive categories (most are non_offensive + some labelled).
            # We compute macro-F1 with zero_division=0 and warn if fewer than 2 unique labels.
            unique_labels = set(s_labels)
            if len(unique_labels) < 2:
                sf1 = 0.0
                style_lines.append(f"  {style:25s}: N/A (only 1 class present in slice, {len(style_subset)} examples)")
            else:
                sf1 = f1_score(s_labels, s_preds, average="macro", zero_division=0)
                style_lines.append(
                    f"  {style:25s}: macro-F1 = {sf1:.4f}  ({len(style_subset)} examples)"
                )
            style_f1s[style] = sf1

    # Assemble full report
    full_report = "\n".join([
        "DictaBERT 5-class Hebrew Offensive Content Classifier",
        "Test Set Evaluation Report",
        "=" * 60,
        f"Test examples: {len(test_rows)}",
        f"Test macro-F1: {macro_f1:.4f}",
        "",
        "Per-class classification report:",
        report,
        *cm_lines,
        *style_lines,
        *gate_lines,
    ])

    print(full_report)

    with open(output_dir / "eval_report.txt", "w", encoding="utf-8") as f:
        f.write(full_report)

    with open(output_dir / "confusion_matrix.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(cm_lines))

    if style_lines:
        with open(output_dir / "stylistic_eval_report.txt", "w", encoding="utf-8") as f:
            f.write("\n".join(style_lines))

    return {
        "test_macro_f1": float(macro_f1),
        "test_per_class_f1": {name: float(v) for name, v in zip(LABEL_NAMES, per_class_f1)},
        "test_recall_violence": float(recall_violence),
        "test_precision_non_offensive": float(precision_non_offensive),
        "gate_pass": gate_pass,
        "stylistic_f1": style_f1s,
    }


# ---------------------------------------------------------------------------
# Main training entry point
# ---------------------------------------------------------------------------

def main():
    t_start = time.time()
    set_seed(SEED)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    best_ckpt_dir = OUTPUT_DIR / "checkpoint-best"

    logger.info("=" * 60)
    logger.info("DictaBERT Fine-tuning — Shomer.AI Hebrew Offensive Classifier")
    logger.info("=" * 60)
    logger.info(f"Data dir:   {DATA_DIR}")
    logger.info(f"Output dir: {OUTPUT_DIR}")

    # ------------------------------------------------------------------
    # 1. Unit test: FocalLoss correctness before training
    # ------------------------------------------------------------------
    unit_test_focal_loss()

    # ------------------------------------------------------------------
    # 2. GPU / device
    # ------------------------------------------------------------------
    if not torch.cuda.is_available():
        logger.error("CUDA not available — check training environment (WSL2 + cu128 venv)")
        sys.exit(1)
    device = torch.device("cuda")
    gpu_name = torch.cuda.get_device_name(0)
    logger.info(f"GPU: {gpu_name}")
    logger.info(f"torch: {torch.__version__}")

    # ------------------------------------------------------------------
    # 3. Load class weights
    # ------------------------------------------------------------------
    weights_path = DATA_DIR / "class_weights.json"
    with open(weights_path, encoding="utf-8") as f:
        weights_data = json.load(f)

    # Validate label order matches our canonical order
    assert weights_data["label_order"] == LABEL_NAMES, (
        f"class_weights.json label_order mismatch: {weights_data['label_order']} != {LABEL_NAMES}"
    )
    class_weights = torch.tensor(weights_data["weights"], dtype=torch.float32).to(device)
    logger.info(f"Class weights: {dict(zip(LABEL_NAMES, weights_data['weights']))}")
    logger.info(f"Class counts in train: {dict(zip(LABEL_NAMES, weights_data['counts']))}")

    # ------------------------------------------------------------------
    # 4. Load data
    # ------------------------------------------------------------------
    logger.info("Loading data...")
    train_rows = load_jsonl(DATA_DIR / "train.jsonl")
    val_rows = load_jsonl(DATA_DIR / "validation.jsonl")
    test_rows = load_jsonl(DATA_DIR / "test.jsonl")
    stylistic_rows = load_jsonl(DATA_DIR / "stylistic_eval.jsonl")

    logger.info(f"Train:         {len(train_rows):,} examples")
    logger.info(f"Validation:    {len(val_rows):,} examples")
    logger.info(f"Test:          {len(test_rows):,} examples")
    logger.info(f"Stylistic:     {len(stylistic_rows):,} examples (held-out)")

    # ------------------------------------------------------------------
    # 5. Load tokenizer
    # ------------------------------------------------------------------
    logger.info(f"Loading tokenizer from {BASE_MODEL}...")
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)

    # ------------------------------------------------------------------
    # 6. Tokenize datasets
    # ------------------------------------------------------------------
    logger.info(f"Tokenizing with max_length={MAX_LENGTH}...")
    train_dataset = build_hf_dataset(train_rows, tokenizer, MAX_LENGTH)
    val_dataset = build_hf_dataset(val_rows, tokenizer, MAX_LENGTH)

    # ------------------------------------------------------------------
    # 7. Load model
    # ------------------------------------------------------------------
    logger.info(f"Loading model from {BASE_MODEL}...")

    base_config = AutoConfig.from_pretrained(BASE_MODEL)
    base_dict = base_config.to_dict()
    # Remove fields we set explicitly to avoid "multiple values for keyword argument" errors.
    # BertConfig already contains 'classifier_dropout'; DictaBertMlpConfig defines its own.
    base_dict.pop("classifier_dropout", None)
    base_dict.pop("classifier_hidden_dim", None)
    base_dict.pop("model_type", None)  # we set this via the class

    config = DictaBertMlpConfig(
        classifier_hidden_dim=256,
        classifier_dropout=0.1,
        **base_dict,
    )
    config.num_labels = NUM_LABELS
    config.id2label = ID2LABEL
    config.label2id = LABEL2ID

    model = DictaBertWithMlpHead.from_pretrained(
        BASE_MODEL,
        config=config,
        ignore_mismatched_sizes=True,
    )
    model = model.to(device)

    # Log param count
    total_params = sum(p.numel() for p in model.parameters())
    trainable_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    logger.info(f"Total parameters:     {total_params:,} ({total_params/1e6:.1f}M)")
    logger.info(f"Trainable parameters: {trainable_params:,}")

    # ------------------------------------------------------------------
    # 8. Build Focal Loss
    # ------------------------------------------------------------------
    focal_loss_fn = FocalLoss(
        alpha=class_weights,
        gamma=FOCAL_GAMMA,
        label_smoothing=LABEL_SMOOTHING,
        num_classes=NUM_LABELS,
    )
    logger.info(f"Focal Loss: gamma={FOCAL_GAMMA}, label_smoothing={LABEL_SMOOTHING}")

    # ------------------------------------------------------------------
    # 9. Training arguments (locked per arch §8.1)
    # ------------------------------------------------------------------
    training_args = TrainingArguments(
        output_dir=str(OUTPUT_DIR / "hf_trainer"),
        num_train_epochs=NUM_EPOCHS,
        learning_rate=LR,
        per_device_train_batch_size=BATCH_SIZE,
        per_device_eval_batch_size=64,
        warmup_ratio=WARMUP_RATIO,
        weight_decay=WEIGHT_DECAY,
        lr_scheduler_type="cosine",
        bf16=True,
        fp16=False,
        eval_strategy="epoch",
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="eval_macro_f1",
        greater_is_better=True,
        save_total_limit=3,
        seed=SEED,
        data_seed=SEED,
        report_to=["none"],    # tensorboard not installed in venv; metrics are in training_log.jsonl
        logging_dir=str(OUTPUT_DIR / "logs"),
        logging_steps=50,
        dataloader_pin_memory=True,
        dataloader_num_workers=0,    # WSL2 multiprocessing is unreliable
    )

    # ------------------------------------------------------------------
    # 10. Train
    # ------------------------------------------------------------------
    logger.info("Starting training...")
    logger.info(f"Hyperparameters: lr={LR}, batch={BATCH_SIZE}, epochs={NUM_EPOCHS}, "
                f"warmup_ratio={WARMUP_RATIO}, weight_decay={WEIGHT_DECAY}, "
                f"max_length={MAX_LENGTH}, BF16=True, seed={SEED}, "
                f"early_stopping_patience={EARLY_STOPPING_PATIENCE} [Stage-2 Rung-1 D7]")

    training_log = []

    class EpochLogCallback:
        """Collect per-epoch metrics into training_log."""
        def on_evaluate(self, args, state, control, metrics=None, **kwargs):
            if metrics:
                entry = {"epoch": state.epoch, **metrics}
                training_log.append(entry)
                logger.info(
                    f"Epoch {state.epoch:.0f} | "
                    f"macro_f1={metrics.get('eval_macro_f1', 0):.4f} | "
                    f"f1_hate={metrics.get('eval_f1_hate', 0):.4f} | "
                    f"f1_violence={metrics.get('eval_f1_violence', 0):.4f} | "
                    f"f1_porn={metrics.get('eval_f1_pornographic', 0):.4f}"
                )

    from transformers import TrainerCallback
    class MetricsLoggerCallback(TrainerCallback):
        def on_evaluate(self, args, state, control, metrics=None, **kwargs):
            if metrics:
                entry = {"epoch": state.epoch, **{k: v for k, v in metrics.items()}}
                training_log.append(entry)
                logger.info(
                    f"Epoch {state.epoch:.1f} | "
                    f"macro_f1={metrics.get('eval_macro_f1', 0):.4f} | "
                    f"f1_violence={metrics.get('eval_f1_violence', 0):.4f} | "
                    f"f1_hate={metrics.get('eval_f1_hate', 0):.4f} | "
                    f"f1_abusive={metrics.get('eval_f1_abusive', 0):.4f} | "
                    f"f1_porn={metrics.get('eval_f1_pornographic', 0):.4f}"
                )

    # In transformers 5.x the 'tokenizer' arg was renamed to 'processing_class'.
    # Use processing_class if available, fall back to tokenizer for older versions.
    import inspect as _inspect
    _trainer_sig = _inspect.signature(Trainer.__init__)
    _tokenizer_kwarg = "processing_class" if "processing_class" in _trainer_sig.parameters else "tokenizer"

    trainer = FocalTrainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=val_dataset,
        **{_tokenizer_kwarg: tokenizer},
        compute_metrics=compute_metrics,
        focal_loss_fn=focal_loss_fn,
        callbacks=[
            EarlyStoppingCallback(early_stopping_patience=EARLY_STOPPING_PATIENCE),
            MetricsLoggerCallback(),
        ],
    )

    trainer.train()

    # ------------------------------------------------------------------
    # 11. Save best checkpoint (the one loaded at end from load_best_model_at_end=True)
    # ------------------------------------------------------------------
    best_ckpt_dir.mkdir(parents=True, exist_ok=True)
    trainer.save_model(str(best_ckpt_dir))
    tokenizer.save_pretrained(str(best_ckpt_dir))
    logger.info(f"Best model saved to {best_ckpt_dir}")

    # Save training log
    with open(OUTPUT_DIR / "training_log.jsonl", "w", encoding="utf-8") as f:
        for entry in training_log:
            f.write(json.dumps(entry) + "\n")

    # ------------------------------------------------------------------
    # 12. Evaluate on test set
    # ------------------------------------------------------------------
    eval_metrics = run_evaluation(
        model=model,
        tokenizer=tokenizer,
        test_rows=test_rows,
        stylistic_rows=stylistic_rows,
        output_dir=OUTPUT_DIR,
        device=device,
    )

    # ------------------------------------------------------------------
    # 13. Calibration
    # ------------------------------------------------------------------
    calib_metrics = calibrate_and_evaluate(
        model=model,
        tokenizer=tokenizer,
        val_rows=val_rows,
        test_rows=test_rows,
        output_dir=OUTPUT_DIR,
        device=device,
    )

    # ------------------------------------------------------------------
    # 14. Save metadata.json
    # ------------------------------------------------------------------
    t_end = time.time()
    elapsed_min = (t_end - t_start) / 60

    metadata = {
        "model": BASE_MODEL,
        "num_labels": NUM_LABELS,
        "label_order": LABEL_NAMES,
        "label2id": LABEL2ID,
        "id2label": {str(k): v for k, v in ID2LABEL.items()},
        "hyperparameters": {
            "max_length": MAX_LENGTH,
            "batch_size": BATCH_SIZE,
            "num_epochs": NUM_EPOCHS,
            "learning_rate": LR,
            "warmup_ratio": WARMUP_RATIO,
            "weight_decay": WEIGHT_DECAY,
            "focal_gamma": FOCAL_GAMMA,
            "label_smoothing": LABEL_SMOOTHING,
            "seed": SEED,
            "precision": "BF16",
            "lr_scheduler": "cosine",
            "early_stopping_patience": EARLY_STOPPING_PATIENCE,
        },
        "dataset": {
            "train_size": len(train_rows),
            "val_size": len(val_rows),
            "test_size": len(test_rows),
            "stylistic_eval_size": len(stylistic_rows),
            "class_weights": dict(zip(LABEL_NAMES, weights_data["weights"])),
        },
        "gpu": gpu_name,
        "torch_version": torch.__version__,
        "training_minutes": round(elapsed_min, 1),
        "test_metrics": json.loads(json.dumps(eval_metrics, default=lambda x: float(x) if hasattr(x, "__float__") else bool(x))),
        "calibration_metrics": calib_metrics,
        "ship_gate": {
            "criteria": {
                "macro_f1_threshold": GATE_MACRO_F1,
                "recall_violence_threshold": GATE_RECALL_VIOLENCE,
                "precision_non_offensive_threshold": GATE_PRECISION_NON_OFFENSIVE,
            },
            "result": "PASS" if eval_metrics["gate_pass"] else "FAIL",
        },
        "checkpoint_path": str(best_ckpt_dir),
    }

    with open(OUTPUT_DIR / "metadata.json", "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

    with open(best_ckpt_dir / "metadata.json", "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

    # ------------------------------------------------------------------
    # 15. Final summary
    # ------------------------------------------------------------------
    logger.info("=" * 60)
    logger.info("TRAINING COMPLETE")
    logger.info(f"Total time:       {elapsed_min:.1f} minutes")
    logger.info(f"Test macro-F1:    {eval_metrics['test_macro_f1']:.4f}")
    logger.info(f"Recall violence:  {eval_metrics['test_recall_violence']:.4f}")
    logger.info(f"Prec non_off:     {eval_metrics['test_precision_non_offensive']:.4f}")
    logger.info(f"ECE before calib: {calib_metrics['ece_before']:.4f}")
    logger.info(f"ECE after  calib: {calib_metrics['ece_after']:.4f}")
    logger.info(f"Ship gate:        {'PASS' if eval_metrics['gate_pass'] else 'FAIL'}")
    logger.info(f"Checkpoint:       {best_ckpt_dir}")
    logger.info("=" * 60)

    if not eval_metrics["gate_pass"]:
        logger.warning(
            "GATE FAILED — do NOT flip CLASSIFIER_MODEL_VERSION. "
            "Invoke ml-iteration-coach to determine the next fallback rung."
        )
        sys.exit(2)  # non-zero exit so CI knows the gate failed


if __name__ == "__main__":
    main()
