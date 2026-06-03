#!/usr/bin/env python3
"""Quick per-style stats: match ratio distribution. Run after 03_run_ocr.py."""
import json
import sys
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

REPO = Path(__file__).resolve().parents[2]
recs = [
    json.loads(l)
    for l in (REPO / "data" / "ocr_validation" / "ocr_outputs.jsonl").read_text(encoding="utf-8").splitlines()
]

by_style = defaultdict(list)
for r in recs:
    ratio = SequenceMatcher(None, r["original_text"], r.get("ocr_text") or "").ratio()
    by_style[r["style_label"]].append((r["id"], ratio, r["original_text"], r.get("ocr_text", "") or ""))

print(f"\n=== Per-style match ratio (SequenceMatcher) — N={len(recs)} ===\n")
print(f"{'Style':<8} {'Mean':>8} {'Min':>8} {'Max':>8}  Good(≥95%)  OK(80-95%)  Poor(<80%)")
print("-" * 80)
for label in sorted(by_style):
    items = by_style[label]
    ratios = [r for _, r, _, _ in items]
    n = len(ratios)
    good = sum(1 for r in ratios if r >= 0.95)
    ok = sum(1 for r in ratios if 0.80 <= r < 0.95)
    poor = sum(1 for r in ratios if r < 0.80)
    print(f"{label:<8} {sum(ratios)/n:>7.1%} {min(ratios):>7.1%} {max(ratios):>7.1%}     "
          f"{good:>2}/{n}        {ok:>2}/{n}         {poor:>2}/{n}")

print("\n=== Worst case per style (for spot-checking) ===\n")
for label in sorted(by_style):
    items = by_style[label]
    worst = min(items, key=lambda x: x[1])
    print(f"[{label}] {worst[0]} — ratio {worst[1]:.1%}")
    print(f"    original: {worst[2]}")
    print(f"    ocr:      {worst[3]}")
    print()
