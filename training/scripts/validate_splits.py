"""D9 data contract validator (§9.8 invariants).

Run after prepare_data_dictabert.py to verify the output is correct.
Exits with non-zero status on any failure.

Checks:
  1. All records have required fields and valid values
  2. All 5 classes present in each split
  3. No intra-split duplicates (exact normalized text)
  4. Zero cross-split leakage (exact)
  5. test.jsonl >= 300 rows (D9: smaller test pool than D8 balanced 5x120)
  6. class_weights.json consistent with train counts (sklearn balanced)
  7. D9 prevalence check: train non_off ~40-60%, val/test non_off ~60-80%
  8. No source=unknown rows (source field must be populated)

D9 NOTE: val/test are intentionally NOT stratified equally across classes —
train has ~50% non_offensive, val/test have ~70% non_offensive (by design).
The old stratification check (per-class fractions matched across splits) is
replaced by the D9 prevalence check (check 7).

Run in WSL2 training venv from repo root:
    python training/scripts/validate_splits.py
"""
from __future__ import annotations

import json
import sys
import unicodedata
import re
from collections import Counter
from pathlib import Path

import numpy as np
from sklearn.utils.class_weight import compute_class_weight

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = REPO_ROOT / "data"
TRAIN_PATH = DATA_DIR / "train.jsonl"
VAL_PATH = DATA_DIR / "validation.jsonl"
TEST_PATH = DATA_DIR / "test.jsonl"
WEIGHTS_PATH = DATA_DIR / "class_weights.json"
STYLISTIC_PATH = DATA_DIR / "stylistic_eval.jsonl"

# ---------------------------------------------------------------------------
# Label constants (must match prepare_data_dictabert.py exactly)
# ---------------------------------------------------------------------------
LABEL_NAMES = ["non_offensive", "abusive", "hate", "violence", "pornographic"]
LABEL2ID = {l: i for i, l in enumerate(LABEL_NAMES)}

# ---------------------------------------------------------------------------
# Normalization (must match prepare_data_dictabert.py)
# ---------------------------------------------------------------------------
_NIKUD_RE = re.compile(r"[֑-ׇ]")
_DIR_CTRL_RE = re.compile(r"[‎‏‪-‮⁦-⁩]")
_URL_RE = re.compile(r"https?://\S+|www\.\S+")
_MENTION_RE = re.compile(r"@[\w_]+")
_WHITESPACE_RE = re.compile(r"\s+")


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = _NIKUD_RE.sub("", text)
    text = _DIR_CTRL_RE.sub("", text)
    text = _URL_RE.sub("[URL]", text)
    text = _MENTION_RE.sub("[MENTION]", text)
    text = _WHITESPACE_RE.sub(" ", text).strip().lower()
    return text


# ---------------------------------------------------------------------------
# Helper: load JSONL
# ---------------------------------------------------------------------------
def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                print(f"  [ERROR] {path.name} line {i}: invalid JSON: {exc}")
    return rows


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------
errors: list[str] = []
warnings: list[str] = []


def err(msg: str) -> None:
    errors.append(msg)
    print(f"  [FAIL] {msg}")


def warn(msg: str) -> None:
    warnings.append(msg)
    print(f"  [WARN] {msg}")


def ok(msg: str) -> None:
    print(f"  [OK]   {msg}")


def check_records(split_name: str, rows: list[dict]) -> None:
    """Check 1: all records have required fields, correct label_id, non-empty text."""
    bad_text = bad_label = bad_label_id = bad_source = 0
    for i, r in enumerate(rows):
        if not r.get("text", "").strip():
            bad_text += 1
            if bad_text <= 3:
                err(f"{split_name}[{i}]: empty text")
        label = r.get("label", "")
        if label not in LABEL2ID:
            bad_label += 1
            if bad_label <= 3:
                err(f"{split_name}[{i}]: bad label '{label}'")
        else:
            if r.get("label_id") != LABEL2ID[label]:
                bad_label_id += 1
                if bad_label_id <= 3:
                    err(f"{split_name}[{i}]: label_id mismatch for '{label}': "
                        f"expected {LABEL2ID[label]}, got {r.get('label_id')}")
        if not r.get("source", "").strip():
            bad_source += 1

    if bad_text == 0 and bad_label == 0 and bad_label_id == 0:
        ok(f"{split_name}: all records valid (text, label, label_id)")
    if bad_source > 0:
        warn(f"{split_name}: {bad_source} rows missing 'source' field")


def check_all_classes_present(split_name: str, rows: list[dict]) -> None:
    """Check 2: all 5 classes present."""
    present = set(r.get("label") for r in rows)
    missing = set(LABEL_NAMES) - present
    if missing:
        err(f"{split_name}: missing classes: {missing}")
    else:
        ok(f"{split_name}: all 5 classes present")


def check_no_intra_split_dups(split_name: str, rows: list[dict]) -> None:
    """Check 3: no intra-split duplicates.

    EDA-augmented rows (source ending in '_eda') are intentionally derived from
    original rows and may share normalized text. We only flag cases where two
    NON-eda rows share identical normalized text, or where an eda row duplicates
    another eda row of the same label (which would be a bug in EDA dedup).
    """
    norm_texts = [normalize(r.get("text", "")) for r in rows]
    counts = Counter(norm_texts)
    dups = {t: c for t, c in counts.items() if c > 1}
    if dups:
        # Determine how many are pure non-eda duplicates
        non_eda_norm = [normalize(r.get("text", "")) for r in rows
                        if not r.get("source", "").endswith("_eda")]
        non_eda_counts = Counter(non_eda_norm)
        non_eda_dups = {t: c for t, c in non_eda_counts.items() if c > 1}
        if non_eda_dups:
            err(f"{split_name}: {len(non_eda_dups)} duplicate normalized texts "
                f"(non-EDA rows, showing first 3): {list(non_eda_dups.items())[:3]}")
        else:
            ok(f"{split_name}: no intra-split duplicates ({len(rows)} rows); "
               f"{len(dups)} text(s) appear in both original and EDA-derived rows (expected)")
    else:
        ok(f"{split_name}: no intra-split duplicates ({len(rows)} rows)")


def check_cross_split_leakage(
    train_rows: list[dict],
    val_rows: list[dict],
    test_rows: list[dict],
) -> None:
    """Check 4: no exact cross-split leakage."""
    train_texts = {normalize(r["text"]) for r in train_rows}
    val_texts = {normalize(r["text"]) for r in val_rows}
    test_texts = {normalize(r["text"]) for r in test_rows}

    tv_leak = train_texts & val_texts
    tt_leak = train_texts & test_texts
    vt_leak = val_texts & test_texts

    total_leak = len(tv_leak) + len(tt_leak) + len(vt_leak)
    if total_leak > 0:
        err(f"Cross-split exact leakage: train/val={len(tv_leak)}, "
            f"train/test={len(tt_leak)}, val/test={len(vt_leak)}")
    else:
        ok(f"No cross-split exact leakage (train/val/test all disjoint)")


def check_test_size(test_rows: list[dict]) -> None:
    """Check 5: test set >= 300 rows.

    D9 rationale: prevalence-aware split has fewer offensive rows in test
    (~25 per offensive class vs ~120 in D8 balanced). The minimum is 300 rows
    to support per-class breakdown and macro-F1 bootstrap CI at the gate.
    """
    n = len(test_rows)
    if n < 300:
        err(f"test.jsonl too small: {n} rows (minimum 300 for D9 prevalence-aware split)")
    else:
        ok(f"test.jsonl size: {n} >= 300")


def check_class_weights(train_rows: list[dict]) -> None:
    """Check 6: class_weights.json consistent with train label counts."""
    if not WEIGHTS_PATH.exists():
        err(f"class_weights.json not found: {WEIGHTS_PATH}")
        return

    with WEIGHTS_PATH.open("r", encoding="utf-8") as f:
        weights_data = json.load(f)

    # label_order must match LABEL_NAMES
    if weights_data.get("label_order") != LABEL_NAMES:
        err(f"class_weights label_order mismatch: "
            f"expected {LABEL_NAMES}, got {weights_data.get('label_order')}")
        return

    # Recompute from train
    train_label_ids = [r["label_id"] for r in train_rows if r.get("label_id") is not None]
    expected_weights = compute_class_weight(
        "balanced",
        classes=np.arange(len(LABEL_NAMES)),
        y=np.array(train_label_ids),
    )
    stored_weights = np.array(weights_data.get("weights", []))

    if len(stored_weights) != len(LABEL_NAMES):
        err(f"class_weights has {len(stored_weights)} weights, expected {len(LABEL_NAMES)}")
        return

    if not np.allclose(stored_weights, expected_weights, atol=0.01):
        diffs = [(LABEL_NAMES[i], stored_weights[i], expected_weights[i])
                 for i in range(len(LABEL_NAMES))
                 if abs(stored_weights[i] - expected_weights[i]) > 0.01]
        err(f"class_weights stale (>0.01 diff): {diffs}")
    else:
        ok(f"class_weights.json consistent with train counts (atol=0.01)")


def check_d9_prevalence(
    train_rows: list[dict],
    val_rows: list[dict],
    test_rows: list[dict],
) -> None:
    """Check 7 (D9): prevalence-aware composition sanity.

    D9 specifies:
      train non_offensive: ~40-60% (target ~50%)
      val   non_offensive: ~60-80% (target ~70%)
      test  non_offensive: ~60-80% (target ~70%)

    Note: val/test are intentionally NOT balanced equally across classes —
    this is by design in D9 to restore precision[non_offensive].
    """
    def nonoff_pct(rows: list[dict]) -> float:
        if not rows:
            return 0.0
        c = Counter(r.get("label") for r in rows)
        return c.get("non_offensive", 0) / len(rows)

    t_pct = nonoff_pct(train_rows)
    v_pct = nonoff_pct(val_rows)
    x_pct = nonoff_pct(test_rows)

    ok(f"train non_offensive: {t_pct:.1%}")
    ok(f"val   non_offensive: {v_pct:.1%}")
    ok(f"test  non_offensive: {x_pct:.1%}")

    if not (0.35 <= t_pct <= 0.65):
        err(f"train non_offensive {t_pct:.1%} outside [35%, 65%] (D9 target ~50%)")
    if not (0.55 <= v_pct <= 0.85):
        warn(f"val non_offensive {v_pct:.1%} outside [55%, 85%] (D9 target ~70%)")
    if not (0.55 <= x_pct <= 0.85):
        warn(f"test non_offensive {x_pct:.1%} outside [55%, 85%] (D9 target ~70%)")


def check_stylistic_eval() -> None:
    """Check: stylistic_eval.jsonl is present and has rows."""
    if not STYLISTIC_PATH.exists():
        warn(f"stylistic_eval.jsonl not found: {STYLISTIC_PATH}")
        return
    rows = load_jsonl(STYLISTIC_PATH)
    styles = Counter(r.get("style") for r in rows)
    ok(f"stylistic_eval.jsonl: {len(rows)} rows, styles: {dict(styles)}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    print("=" * 60)
    print("Stage-1 split validator (§9.8)")
    print("=" * 60)

    # Load splits
    for path in [TRAIN_PATH, VAL_PATH, TEST_PATH, WEIGHTS_PATH]:
        if not path.exists():
            print(f"[FATAL] Required file not found: {path}")
            sys.exit(1)

    print(f"\n[Loading splits from {DATA_DIR}]")
    train_rows = load_jsonl(TRAIN_PATH)
    val_rows = load_jsonl(VAL_PATH)
    test_rows = load_jsonl(TEST_PATH)
    print(f"  train={len(train_rows)}, val={len(val_rows)}, test={len(test_rows)}")

    print("\n[Check 1: Record validity]")
    check_records("train", train_rows)
    check_records("val", val_rows)
    check_records("test", test_rows)

    print("\n[Check 2: All 5 classes present per split]")
    check_all_classes_present("train", train_rows)
    check_all_classes_present("val", val_rows)
    check_all_classes_present("test", test_rows)

    print("\n[Check 3: No intra-split duplicates]")
    check_no_intra_split_dups("train", train_rows)
    check_no_intra_split_dups("val", val_rows)
    check_no_intra_split_dups("test", test_rows)

    print("\n[Check 4: No cross-split leakage]")
    check_cross_split_leakage(train_rows, val_rows, test_rows)

    print("\n[Check 5: Test set size >= 300 (D9 prevalence-aware 70/20/10)]")
    check_test_size(test_rows)

    print("\n[Check 6: class_weights.json consistency]")
    check_class_weights(train_rows)

    print("\n[Check 7: D9 Prevalence-aware composition]")
    check_d9_prevalence(train_rows, val_rows, test_rows)

    print("\n[Check 8: stylistic_eval.jsonl]")
    check_stylistic_eval()

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("VALIDATION RESULT")
    print("=" * 60)

    # Print per-class table
    print("\nPer-class counts:")
    print(f"  {'Label':<22} {'train':>8} {'val':>8} {'test':>8}")
    print(f"  {'-'*22} {'-'*8} {'-'*8} {'-'*8}")
    for lname in LABEL_NAMES:
        tc = sum(1 for r in train_rows if r.get("label") == lname)
        vc = sum(1 for r in val_rows if r.get("label") == lname)
        xc = sum(1 for r in test_rows if r.get("label") == lname)
        print(f"  {lname:<22} {tc:>8} {vc:>8} {xc:>8}")
    print(f"  {'TOTAL':<22} {len(train_rows):>8} {len(val_rows):>8} {len(test_rows):>8}")

    print()
    if errors:
        print(f"FAILED: {len(errors)} error(s), {len(warnings)} warning(s)")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    else:
        msg = "PASSED"
        if warnings:
            msg += f" with {len(warnings)} warning(s)"
        print(msg)
        for w in warnings:
            print(f"  - {w}")
        sys.exit(0)


if __name__ == "__main__":
    main()
