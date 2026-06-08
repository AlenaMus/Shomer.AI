"""D9/D10 data-preparation pipeline for DictaBERT 5-class classifier.

Decision D9: prevalence-aware class mix + slang/code-switch/typo-noise strengthening.
Reverts from D8 full balancing (which caused precision[non_offensive]=0.688 false-alarm flood).

Decision D10: add benign code-switched data (synth_codeswitch.jsonl, 860 rows, ~49%
non_offensive) to improve code_switching stylistic slice without hurting precision.

NOTE: D11 heavy-noise augmentation was attempted (Round 6) but reverted — it cost
hate F1 -0.08 for only +0.02 on poor_spelling. D10 is the final model.
The add_noise_to_pool_heavy function remains in augment_noise.py but is NOT called here.

D10 composition rules:
  TRAIN:
    non_offensive = ~50% of train rows (= sum of all 4 offensive class rows)
    4 offensive classes ~equal among themselves
    Augment offensive minorities via EDA (2x cap) + noise augmentation (augment_noise.py)
    Cap: ~25–30% noise copies of train examples (biased toward offensive)

  VAL / TEST:
    ~70% non_offensive (production-realistic prevalence → precision/FPR meaningful)
    30% offensive (equally distributed across 4 classes)

  SPLIT RATIO: 70/20/10 (unchanged from D8)

  Class weights: recomputed on new train distribution — NOT uniform (non_off has most
  rows but the loss still applies class weights to downweight it in the Focal Loss).

  NEW SOURCES (D9.2):
    training/data/interim/synth_kids.jsonl      (kids/teen register synthesis)
    training/data/interim/synth_codeswitch.jsonl (Heb-Eng code-switched synthesis)
    training/augment_noise.py                    (label-preserving noise augmentation)

  CACHED SOURCES (unchanged from D8 — do NOT regenerate):
    training/data/raw/sinalab/AllData_OffensiveHebrew.csv
    training/data/interim/textdetox_he_labeled.jsonl
    training/data/interim/synth_porn.jsonl
    training/data/interim/jigsaw_he.jsonl
    training/data/interim/synth_hate_violence.jsonl
    training/data/interim/synth_abusive.jsonl
    plan-docs/meetings/m5/ocr_validation/sentences.jsonl

Cleaning stack (§11 locked, unchanged):
  A1 Exact dedup
  A2 MinHash near-dedup (Jaccard >= 0.85)
  A3 NFKC unicode normalization
  A4 Strip Hebrew nikud
  A5 Strip direction-control chars
  A6 Replace URLs / @mentions
  A7 Length filter (3–200 tokens)
  D1 Stratified split (seed=42)
  D2 Cross-split leakage check
  D3 stylistic_eval.jsonl (1040 OCR validation sentences)
  E1-E3 EDA on minority train classes, 2x cap, no E4

Outputs (into data/):
  data/train.jsonl
  data/validation.jsonl
  data/test.jsonl
  data/class_weights.json
  data/stylistic_eval.jsonl

Schema per row: {"text": str, "label": str, "label_id": int, "source": str}

Run in WSL2 training venv from repo root:
    python training/prepare_data_dictabert.py
"""
from __future__ import annotations

import hashlib
import json
import random
import re
import unicodedata
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.utils.class_weight import compute_class_weight

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_OUT = REPO_ROOT / "data"
SINALAB_CSV = REPO_ROOT / "training/data/raw/sinalab/AllData_OffensiveHebrew.csv"
TEXTDETOX_JSONL = REPO_ROOT / "training/data/interim/textdetox_he_labeled.jsonl"
SYNTH_PORN_JSONL = REPO_ROOT / "training/data/interim/synth_porn.jsonl"
STYLISTIC_SENTENCES = REPO_ROOT / "plan-docs/meetings/m5/ocr_validation/sentences.jsonl"

# Stage-2 cached sources (do NOT regenerate)
JIGSAW_HE_JSONL = REPO_ROOT / "training/data/interim/jigsaw_he.jsonl"
SYNTH_HV_JSONL = REPO_ROOT / "training/data/interim/synth_hate_violence.jsonl"
PORN_REAL_SEED_JSONL = REPO_ROOT / "training/data/interim/porn_real_seed.jsonl"
SYNTH_ABUSIVE_JSONL = REPO_ROOT / "training/data/interim/synth_abusive.jsonl"

# D9.2 new sources
SYNTH_KIDS_JSONL = REPO_ROOT / "training/data/interim/synth_kids.jsonl"
SYNTH_CODESWITCH_JSONL = REPO_ROOT / "training/data/interim/synth_codeswitch.jsonl"

# ---------------------------------------------------------------------------
# Label constants (§9.2 locked)
# ---------------------------------------------------------------------------
LABEL_NAMES = ["non_offensive", "abusive", "hate", "violence", "pornographic"]
LABEL2ID = {l: i for i, l in enumerate(LABEL_NAMES)}
ID2LABEL = {i: l for l, i in LABEL2ID.items()}
OFFENSIVE_LABELS = {"abusive", "hate", "violence", "pornographic"}

# ---------------------------------------------------------------------------
# D9 composition constants
# ---------------------------------------------------------------------------
# Offensive class sizes — how many rows each of the 4 offensive classes
# should contribute to TRAIN (before noise augmentation).
# These are achievable from the combined pool (verified in D8: each class had 840+).
OFFENSIVE_PER_CLASS_TRAIN = 900  # each of 4 offensive classes -> ~900 train rows
# NON_OFFENSIVE_TRAIN set to match total offensive (4 * 900 = 3600) -> ~50% each side
NON_OFF_TRAIN_TARGET = OFFENSIVE_PER_CLASS_TRAIN * 4  # 3600

# Val/Test composition: ~70% non_offensive (realistic prevalence)
# With ~900 offensive total split 4-ways across 4 classes per val+test,
# we need ~2100 non_offensive for val+test combined (70%) alongside 900 offensive (30%)
VAL_SIZE_FRAC = 0.20   # of total corpus
TEST_SIZE_FRAC = 0.10  # of total corpus

# Synth porn train cap (from D8 — unchanged)
SYNTH_PORN_TRAIN_CAP = 900

# ---------------------------------------------------------------------------
# SinaLab label normalization (unchanged from D8)
# ---------------------------------------------------------------------------
_SEVERITY_ORDER = ["violence", "hate", "pornographic", "abusive"]

_LABEL_ALIASES: dict[str, str] = {
    "not": "non_offensive",
    "none": "non_offensive",
    "non-offensive": "non_offensive",
    "non offensive": "non_offensive",
    "nonoffensive": "non_offensive",
    "porographic": "pornographic",
    "pornograhic": "pornographic",
    "pornografic": "pornographic",
    "racism": "hate",
    "racist": "hate",
    "hate speech": "hate",
    "abussive": "abusive",
}


def _normalize_sinalab_label(raw: str) -> str | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    raw = raw.strip().lower()
    parts = [p.strip() for p in raw.split(",")]
    resolved: list[str] = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        mapped = _LABEL_ALIASES.get(part)
        if mapped is None:
            if part in LABEL2ID:
                mapped = part
            else:
                for lname in LABEL_NAMES:
                    if part.startswith(lname[:4]):
                        mapped = lname
                        break
        if mapped:
            resolved.append(mapped)
    if not resolved:
        return None
    for priority_label in _SEVERITY_ORDER:
        if priority_label in resolved:
            return priority_label
    return resolved[0]


# ---------------------------------------------------------------------------
# Text normalization (A3-A6, unchanged from D8)
# ---------------------------------------------------------------------------
_NIKUD_RE = re.compile(r"[֑-ׇ]")
_DIR_CTRL_RE = re.compile(r"[‎‏‪-‮⁦-⁩]")
_URL_RE = re.compile(r"https?://\S+|www\.\S+")
_MENTION_RE = re.compile(r"@[\w_]+")
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = _NIKUD_RE.sub("", text)
    text = _DIR_CTRL_RE.sub("", text)
    text = _URL_RE.sub("[URL]", text)
    text = _MENTION_RE.sub("[MENTION]", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text


def dedup_key(text: str) -> str:
    return normalize_text(text).lower()


def token_len(text: str) -> int:
    return len(text.split())


def passes_length_filter(text: str, min_tok: int = 3, max_tok: int = 200) -> bool:
    n = token_len(text)
    return min_tok <= n <= max_tok


# ---------------------------------------------------------------------------
# MinHash near-dedup (A2, unchanged from D8)
# ---------------------------------------------------------------------------
def _build_minhash(text: str, num_perm: int = 128):
    from datasketch import MinHash
    m = MinHash(num_perm=num_perm)
    for i in range(max(1, len(text) - 2)):
        m.update(text[i : i + 3].encode("utf-8"))
    return m


def near_dedup_rows(rows: list[dict], threshold: float = 0.85, num_perm: int = 128, verbose: bool = True) -> list[dict]:
    from datasketch import MinHashLSH
    lsh = MinHashLSH(threshold=threshold, num_perm=num_perm)
    kept: list[dict] = []
    for i, row in enumerate(rows):
        key = f"r{i}"
        m = _build_minhash(dedup_key(row["text"]), num_perm=num_perm)
        try:
            result = lsh.query(m)
        except Exception:
            result = []
        if result:
            continue
        lsh.insert(key, m)
        kept.append(row)
        if verbose and (i + 1) % 2000 == 0:
            print(f"    MinHash progress: {i + 1}/{len(rows)}, kept={len(kept)}")
    return kept


def cross_split_leakage_check(
    train_rows: list[dict],
    val_rows: list[dict],
    test_rows: list[dict],
    num_perm: int = 128,
    threshold: float = 0.85,
    verbose: bool = True,
) -> int:
    from datasketch import MinHashLSH
    lsh = MinHashLSH(threshold=threshold, num_perm=num_perm)
    for i, row in enumerate(train_rows):
        m = _build_minhash(dedup_key(row["text"]), num_perm=num_perm)
        lsh.insert(f"tr{i}", m)
    leaks = 0
    for split_name, rows in [("val", val_rows), ("test", test_rows)]:
        for j, row in enumerate(rows):
            m = _build_minhash(dedup_key(row["text"]), num_perm=num_perm)
            hits = lsh.query(m)
            if hits:
                leaks += 1
                if verbose and leaks <= 5:
                    print(f"  [LEAK] {split_name}[{j}]: \"{row['text'][:60]}...\"")
    return leaks


# ---------------------------------------------------------------------------
# EDA augmentation (E1-E3, train minorities only, 2x cap, unchanged from D8)
# ---------------------------------------------------------------------------
def _eda_random_insert(words: list[str], vocab: list[str], rng: random.Random) -> list[str]:
    if not vocab:
        return words
    idx = rng.randint(0, len(words))
    w = rng.choice(vocab)
    return words[:idx] + [w] + words[idx:]


def _eda_random_swap(words: list[str], rng: random.Random) -> list[str]:
    if len(words) < 2:
        return words
    words = list(words)
    i, j = rng.sample(range(len(words)), 2)
    words[i], words[j] = words[j], words[i]
    return words


def _eda_random_delete(words: list[str], p: float, rng: random.Random) -> list[str]:
    if len(words) <= 1:
        return words
    result = [w for w in words if rng.random() > p]
    return result if result else [rng.choice(words)]


# ---------------------------------------------------------------------------
# Loaders (unchanged from D8)
# ---------------------------------------------------------------------------
def load_sinalab(path: Path, verbose: bool = True) -> list[dict]:
    df = pd.read_csv(path, encoding="utf-8")
    if verbose:
        print(f"  SinaLab raw: {len(df)} rows, columns: {list(df.columns)}")
    rows: list[dict] = []
    dropped_label = dropped_text = 0
    for _, row in df.iterrows():
        raw_label = str(row.get("Label", "") or "").strip()
        label = _normalize_sinalab_label(raw_label)
        if label is None:
            dropped_label += 1
            continue
        text = str(row.get("TweetText", "") or "").strip()
        if not text:
            dropped_text += 1
            continue
        rows.append({"text": text, "label": label, "source": "sinalab"})
    if verbose:
        print(f"  SinaLab after label norm: {len(rows)} rows "
              f"(dropped_label={dropped_label}, dropped_text={dropped_text})")
        print(f"  Label distribution: {dict(Counter(r['label'] for r in rows))}")
    return rows


def load_textdetox_labeled(path: Path, verbose: bool = True) -> list[dict]:
    toxic_rows: list[dict] = []
    if path.exists():
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                label = row.get("label", "").strip()
                if label not in LABEL2ID:
                    continue
                text = row.get("text", "").strip()
                if not text:
                    continue
                toxic_rows.append({"text": text, "label": label, "source": "textdetox_he"})
        if verbose:
            print(f"  textdetox toxic rows: {len(toxic_rows)}")
            print(f"  textdetox distribution: {dict(Counter(r['label'] for r in toxic_rows))}")
    else:
        print(f"  [WARN] textdetox labeled file not found: {path}")
    return toxic_rows


def load_textdetox_clean(verbose: bool = True) -> list[dict]:
    try:
        from datasets import load_dataset
        ds = load_dataset("textdetox/multilingual_toxicity_dataset", split="he")
        clean_rows = []
        for row in ds:
            if int(row.get("toxic", 0)) == 0:
                text = str(row.get("text", "")).strip()
                if text:
                    clean_rows.append({"text": text, "label": "non_offensive", "source": "textdetox_he"})
        if verbose:
            print(f"  textdetox clean rows (non_offensive pool): {len(clean_rows)}")
        return clean_rows
    except Exception as exc:
        print(f"  [WARN] Could not load textdetox clean rows: {exc}")
        return []


def load_synth_porn(path: Path, verbose: bool = True) -> list[dict]:
    rows: list[dict] = []
    if path.exists():
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                text = row.get("text", "").strip()
                if not text:
                    continue
                rows.append({"text": text, "label": "pornographic", "source": "synthetic"})
        if verbose:
            print(f"  Synthetic porn rows: {len(rows)}")
    else:
        print(f"  [WARN] Synth porn file not found: {path}")
    return rows


def load_jsonl_rows(path: Path, expected_labels: set[str] | None = None, verbose: bool = True) -> list[dict]:
    rows: list[dict] = []
    if not path.exists():
        if verbose:
            print(f"  [INFO] File not found (skipping): {path.name}")
        return rows
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            label = row.get("label", "").strip()
            if expected_labels is not None and label not in expected_labels:
                continue
            text = row.get("text", "").strip()
            if not text:
                continue
            source = row.get("source", "unknown").strip()
            rows.append({"text": text, "label": label, "source": source})
    if verbose:
        print(f"  Loaded {len(rows)} rows from {path.name}")
        print(f"  Distribution: {dict(Counter(r['label'] for r in rows))}")
    return rows


# ---------------------------------------------------------------------------
# D9 prevalence-aware split builder
# ---------------------------------------------------------------------------
def build_d9_splits(
    by_label: dict[str, list[dict]],
    rng: random.Random,
    verbose: bool = True,
) -> tuple[list[dict], list[dict], list[dict]]:
    """
    Build train/val/test with D9 prevalence-aware composition.

    Train:
      non_offensive = NON_OFF_TRAIN_TARGET (= 4 * OFFENSIVE_PER_CLASS_TRAIN)
      Each offensive class = OFFENSIVE_PER_CLASS_TRAIN (capped by available pool + 2x EDA)

    Val + Test combined (before 2:1 split):
      70% non_offensive, 30% offensive (equal across 4 classes)

    Returns (train_rows, val_rows, test_rows).
    Each is a plain list — caller adds label_id + EDA separately.
    """
    # ------------------------------------------------------------------
    # OFFENSIVE TRAIN: pick OFFENSIVE_PER_CLASS_TRAIN from each class
    # ------------------------------------------------------------------
    off_train: dict[str, list[dict]] = {}
    off_valtest: dict[str, list[dict]] = {}

    for lname in ["abusive", "hate", "violence", "pornographic"]:
        pool = list(by_label.get(lname, []))
        rng.shuffle(pool)
        n_for_train = min(OFFENSIVE_PER_CLASS_TRAIN, len(pool))
        off_train[lname] = pool[:n_for_train]
        off_valtest[lname] = pool[n_for_train:]
        if verbose:
            print(f"  {lname:<20}: pool={len(pool)}, train={n_for_train}, val+test_pool={len(pool) - n_for_train}")

    # ------------------------------------------------------------------
    # OFFENSIVE VAL+TEST: how many offensive rows we can use for val/test
    # The target is that in val+test combined, offensive = 30%.
    # So: if we have N total offensive rows for val+test, we need N_nonoff = N/0.30 * 0.70 non_off rows.
    # We determine N from each class's leftover pool.
    # Cap each offensive val+test class at ~100 (for val+test combined with ~50/50 split).
    # ------------------------------------------------------------------
    OFFENSIVE_VALTEST_PER_CLASS = 100  # each of 4 offensive -> 100 combined val+test rows
    off_valtest_selected: dict[str, list[dict]] = {}
    for lname in ["abusive", "hate", "violence", "pornographic"]:
        pool = off_valtest[lname]
        n = min(OFFENSIVE_VALTEST_PER_CLASS, len(pool))
        off_valtest_selected[lname] = pool[:n]
        if verbose:
            print(f"  {lname:<20}: val+test rows = {n}")

    total_off_valtest = sum(len(v) for v in off_valtest_selected.values())
    # 30% offensive -> 70% non_offensive in val+test
    # N_nonoff = total_off_valtest * (70/30)
    n_nonoff_valtest = int(total_off_valtest * (70.0 / 30.0))
    if verbose:
        print(f"\n  Total offensive val+test rows: {total_off_valtest}")
        print(f"  Target non_offensive val+test rows (70%): {n_nonoff_valtest}")

    # ------------------------------------------------------------------
    # NON-OFFENSIVE SPLIT: partition into train + valtest
    # ------------------------------------------------------------------
    nonoff_pool = list(by_label.get("non_offensive", []))
    rng.shuffle(nonoff_pool)

    # We need NON_OFF_TRAIN_TARGET for train + n_nonoff_valtest for val+test
    n_nonoff_train = min(NON_OFF_TRAIN_TARGET, len(nonoff_pool))
    n_nonoff_vt = min(n_nonoff_valtest, max(0, len(nonoff_pool) - n_nonoff_train))

    if verbose:
        print(f"  non_offensive pool: {len(nonoff_pool)}")
        print(f"  non_offensive train: {n_nonoff_train} (target={NON_OFF_TRAIN_TARGET})")
        print(f"  non_offensive val+test: {n_nonoff_vt} (target={n_nonoff_valtest})")

    nonoff_train = nonoff_pool[:n_nonoff_train]
    nonoff_valtest = nonoff_pool[n_nonoff_train : n_nonoff_train + n_nonoff_vt]

    # ------------------------------------------------------------------
    # TRAIN pool (before EDA and noise)
    # ------------------------------------------------------------------
    train_rows: list[dict] = list(nonoff_train)
    for lname in ["abusive", "hate", "violence", "pornographic"]:
        train_rows.extend(off_train[lname])
    rng.shuffle(train_rows)

    # ------------------------------------------------------------------
    # VAL+TEST pool: combine non_off + offensive val+test, then split 2:1
    # ------------------------------------------------------------------
    valtest_rows: list[dict] = list(nonoff_valtest)
    for lname in ["abusive", "hate", "violence", "pornographic"]:
        valtest_rows.extend(off_valtest_selected[lname])
    rng.shuffle(valtest_rows)

    # Stratified 2:1 split (val:test) by label
    valtest_labels = [r["label"] for r in valtest_rows]
    # val gets 2/3 of valtest, test gets 1/3
    # (This is consistent with 70/20/10 overall: val=20%, test=10%, so val:test = 2:1)
    try:
        val_rows, test_rows = train_test_split(
            valtest_rows,
            test_size=1.0 / 3.0,  # 1/3 of valtest -> test (10% overall)
            stratify=valtest_labels,
            random_state=42,
        )
    except ValueError:
        # If stratify fails (tiny class), fall back to random split
        print("  [WARN] Stratified val/test split failed; using random split.")
        mid = len(valtest_rows) * 2 // 3
        val_rows = valtest_rows[:mid]
        test_rows = valtest_rows[mid:]

    if verbose:
        print(f"\n  Pre-EDA train: {len(train_rows)}")
        td = Counter(r["label"] for r in train_rows)
        print(f"  Train dist: {dict(td)}")
        nonoff_pct = td.get("non_offensive", 0) / max(len(train_rows), 1) * 100
        print(f"  Train non_offensive %: {nonoff_pct:.1f}% (target ~50%)")

        print(f"\n  Val:  {len(val_rows)}")
        vd = Counter(r["label"] for r in val_rows)
        print(f"  Val dist: {dict(vd)}")
        vno_pct = vd.get("non_offensive", 0) / max(len(val_rows), 1) * 100
        print(f"  Val non_offensive %: {vno_pct:.1f}% (target ~70%)")

        print(f"\n  Test: {len(test_rows)}")
        xd = Counter(r["label"] for r in test_rows)
        print(f"  Test dist: {dict(xd)}")
        xno_pct = xd.get("non_offensive", 0) / max(len(test_rows), 1) * 100
        print(f"  Test non_offensive %: {xno_pct:.1f}% (target ~70%)")

    return train_rows, val_rows, test_rows


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------
def main() -> None:  # noqa: C901
    DATA_OUT.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("D9 DictaBERT data preparation pipeline (prevalence-aware)")
    print("=" * 60)

    # ------------------------------------------------------------------
    # 1. Load all sources
    # ------------------------------------------------------------------
    print("\n[1/7] Loading data sources...")

    sinalab_rows = load_sinalab(SINALAB_CSV, verbose=True)
    textdetox_toxic = load_textdetox_labeled(TEXTDETOX_JSONL, verbose=True)
    textdetox_clean = load_textdetox_clean(verbose=True)

    # Synth porn — cap at SYNTH_PORN_TRAIN_CAP (900) as in D8
    rng_porn_cap = random.Random(42)
    synth_porn_rows = load_synth_porn(SYNTH_PORN_JSONL, verbose=True)

    print("\n  [Stage-2 cached] Loading...")
    jigsaw_he_rows = load_jsonl_rows(JIGSAW_HE_JSONL, expected_labels={"hate", "violence"}, verbose=True)
    synth_hv_rows = load_jsonl_rows(SYNTH_HV_JSONL, expected_labels={"hate", "violence"}, verbose=True)
    porn_real_seed_rows = load_jsonl_rows(PORN_REAL_SEED_JSONL, expected_labels={"pornographic"}, verbose=True)
    synth_abusive_rows = load_jsonl_rows(SYNTH_ABUSIVE_JSONL, expected_labels={"abusive"}, verbose=True)

    print("\n  [D9.2 new sources] Loading...")
    synth_kids_rows = load_jsonl_rows(SYNTH_KIDS_JSONL, verbose=True)
    synth_codeswitch_rows = load_jsonl_rows(SYNTH_CODESWITCH_JSONL, verbose=True)

    if not synth_kids_rows:
        print("  [WARN] synth_kids.jsonl not found — run training/synthesize_kids.py first.")
    if not synth_codeswitch_rows:
        print("  [WARN] synth_codeswitch.jsonl not found — run training/synthesize_codeswitch.py first.")

    # ------------------------------------------------------------------
    # 2. Normalize text (A3-A6) + length filter (A7)
    # ------------------------------------------------------------------
    print("\n[2/7] Normalizing text and applying length filter...")

    def normalize_and_filter(rows: list[dict]) -> list[dict]:
        out = []
        for row in rows:
            text = normalize_text(row["text"])
            if passes_length_filter(text):
                out.append({"text": text, "label": row["label"], "source": row["source"]})
        return out

    all_rows: list[dict] = []

    all_rows.extend(normalize_and_filter(sinalab_rows))
    all_rows.extend(normalize_and_filter(textdetox_toxic))
    all_rows.extend(normalize_and_filter(textdetox_clean))

    # Synth porn: apply train cap
    synth_porn_norm = normalize_and_filter(synth_porn_rows)
    if len(synth_porn_norm) > SYNTH_PORN_TRAIN_CAP:
        synth_porn_norm = rng_porn_cap.sample(synth_porn_norm, SYNTH_PORN_TRAIN_CAP)
        print(f"  Synth porn down-sampled to {SYNTH_PORN_TRAIN_CAP}")
    all_rows.extend(synth_porn_norm)

    # Stage-2 cached
    all_rows.extend(normalize_and_filter(jigsaw_he_rows))
    all_rows.extend(normalize_and_filter(synth_hv_rows))
    all_rows.extend(normalize_and_filter(synth_abusive_rows))

    # D9.2 new
    all_rows.extend(normalize_and_filter(synth_kids_rows))
    all_rows.extend(normalize_and_filter(synth_codeswitch_rows))

    # porn_real_seed: separate bucket (injected into val+test later)
    porn_real_seed_normalized = normalize_and_filter(porn_real_seed_rows)
    if porn_real_seed_normalized:
        print(f"  porn_real_seed: {len(porn_real_seed_normalized)} rows (separate val+test bucket)")

    print(f"  After normalization + length filter: {len(all_rows)} rows (excl. porn_real_seed)")
    dist_raw = Counter(r["label"] for r in all_rows)
    print(f"  Raw pool distribution: {dict(dist_raw)}")

    # ------------------------------------------------------------------
    # 3. Exact dedup (A1)
    # ------------------------------------------------------------------
    print("\n[3/7] Exact deduplication (A1)...")
    seen_keys: set[str] = set()
    deduped_exact: list[dict] = []
    for row in all_rows:
        key = dedup_key(row["text"])
        if key not in seen_keys:
            seen_keys.add(key)
            deduped_exact.append(row)
    print(f"  After exact dedup: {len(deduped_exact)} rows "
          f"(removed {len(all_rows) - len(deduped_exact)})")

    # ------------------------------------------------------------------
    # 4. Near-dedup via MinHash (A2)
    # ------------------------------------------------------------------
    print("\n[4/7] Near-dedup via MinHash Jaccard >= 0.85 (A2)...")
    try:
        deduped_near = near_dedup_rows(deduped_exact, threshold=0.85, num_perm=128, verbose=True)
        print(f"  After near-dedup: {len(deduped_near)} rows "
              f"(removed {len(deduped_exact) - len(deduped_near)})")
    except ImportError:
        print("  [WARN] datasketch not available; skipping near-dedup.")
        deduped_near = deduped_exact

    # Check per-class pool sizes
    by_label: dict[str, list[dict]] = {lname: [] for lname in LABEL_NAMES}
    for row in deduped_near:
        lname = row["label"]
        if lname in by_label:
            by_label[lname].append(row)
    print(f"\n  Per-class pool sizes after dedup: {dict((k, len(v)) for k, v in by_label.items())}")

    # ------------------------------------------------------------------
    # 5. D9 prevalence-aware split
    # ------------------------------------------------------------------
    print("\n[5/7] D9 prevalence-aware train/val/test split...")
    rng = random.Random(42)
    train_rows, val_rows, test_rows = build_d9_splits(by_label, rng, verbose=True)

    # ------------------------------------------------------------------
    # 5b. Inject porn_real_seed into val + test (50/50)
    # ------------------------------------------------------------------
    if porn_real_seed_normalized:
        print(f"\n  Injecting {len(porn_real_seed_normalized)} porn_real_seed rows into val+test...")
        existing_vt_keys = {dedup_key(r["text"]) for r in val_rows + test_rows}
        porn_seed_deduped = [r for r in porn_real_seed_normalized if dedup_key(r["text"]) not in existing_vt_keys]
        removed = len(porn_real_seed_normalized) - len(porn_seed_deduped)
        if removed:
            print(f"    Removed {removed} porn_real_seed rows duplicating val/test")
        rng_porn = random.Random(42)
        rng_porn.shuffle(porn_seed_deduped)
        half = len(porn_seed_deduped) // 2
        val_rows = val_rows + porn_seed_deduped[:half]
        test_rows = test_rows + porn_seed_deduped[half:]
        print(f"    Injected: val +{half}, test +{len(porn_seed_deduped) - half}")

    # ------------------------------------------------------------------
    # 6. Cross-split leakage check (D2)
    # ------------------------------------------------------------------
    print("\n[6/7] Cross-split leakage check (D2)...")
    train_keys = {dedup_key(r["text"]) for r in train_rows}
    val_keys = {dedup_key(r["text"]) for r in val_rows}
    test_keys = {dedup_key(r["text"]) for r in test_rows}
    exact_leaks = len(train_keys & val_keys) + len(train_keys & test_keys) + len(val_keys & test_keys)
    print(f"  Exact cross-split leaks: {exact_leaks}")
    try:
        near_leaks = cross_split_leakage_check(train_rows, val_rows, test_rows, verbose=True)
        print(f"  Near-dup cross-split leaks: {near_leaks}")
        if near_leaks > 0:
            print(f"  [WARN] {near_leaks} near-dup pairs across splits (MinHash approx).")
    except ImportError:
        print("  [WARN] datasketch not available; skipping near-dup leakage check.")

    # ------------------------------------------------------------------
    # 7. EDA augmentation on train minorities (E1-E3, 2x cap)
    # ------------------------------------------------------------------
    print("\n[7a/7] EDA augmentation on train minorities (E1-E3, 2x cap)...")
    eda_rng = random.Random(42)
    all_train_words: list[str] = []
    for row in train_rows:
        all_train_words.extend(row["text"].split())
    train_vocab = list(set(all_train_words))

    augmented_eda: list[dict] = []
    for lname in ["abusive", "hate", "violence", "pornographic"]:
        lrows = [r for r in train_rows if r["label"] == lname]
        n_have = len(lrows)
        # Target per offensive class in train (from OFFENSIVE_PER_CLASS_TRAIN, 70% = train fraction)
        n_target = OFFENSIVE_PER_CLASS_TRAIN
        n_need = max(0, n_target - n_have)
        n_max_aug = n_have  # 2x cap
        n_aug = min(n_need, n_max_aug)
        if n_aug <= 0:
            print(f"  {lname:<20}: {n_have} rows (no EDA needed)")
            continue
        aug_count = 0
        attempts = 0
        while aug_count < n_aug and attempts < n_aug * 5:
            attempts += 1
            row = eda_rng.choice(lrows)
            words = row["text"].split()
            op = eda_rng.choice(["insert", "swap", "delete"])
            if op == "insert":
                idx = eda_rng.randint(0, len(words))
                w = eda_rng.choice(train_vocab)
                words = words[:idx] + [w] + words[idx:]
            elif op == "swap" and len(words) >= 2:
                i, j = eda_rng.sample(range(len(words)), 2)
                words[i], words[j] = words[j], words[i]
            else:
                words = [w for w in words if eda_rng.random() > 0.1] or [eda_rng.choice(words)]
            new_text = " ".join(words).strip()
            if not new_text:
                continue
            augmented_eda.append({
                "text": new_text,
                "label": lname,
                "label_id": LABEL2ID[lname],
                "source": f"{row['source']}_eda",
            })
            aug_count += 1
        print(f"  {lname:<20}: {n_have} + {aug_count} EDA -> {n_have + aug_count} (target={n_target})")

    train_rows = train_rows + augmented_eda

    # ------------------------------------------------------------------
    # 7b. Light-noise augmentation (augment_noise.py, D9.2(a) — UNCHANGED from D10)
    # Target: ~28% noisy copies of train, biased toward offensive
    # ------------------------------------------------------------------
    print("\n[7b/7] Light-noise augmentation (D9.2(a), ~28% of train, offensive-biased)...")
    try:
        import sys as _sys  # noqa: PLC0415
        _sys.path.insert(0, str(REPO_ROOT))
        from training.augment_noise import add_noise_to_pool  # noqa: PLC0415
        noisy_rows = add_noise_to_pool(
            train_rows,
            fraction=0.28,
            seed=42,
            bias_toward_offensive=True,
            n_ops=2,
        )
        print(f"  Generated {len(noisy_rows)} light-noise copies from {len(train_rows)} train rows")
        train_rows = train_rows + noisy_rows
    except Exception as exc:
        print(f"  [WARN] Light-noise augmentation failed: {exc}. Skipping.")

    # ------------------------------------------------------------------
    # 7c. Dedup EDA/noise augmented train
    # ------------------------------------------------------------------
    seen_eda: set[str] = set()
    train_deduped: list[dict] = []
    for r in train_rows:
        k = dedup_key(r["text"])
        if k not in seen_eda:
            seen_eda.add(k)
            train_deduped.append(r)
    removed_dups = len(train_rows) - len(train_deduped)
    if removed_dups > 0:
        print(f"  Removed {removed_dups} duplicate rows from EDA/noise augmentation.")
    train_rows = train_deduped

    # ------------------------------------------------------------------
    # 7d. Add label_id to all rows
    # ------------------------------------------------------------------
    def add_label_id(rows: list[dict]) -> list[dict]:
        result = []
        for r in rows:
            label = r["label"]
            result.append({
                "text": r["text"],
                "label": label,
                "label_id": LABEL2ID[label],
                "source": r.get("source", "unknown"),
            })
        return result

    train_rows = add_label_id(train_rows)
    val_rows = add_label_id(val_rows)
    test_rows = add_label_id(test_rows)

    # ------------------------------------------------------------------
    # 8. Write JSONL splits
    # ------------------------------------------------------------------
    print("\n[8/7] Writing splits...")

    def write_jsonl(rows: list[dict], path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"  Wrote {len(rows)} rows to {path}")

    write_jsonl(train_rows, DATA_OUT / "train.jsonl")
    write_jsonl(val_rows, DATA_OUT / "validation.jsonl")
    write_jsonl(test_rows, DATA_OUT / "test.jsonl")

    # ------------------------------------------------------------------
    # class_weights.json (§9.4) — recomputed on actual train distribution
    # ------------------------------------------------------------------
    print("\n[Computing class_weights.json...]")
    train_label_ids = [r["label_id"] for r in train_rows]
    weights = compute_class_weight(
        "balanced",
        classes=np.arange(len(LABEL_NAMES)),
        y=np.array(train_label_ids),
    )
    train_counts_by_id = Counter(train_label_ids)
    counts_ordered = [train_counts_by_id[i] for i in range(len(LABEL_NAMES))]

    td_final = Counter(r["label"] for r in train_rows)
    nonoff_pct = td_final.get("non_offensive", 0) / max(len(train_rows), 1) * 100

    class_weights_obj: dict[str, Any] = {
        "method": "sklearn_balanced",
        "computed_on": "train.jsonl",
        "label_order": LABEL_NAMES,
        "weights": [round(float(w), 6) for w in weights],
        "counts": counts_ordered,
        "total": len(train_rows),
        "non_offensive_pct_train": round(nonoff_pct, 2),
        "computed_at": datetime.utcnow().strftime("%Y-%m-%d"),
        "note": (
            "D10 prevalence-aware mix: train ~50% non_offensive, val/test ~70% non_offensive. "
            "Weights are NOT uniform — non_offensive is down-weighted by Focal Loss alpha. "
            "pornographic val/test contains synthetic rows (caveat: only 4 real SinaLab porn examples). "
            "D10: light-noise copies (~28% of train, biased toward offensive, D9 unchanged). "
            "D11 heavy-noise reverted — cost hate F1 -0.08 for only +0.02 on poor_spelling."
        ),
    }
    weights_path = DATA_OUT / "class_weights.json"
    with weights_path.open("w", encoding="utf-8") as f:
        json.dump(class_weights_obj, f, ensure_ascii=False, indent=2)
    print(f"  Wrote class_weights.json")
    print(f"  Weights: {list(zip(LABEL_NAMES, [round(float(w), 4) for w in weights]))}")

    # ------------------------------------------------------------------
    # stylistic_eval.jsonl (D3)
    # ------------------------------------------------------------------
    print("\n[Writing stylistic_eval.jsonl...]")
    _CATEGORY_TO_LABEL = {
        "none": "non_offensive",
        "abusive": "abusive",
        "hate": "hate",
        "violence": "violence",
        "pornographic": "pornographic",
    }
    stylistic_rows: list[dict] = []
    if STYLISTIC_SENTENCES.exists():
        with STYLISTIC_SENTENCES.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                raw = json.loads(line)
                text = str(raw.get("text", "")).strip()
                if not text:
                    continue
                text = normalize_text(text)
                raw_cat = str(raw.get("category", "none")).strip().lower()
                label = _CATEGORY_TO_LABEL.get(raw_cat, "non_offensive")
                style = str(raw.get("style", "")).strip()
                if style not in {"clear_hebrew", "children_mistakes", "code_switching", "poor_spelling"}:
                    style_label = str(raw.get("style_label", "")).strip()
                    style = {"A": "clear_hebrew", "B": "children_mistakes", "C": "code_switching", "D": "poor_spelling"}.get(style_label, "clear_hebrew")
                stylistic_rows.append({
                    "text": text,
                    "label": label,
                    "label_id": LABEL2ID[label],
                    "source": "our_ocr_validation",
                    "style": style,
                })
        print(f"  Loaded {len(stylistic_rows)} stylistic eval rows")
    else:
        print(f"  [WARN] Stylistic sentences file not found: {STYLISTIC_SENTENCES}")
    write_jsonl(stylistic_rows, DATA_OUT / "stylistic_eval.jsonl")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("D10 SUMMARY (D9 + code-switch data; D11 heavy-noise reverted)")
    print("=" * 60)
    print(f"  train.jsonl:         {len(train_rows):>6} rows")
    print(f"  validation.jsonl:    {len(val_rows):>6} rows")
    print(f"  test.jsonl:          {len(test_rows):>6} rows")
    print(f"  stylistic_eval.jsonl:{len(stylistic_rows):>6} rows")
    print()

    for split_name, rows in [("train", train_rows), ("validation", val_rows), ("test", test_rows)]:
        dist = Counter(r["label"] for r in rows)
        total = len(rows)
        print(f"  {split_name}:")
        for lname in LABEL_NAMES:
            n = dist.get(lname, 0)
            pct = n / max(total, 1) * 100
            print(f"    {lname:<20}: {n:>5}  ({pct:.1f}%)")
        print()

    vd = Counter(r["label"] for r in val_rows)
    xd = Counter(r["label"] for r in test_rows)
    vno_pct = vd.get("non_offensive", 0) / max(len(val_rows), 1) * 100
    xno_pct = xd.get("non_offensive", 0) / max(len(test_rows), 1) * 100
    td_f = Counter(r["label"] for r in train_rows)
    tno_pct = td_f.get("non_offensive", 0) / max(len(train_rows), 1) * 100

    print(f"  D9 KEY METRICS:")
    print(f"    train non_offensive %: {tno_pct:.1f}% (target ~50%)")
    print(f"    val   non_offensive %: {vno_pct:.1f}% (target ~70%)")
    print(f"    test  non_offensive %: {xno_pct:.1f}% (target ~70%)")
    print()

    print("  class_weights.json:")
    for lname, w in zip(LABEL_NAMES, weights):
        print(f"    {lname:<20}: {w:.4f}")

    print()
    print("D10 CAVEATS:")
    print("  1. Train ~50% non_offensive (prevalence-aware, NOT fully balanced).")
    print("     This restores precision[non_offensive] vs D8 balanced (which had 0.688).")
    print("  2. Val/Test ~70% non_offensive (realistic prevalence) for meaningful FPR.")
    print("  3. Synthetic/translated rows eligible for val/test (D8 user choice, maintained).")
    print("  4. pornographic val/test still predominantly synthetic (only 4 real SinaLab rows).")
    print("  5. Light-noise augmentation (~28% of train) biased toward offensive classes (D9 unchanged).")
    print("  6. D11 heavy-noise reverted: cost hate F1 -0.08 for only +0.02 on poor_spelling.")
    print("     add_noise_to_pool_heavy remains in augment_noise.py but is NOT called.")
    print("  7. New sources: synth_kids + synth_codeswitch (D9.2, unchanged).")
    print()
    print("Done. Run training/validate_splits.py to verify.")


if __name__ == "__main__":
    main()
