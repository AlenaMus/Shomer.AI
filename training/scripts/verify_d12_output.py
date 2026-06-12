"""Verify synth_kids_noised_d12.jsonl output quality."""
import json
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).parents[2]
output_path = ROOT / "training" / "data" / "interim" / "synth_kids_noised_d12.jsonl"
kids_path = ROOT / "training" / "data" / "interim" / "synth_kids.jsonl"

if not output_path.exists():
    print(f"NOT FOUND: {output_path}")
    sys.exit(1)

rows = []
with open(output_path, encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line:
            rows.append(json.loads(line))

kids_rows = []
with open(kids_path, encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line:
            kids_rows.append(json.loads(line))

print(f"D12 output: {len(rows)} rows")
dist = Counter(r["label"] for r in rows)
print(f"Distribution: {dict(dist)}")

# Source check
src = Counter(r.get("source") for r in rows)
print(f"Source: {dict(src)}")

# Show samples for each label
print("\n=== Sample pairs: original kid text vs D12 noised version ===")
kids_by_label = {}
for r in kids_rows:
    kids_by_label.setdefault(r["label"], []).append(r)

for label in ["abusive", "hate", "violence", "non_offensive"]:
    print(f"\n--- {label} ---")
    orig = kids_by_label.get(label, [])
    d12_rows = [r for r in rows if r["label"] == label]

    # Show 3 originals and their noised versions (approximate pairs)
    for i in range(min(3, len(orig), len(d12_rows))):
        print(f"  ORIGINAL: {orig[i]['text'][:90]}")
        print(f"  D12-NOISE: {d12_rows[i]['text'][:90]}")
        print()

# Label validity check
invalid = [r for r in rows if r["label"] not in {"non_offensive","abusive","hate","violence","pornographic"}]
print(f"Label validity: {len(invalid)} invalid rows (should be 0)")

# Check no exact overlap with original kids rows
kids_keys = {r["text"].strip().lower() for r in kids_rows}
overlap = sum(1 for r in rows if r["text"].strip().lower() in kids_keys)
print(f"Exact overlap with original kids rows: {overlap} (should be near 0)")
