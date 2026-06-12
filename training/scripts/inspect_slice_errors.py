"""Show sample texts from poor_spelling and children_mistakes slices, by label."""
import json
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).parents[2]
eval_path = ROOT / "data" / "stylistic_eval.jsonl"

rows = []
with open(eval_path, encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if line:
            rows.append(json.loads(line))

for style in ["poor_spelling", "children_mistakes"]:
    style_rows = [r for r in rows if r.get("style") == style]
    dist = Counter(r["label"] for r in style_rows)
    print(f"\n{'='*60}")
    print(f"STYLE: {style}  ({len(style_rows)} total)")
    print(f"Label dist: {dict(dist)}")
    for lbl in ["non_offensive", "abusive", "hate", "violence", "pornographic"]:
        lbl_rows = [r for r in style_rows if r["label"] == lbl]
        print(f"\n  --- {lbl} ({len(lbl_rows)} rows) ---")
        for r in lbl_rows[:8]:
            print(f"    {r['text'][:120]}")
