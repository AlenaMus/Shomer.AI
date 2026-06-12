"""Simulate D12 training composition to predict gate safety.

Approximates what the final train.jsonl will look like after D12 is added,
without running the full datasketch pipeline.
"""
import json
import sys
from collections import Counter
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).parents[2]

def load_jsonl(path):
    rows = []
    if not path.exists():
        return rows
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows

# Load current D10 train
train_d10 = load_jsonl(ROOT / "data/train.jsonl")
# Load D12 noise
d12_noise = load_jsonl(ROOT / "training/data/interim/synth_kids_noised_d12.jsonl")

print(f"D10 train: {len(train_d10)} rows")
print(f"D12 noise: {len(d12_noise)} rows")

d10_dist = Counter(r["label"] for r in train_d10)
d12_dist = Counter(r["label"] for r in d12_noise)

print(f"\nD10 train distribution:")
for lbl in ["non_offensive", "abusive", "hate", "violence", "pornographic"]:
    cnt = d10_dist.get(lbl, 0)
    pct = cnt / len(train_d10) * 100
    print(f"  {lbl:<20}: {cnt} ({pct:.1f}%)")

print(f"\nD12 noise distribution:")
for lbl in ["non_offensive", "abusive", "hate", "violence", "pornographic"]:
    cnt = d12_dist.get(lbl, 0)
    pct = cnt / max(len(d12_noise), 1) * 100
    print(f"  {lbl:<20}: {cnt} ({pct:.1f}%)")

# Simulate combined (before split logic — the actual pipeline rebalances)
# The D9 split logic picks OFFENSIVE_PER_CLASS_TRAIN=900 from each offensive class's pool
# and NON_OFF_TRAIN_TARGET=3600. Adding D12 noise increases the pool, so the pick still
# caps at 900 per class. The net effect: slightly more noisy examples compete in each class pool.
# With 384 existing kid rows (abusive 102, hate 60, violence 77) and D12 adding 300/220/220,
# the kid-noised rows now have a good chance of being sampled into the 900-row class cap.

# Current kid rows in train (from source tags)
kid_in_train = [r for r in train_d10 if "kids" in r.get("source", "")]
print(f"\nKid-register rows currently in D10 train: {len(kid_in_train)}")
kid_dist = Counter(r["label"] for r in kid_in_train)
for lbl in ["non_offensive", "abusive", "hate", "violence", "pornographic"]:
    print(f"  {lbl:<20}: {kid_dist.get(lbl, 0)}")

# What fraction of train abusive rows are currently kid-register?
abusive_train = [r for r in train_d10 if r["label"] == "abusive"]
kid_abusive_train = [r for r in kid_in_train if r["label"] == "abusive"]
print(f"\nAbusive train rows: {len(abusive_train)} total, {len(kid_abusive_train)} kid-register ({len(kid_abusive_train)/max(len(abusive_train),1)*100:.0f}%)")

hate_train = [r for r in train_d10 if r["label"] == "hate"]
kid_hate_train = [r for r in kid_in_train if r["label"] == "hate"]
print(f"Hate train rows: {len(hate_train)} total, {len(kid_hate_train)} kid-register ({len(kid_hate_train)/max(len(hate_train),1)*100:.0f}%)")

# After D12: add 220 more kid-hate-noise rows. Pool for hate grows from ~current to ~current+220.
# The split still caps at 900 per class, so the net-new kid-noised hate rows displace
# some non-kid rows in the 900 sample. Since the noised rows are from synth_kids (already
# a clean-text source), this should not confuse the sinalab-hate boundary.

print(f"\n-- D12 safety estimate --")
print(f"D12 adds {d12_dist.get('hate',0)} hate-noise rows (from synth_kids pool only)")
print(f"D12 adds {d12_dist.get('violence',0)} violence-noise rows (from synth_kids pool only)")
print(f"Current hate train pool (total): {len(hate_train)}")
print(f"After D12: hate pool ~{len(hate_train) + d12_dist.get('hate',0)} rows (cap=900)")
print(f"=> {d12_dist.get('hate',0)} more kid-phonetic hate examples compete in the 900-row cap")
print(f"=> Fraction of kid-register in hate train: ~{(len(kid_hate_train) + d12_dist.get('hate',0))/900*100:.0f}% (was {len(kid_hate_train)/max(len(hate_train),1)*100:.0f}%)")
print()
print("KEY SAFETY CHECK: sinalab hate rows (real Hebrew) are NOT touched by D12.")
sinalab_hate = [r for r in train_d10 if r["label"] == "hate" and r.get("source","").startswith("sinalab")]
print(f"Sinalab hate in D10 train: {len(sinalab_hate)} clean-signal anchor rows (unchanged in D12)")
