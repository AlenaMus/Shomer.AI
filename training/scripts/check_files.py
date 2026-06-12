"""Check D12 files exist."""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).parents[2]
files = [
    "training/augment_kids_noise.py",
    "training/data/interim/synth_kids_noised_d12.jsonl",
    "training/prepare_data_dictabert.py",
    "plan-docs/decisions/data-pipeline.decision.md",
    "training/outputs/dictabert-offensive/HANDOFF.md",
]
for f in files:
    p = ROOT / f
    if p.exists():
        print(f"OK  {f}  ({p.stat().st_size:,} bytes)")
    else:
        print(f"MISSING  {f}")
