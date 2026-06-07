"""Stage-0 reconnaissance: load SinaLab/Offensive-Hebrew and report real structure.

Run in WSL2 training venv:
    source ~/shomer-training-venv/bin/activate
    python training/scripts/inspect_sinalab.py

Reports: splits, columns, dtypes, a few sample rows, and the real per-class counts
under the §9 severity-priority single-label mapping (violence > hate > pornographic > abusive).
This is the number that decides how starved the minority classes actually are.
"""
from __future__ import annotations

from collections import Counter

from datasets import load_dataset

DATASET = "SinaLab/Offensive-Hebrew"
OFFENSIVE_COLS = ["abusive", "hate", "violence", "pornographic"]
# §9 severity priority (most severe wins when multiple flags set)
SEVERITY = ["violence", "hate", "pornographic", "abusive"]


def to_single_label(row: dict) -> str:
    flagged = [c for c in OFFENSIVE_COLS if int(row.get(c, 0) or 0) == 1]
    if not flagged:
        return "non_offensive"
    for c in SEVERITY:
        if c in flagged:
            return c
    return flagged[0]


def main() -> None:
    print(f"Loading {DATASET} ...")
    ds = load_dataset(DATASET)
    print("\n=== SPLITS ===")
    for split in ds:
        print(f"  {split}: {len(ds[split])} rows")

    first_split = next(iter(ds))
    feats = ds[first_split].features
    print(f"\n=== COLUMNS ({first_split}) ===")
    for name, ft in feats.items():
        print(f"  {name}: {ft}")

    print("\n=== 3 SAMPLE ROWS ===")
    for i in range(min(3, len(ds[first_split]))):
        row = ds[first_split][i]
        # truncate long text fields for readability
        shown = {k: (v[:80] + "…" if isinstance(v, str) and len(v) > 80 else v) for k, v in row.items()}
        print(f"  [{i}] {shown}")

    print("\n=== REAL PER-CLASS COUNTS (single-label, §9 mapping) ===")
    grand = Counter()
    for split in ds:
        counts = Counter(to_single_label(r) for r in ds[split])
        grand.update(counts)
        ordered = {c: counts.get(c, 0) for c in ["non_offensive", *OFFENSIVE_COLS]}
        total = sum(ordered.values())
        print(f"  {split} (n={total}): {ordered}")

    print("\n=== GRAND TOTAL ===")
    ordered = {c: grand.get(c, 0) for c in ["non_offensive", *OFFENSIVE_COLS]}
    total = sum(ordered.values())
    offensive = total - ordered["non_offensive"]
    print(f"  all (n={total}): {ordered}")
    print(f"  offensive total: {offensive}  ({offensive/total:.1%})")


if __name__ == "__main__":
    main()
