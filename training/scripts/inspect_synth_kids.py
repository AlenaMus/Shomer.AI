"""Inspect synth_kids.jsonl composition and sample texts."""
import json
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).parents[2]
path = ROOT / "training" / "data" / "interim" / "synth_kids.jsonl"

if not path.exists():
    print(f"NOT FOUND: {path}")
    sys.exit(1)

rows = []
with open(path, encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line:
            rows.append(json.loads(line))

dist = Counter(r["label"] for r in rows)
print(f"Total rows: {len(rows)}")
print("Label distribution:")
for lbl, cnt in sorted(dist.items()):
    print(f"  {lbl}: {cnt}")

# Show 5 samples per label
print("\nSamples per label:")
for lbl in sorted(dist.keys()):
    label_rows = [r for r in rows if r["label"] == lbl]
    print(f"\n=== {lbl} (first 5) ===")
    for r in label_rows[:5]:
        print(f"  {r['text'][:100]}")
