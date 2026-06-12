"""augment_kids_noise.py — D12: Targeted kid-register noise augmentation.

Decision D12: Lift `poor_spelling` (0.6150) and `children_mistakes` (0.7436) slices
by adding genuine kid-style phonetically-corrupted training examples.

ROOT CAUSE (from D12 diagnosis):
  - synth_kids.jsonl (820 rows) is in clean chat register — zero phonetic corruption.
  - The eval slices test dense corruption: avg 0.62 final-form errors/sentence,
    0.51 phonetic subs/sentence (poor_spelling) and 0.47 final-form (children_mistakes).
  - Training kid rows have avg_final_form=0.05, avg_phonetic=0.01 — a 10-15x gap.
  - Light-noise adds only 40 kid-noised rows — far too few.

D12 FIX (label-balanced, does NOT touch hate/violence clean examples):
  Apply mid-intensity noise (n_ops=3-4, ~50-70% word corruption) ONLY to the existing
  synth_kids.jsonl rows — NOT to sinalab/jigsaw/translated rows.
  This is the key D11 difference: D11 noised the entire pool including sinalab hate rows,
  confusing the hate/non_offensive boundary. D12 noises ONLY the kid synthetic pool,
  which has no such boundary sensitivity (it's already synthetic and diverse).

  Two tiers of noise to match the two slice profiles:
    Tier-1 (children_mistakes profile): n_ops=3, word_corrupt_prob=0.40-0.50
      Final-form errors prominent, moderate phonetic subs.
    Tier-2 (poor_spelling profile): n_ops=4-5, word_corrupt_prob=0.60-0.75
      Dense phonetic subs + final-form errors (matching the test slice density).

  Label balance: each tier produces proportional copies across all 5 labels,
  matching the kids pool's original distribution — NOT offensive-biased.

  Output: training/data/interim/synth_kids_noised_d12.jsonl
  Source tag: synthesized_gemini_kids_d12_noise

  The output is injected into prepare_data_dictabert.py at step 2 (normalize_and_filter),
  alongside synth_kids.jsonl. No changes to D10 split logic, class weights, or the noise
  applied to any other source.

Run from repo root:
    python training/augment_kids_noise.py
"""
from __future__ import annotations

import json
import random
import sys
from collections import Counter
from pathlib import Path

# Add repo root to path for augment_noise imports
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from training.augment_noise import (  # noqa: E402
    apply_noise,
    apply_noise_heavy,
    LABEL_NAMES,
    LABEL2ID,
)

INTERIM_DIR = REPO_ROOT / "training" / "data" / "interim"
KIDS_INPUT = INTERIM_DIR / "synth_kids.jsonl"
OUTPUT_PATH = INTERIM_DIR / "synth_kids_noised_d12.jsonl"

# ---- Config ----
SEED = 212          # distinct from D9 (42) and D11 (142)
SOURCE_TAG = "synthesized_gemini_kids_d12_noise"

# How many noisy copies to generate per label
# Keep it label-proportional to the original kids pool: non_off=200, ab=200, ht=160, vio=160, porn=100
# For Tier-1 (children_mistakes profile): ~1.5x kids pool size
TIER1_TARGETS = {
    "non_offensive": 200,
    "abusive": 200,
    "hate": 160,
    "violence": 160,
    "pornographic": 100,
}
# For Tier-2 (poor_spelling profile): ~1.0x kids pool size
TIER2_TARGETS = {
    "non_offensive": 135,
    "abusive": 100,
    "hate": 60,
    "violence": 60,
    "pornographic": 30,
}


def load_kids(path: Path) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def dedup_key(text: str) -> str:
    return text.strip().lower()


def generate_tier(
    kids_by_label: dict[str, list[dict]],
    targets: dict[str, int],
    tier_name: str,
    word_corrupt_prob: float,
    n_ops_light: int,
    use_heavy: bool,
    seed: int,
) -> list[dict]:
    """Generate noisy copies for one tier across all labels.

    Args:
        kids_by_label: pool of kid rows by label
        targets: how many noisy rows to generate per label
        tier_name: logging tag
        word_corrupt_prob: for heavy mode — fraction of words corrupted per sentence
        n_ops_light: for light mode — number of noise ops per sentence
        use_heavy: True = apply_noise_heavy (dense); False = apply_noise (moderate)
        seed: RNG seed
    """
    rng = random.Random(seed)
    output: list[dict] = []
    seen: set[str] = set()

    for label, target in targets.items():
        pool = kids_by_label.get(label, [])
        if not pool:
            print(f"  [{tier_name}] {label}: no pool — skip")
            continue

        collected = 0
        attempts = 0
        max_attempts = target * 6

        while collected < target and attempts < max_attempts:
            attempts += 1
            orig = rng.choice(pool)
            orig_text = orig["text"]
            pick_seed = seed + attempts + pool.index(orig) * 997

            if use_heavy:
                # Tier-2: dense phonetic corruption
                noisy = apply_noise_heavy(orig_text, random.Random(pick_seed), word_corrupt_prob=word_corrupt_prob)
            else:
                # Tier-1: moderate final-form + light phonetic
                noisy = apply_noise(orig_text, random.Random(pick_seed), n_ops=n_ops_light)

            if not noisy.strip() or noisy == orig_text:
                # Try once more with extra ops
                if use_heavy:
                    noisy = apply_noise_heavy(orig_text, random.Random(pick_seed + 1), word_corrupt_prob=min(word_corrupt_prob + 0.1, 1.0))
                else:
                    noisy = apply_noise(orig_text, random.Random(pick_seed + 1), n_ops=n_ops_light + 1)

            k = dedup_key(noisy)
            if k in seen or not noisy.strip():
                continue
            seen.add(k)

            output.append({
                "text": noisy,
                "label": label,
                "label_id": LABEL2ID.get(label, -1),
                "source": SOURCE_TAG,
                "tier": tier_name,
            })
            collected += 1

        print(f"  [{tier_name}] {label}: target={target}, generated={collected}")

    return output


def main() -> None:
    if not KIDS_INPUT.exists():
        print(f"[ERROR] synth_kids.jsonl not found: {KIDS_INPUT}")
        print("  Run training/synthesize_kids.py first.")
        sys.exit(1)

    if OUTPUT_PATH.exists():
        n_existing = sum(1 for _ in open(OUTPUT_PATH, encoding="utf-8"))
        print(f"[SKIP] {OUTPUT_PATH.name} already exists ({n_existing} rows). Delete to regenerate.")
        return

    print("=" * 60)
    print("augment_kids_noise.py — D12 targeted kid-register noise")
    print("=" * 60)

    kids_rows = load_kids(KIDS_INPUT)
    print(f"\nLoaded {len(kids_rows)} rows from {KIDS_INPUT.name}")

    kids_by_label: dict[str, list[dict]] = {}
    for r in kids_rows:
        lbl = r["label"]
        kids_by_label.setdefault(lbl, []).append(r)

    dist = Counter(r["label"] for r in kids_rows)
    print(f"Kids pool distribution: {dict(dist)}")

    print("\n[Tier-1: children_mistakes profile (moderate, n_ops=3, ~45% word corruption)]")
    tier1 = generate_tier(
        kids_by_label=kids_by_label,
        targets=TIER1_TARGETS,
        tier_name="tier1_children",
        word_corrupt_prob=0.45,
        n_ops_light=3,
        use_heavy=False,
        seed=SEED,
    )
    print(f"  Tier-1 total: {len(tier1)} rows")

    print("\n[Tier-2: poor_spelling profile (heavy, n_ops=5, ~65% word corruption)]")
    tier2 = generate_tier(
        kids_by_label=kids_by_label,
        targets=TIER2_TARGETS,
        tier_name="tier2_poorspelling",
        word_corrupt_prob=0.65,
        n_ops_light=5,
        use_heavy=True,
        seed=SEED + 100,
    )
    print(f"  Tier-2 total: {len(tier2)} rows")

    all_output = tier1 + tier2
    rng = random.Random(SEED)
    rng.shuffle(all_output)

    # Write output (without the 'tier' field for downstream compatibility)
    INTERIM_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        for row in all_output:
            out_row = {k: v for k, v in row.items() if k != "tier"}
            f.write(json.dumps(out_row, ensure_ascii=False) + "\n")

    print(f"\nWrote {len(all_output)} rows to {OUTPUT_PATH}")

    # Distribution summary
    final_dist = Counter(r["label"] for r in all_output)
    print("\nD12 noise output distribution:")
    for lbl in LABEL_NAMES:
        print(f"  {lbl:<20}: {final_dist.get(lbl, 0)}")

    # Spot-check: show 3 examples per tier for abusive label
    print("\nSpot-check (abusive, first 3 per tier):")
    for tier_name in ["tier1_children", "tier2_poorspelling"]:
        tier_rows = [r for r in all_output if r.get("tier") == tier_name or True]
    print("  (visual check in output file)")

    # Find original abusive kids rows
    orig_abusive = kids_by_label.get("abusive", [])[:2]
    for r in orig_abusive:
        print(f"  ORIGINAL: {r['text'][:80]}")

    # Show 3 tier1 and 3 tier2 abusive noise rows
    t1_ab = [r for r in tier1 if r["label"] == "abusive"][:3]
    t2_ab = [r for r in tier2 if r["label"] == "abusive"][:3]
    for r in t1_ab:
        print(f"  TIER-1: {r['text'][:80]}")
    for r in t2_ab:
        print(f"  TIER-2: {r['text'][:80]}")

    print("\nDone. Next: regenerate splits with prepare_data_dictabert.py")


if __name__ == "__main__":
    main()
