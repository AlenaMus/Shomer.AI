"""Estimate D12 training pool size and composition without running the full pipeline."""
import json
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).parents[2]

def count_jsonl(path):
    if not path.exists():
        return 0, Counter()
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return len(rows), Counter(r["label"] for r in rows)

sources = {
    "synth_kids": ROOT / "training/data/interim/synth_kids.jsonl",
    "synth_kids_noised_d12": ROOT / "training/data/interim/synth_kids_noised_d12.jsonl",
    "synth_codeswitch": ROOT / "training/data/interim/synth_codeswitch.jsonl",
    "train_current_d10": ROOT / "data/train.jsonl",
}

print("D12 pool additions vs D10:")
for name, path in sources.items():
    n, dist = count_jsonl(path)
    print(f"  {name}: {n} rows — {dict(dist)}")

# Current train breakdown
train_n, train_dist = count_jsonl(ROOT / "data/train.jsonl")
d12_n, d12_dist = count_jsonl(ROOT / "training/data/interim/synth_kids_noised_d12.jsonl")

print(f"\nD10 train rows: {train_n}")
print(f"D12 noise rows to add: {d12_n}")
print(f"D12 estimated net new rows (before dedup): {d12_n}")
print(f"D12 estimated train size (before dedup): ~{train_n + d12_n}")
print(f"\nD12 noise label distribution:")
for lbl in ["non_offensive", "abusive", "hate", "violence", "pornographic"]:
    cnt = d12_dist.get(lbl, 0)
    pct = cnt / max(d12_n, 1) * 100
    print(f"  {lbl:<20}: {cnt} ({pct:.0f}%)")

# Compare to current train distribution
print(f"\nD10 current train label distribution:")
for lbl in ["non_offensive", "abusive", "hate", "violence", "pornographic"]:
    cnt = train_dist.get(lbl, 0)
    pct = cnt / max(train_n, 1) * 100
    print(f"  {lbl:<20}: {cnt} ({pct:.0f}%)")
