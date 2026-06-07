"""Stage-0: fetch SinaLab Offensive-Hebrew CSVs from GitHub and inspect real schema/counts.

The dataset is NOT an HF dataset repo (load_dataset fails); it lives in the GitHub repo
SinaLab/OffensiveHebrew under data/*.csv. This script downloads the four CSVs into
training/data/raw/sinalab/ and reports columns, dtypes, sample rows, and real per-class
counts so we can confirm how minority-starved the offensive classes actually are.

Run in WSL2 training venv from repo root:
    python training/scripts/fetch_inspect_sinalab.py
"""
from __future__ import annotations

import urllib.request
from collections import Counter
from pathlib import Path

import pandas as pd

RAW_BASE = "https://raw.githubusercontent.com/SinaLab/OffensiveHebrew/main/data"
FILES = ["train.csv", "test.csv", "val.csv", "none-offiensive.csv"]  # repo misspells "offiensive"
DEST = Path("training/data/raw/sinalab")
OFFENSIVE_COLS = ["abusive", "hate", "violence", "pornographic"]
SEVERITY = ["violence", "hate", "pornographic", "abusive"]  # §9 priority


def download() -> None:
    DEST.mkdir(parents=True, exist_ok=True)
    for f in FILES:
        out = DEST / f
        if out.exists() and out.stat().st_size > 0:
            print(f"  cached: {f} ({out.stat().st_size:,} B)")
            continue
        url = f"{RAW_BASE}/{f}"
        print(f"  downloading {f} ...")
        urllib.request.urlretrieve(url, out)
        print(f"    saved {out.stat().st_size:,} B")


def single_label(row: pd.Series) -> str:
    flagged = [c for c in OFFENSIVE_COLS if c in row and int(row[c] or 0) == 1]
    if not flagged:
        return "non_offensive"
    for c in SEVERITY:
        if c in flagged:
            return c
    return flagged[0]


def main() -> None:
    print("=== DOWNLOAD ===")
    download()

    print("\n=== PER-FILE SCHEMA + COUNTS ===")
    grand = Counter()
    for f in FILES:
        path = DEST / f
        # files may be tab- or comma-separated; sniff by trying comma then tab
        df = pd.read_csv(path)
        if df.shape[1] == 1:
            df = pd.read_csv(path, sep="\t")
        print(f"\n--- {f}: shape={df.shape} ---")
        print(f"  columns: {list(df.columns)}")
        print(f"  dtypes: {dict(df.dtypes.astype(str))}")
        # show first row truncated
        if len(df):
            r0 = {k: (str(v)[:70] + "…" if len(str(v)) > 70 else v) for k, v in df.iloc[0].items()}
            print(f"  row[0]: {r0}")
        # per-class counts only if the 4 offensive columns exist
        if all(c in df.columns for c in OFFENSIVE_COLS):
            counts = Counter(single_label(r) for _, r in df.iterrows())
            grand.update(counts)
            ordered = {c: counts.get(c, 0) for c in ["non_offensive", *OFFENSIVE_COLS]}
            print(f"  per-class (§9 single-label): {ordered}")
        else:
            print("  (offensive category columns not all present — none-offensive file?)")
            grand["non_offensive"] += len(df)

    print("\n=== GRAND TOTAL (all four files, §9 mapping) ===")
    ordered = {c: grand.get(c, 0) for c in ["non_offensive", *OFFENSIVE_COLS]}
    total = sum(ordered.values())
    offensive = total - ordered["non_offensive"]
    print(f"  n={total}: {ordered}")
    if total:
        print(f"  offensive total: {offensive} ({offensive/total:.1%})")


if __name__ == "__main__":
    main()
