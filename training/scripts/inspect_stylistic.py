"""Inspect stylistic_eval.jsonl slice composition."""
import json
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).parents[2]
path = ROOT / "data" / "stylistic_eval.jsonl"

slices = {}
samples = {}  # store first 3 examples per style
with open(path, encoding="utf-8") as f:
    for line in f:
        row = json.loads(line)
        style = row.get("style", "unknown")
        label = row["label"]
        if style not in slices:
            slices[style] = Counter()
            samples[style] = []
        slices[style][label] += 1
        if len(samples[style]) < 3:
            samples[style].append(row)

for style, counter in sorted(slices.items()):
    total = sum(counter.values())
    print(f"\n=== {style}: {total} rows ===")
    for lbl, cnt in sorted(counter.items()):
        print(f"  {lbl}: {cnt}")
    print("  Sample texts:")
    for row in samples[style]:
        text = row["text"][:80]
        print(f"    [{row['label']}] {text}")

print(f"\nTotal: {sum(sum(c.values()) for c in slices.values())}")
