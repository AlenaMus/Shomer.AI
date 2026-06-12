"""Inspect train.jsonl source composition — how many kid-register rows exist."""
import json
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).parents[2]
train_path = ROOT / "data" / "train.jsonl"

if not train_path.exists():
    print(f"NOT FOUND: {train_path}")
    sys.exit(1)

rows = []
with open(train_path, encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line:
            rows.append(json.loads(line))

print(f"Total train rows: {len(rows)}")

# By source
source_dist = Counter(r.get("source", "unknown") for r in rows)
print("\nBy source (sorted by count):")
for src, cnt in source_dist.most_common():
    print(f"  {src}: {cnt}")

# Kid-register sources
kid_sources = [s for s in source_dist if "kids" in s or "synth_kids" in s]
noise_sources = [s for s in source_dist if "noise" in s]
code_sources = [s for s in source_dist if "code" in s or "switch" in s]

print(f"\nKid-register rows (synthesized_gemini_kids*): {sum(source_dist[s] for s in kid_sources)}")
for s in kid_sources:
    print(f"  {s}: {source_dist[s]}")

print(f"\nNoise-augmented rows (*_noise): {sum(source_dist[s] for s in noise_sources)}")
for s in noise_sources:
    print(f"  {s}: {source_dist[s]}")

print(f"\nCode-switch rows: {sum(source_dist[s] for s in code_sources)}")
for s in code_sources:
    print(f"  {s}: {source_dist[s]}")

# Kids rows by label
print("\nKid-register rows by label:")
for src in kid_sources:
    kid_rows = [r for r in rows if r.get("source") == src]
    lbl_dist = Counter(r["label"] for r in kid_rows)
    print(f"  {src}:")
    for lbl, cnt in sorted(lbl_dist.items()):
        print(f"    {lbl}: {cnt}")
