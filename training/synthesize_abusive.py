"""synthesize_abusive.py — Gemini-based Hebrew synthesis for the abusive class.

Stage-3 data augmentation: the abusive class is the bottleneck after Stage-2
training (F1=0.46, bottleneck for macro-F1 gate). This script generates ~800
abusive Hebrew examples seeded from SinaLab real abusive rows.

Abusive (per SinaLab): personal insults, verbal attacks, profanity directed at
individuals or small groups — DISTINCT from hate (group-based dehumanization)
and violence (threats/calls to harm). Register: Israeli social-media insults.

Seeds: real SinaLab abusive examples (119 rows in SinaLab + textdetox pool).
QA:    cosine near-dedup (threshold=0.85), 10% QA sample.

Output:
  - training/data/interim/synth_abusive.jsonl
    schema: {text, label:"abusive", label_id:1, source:"synthesized_gemini"}
  - training/data/interim/qa_synth_abusive_sample.jsonl
    10% QA sample with generation metadata

Guardrails:
  - No real named private individuals as incitement targets.
  - No content involving minors.
  - Personal/crude insults only; stop before crossing into hate-speech
    (group-targeted dehumanization) or violence (harm threats).

Behavior: skip-if-exists (idempotent).
Run in WSL2 training venv from repo root:
    python training/synthesize_abusive.py
"""
from __future__ import annotations

import json
import random
import re
import time
import unicodedata
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
INTERIM_DIR = REPO_ROOT / "training" / "data" / "interim"
SINALAB_CSV = REPO_ROOT / "training" / "data" / "raw" / "sinalab" / "AllData_OffensiveHebrew.csv"
OUTPUT_PATH = INTERIM_DIR / "synth_abusive.jsonl"
QA_PATH = INTERIM_DIR / "qa_synth_abusive_sample.jsonl"

INTERIM_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
LABEL2ID = {
    "non_offensive": 0,
    "abusive": 1,
    "hate": 2,
    "violence": 3,
    "pornographic": 4,
}

TARGET_ABUSIVE = 800              # ~800 synthetic abusive rows
NUM_FEW_SHOT_SEEDS = 6
BATCH_SIZE = 10
COSINE_DEDUP_THRESHOLD = 0.85

# ---------------------------------------------------------------------------
# Text normalization (matches prepare_data_dictabert.py)
# ---------------------------------------------------------------------------
_NIKUD_RE = re.compile(r"[֑-ׇ]")
_DIR_CTRL_RE = re.compile(r"[‎‏‪-‮⁦-⁩]")
_URL_RE = re.compile(r"https?://\S+|www\.\S+")
_MENTION_RE = re.compile(r"@[\w_]+")
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = _NIKUD_RE.sub("", text)
    text = _DIR_CTRL_RE.sub("", text)
    text = _URL_RE.sub("[URL]", text)
    text = _MENTION_RE.sub("[MENTION]", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text


def passes_length_filter(text: str, min_tok: int = 3, max_tok: int = 200) -> bool:
    return min_tok <= len(text.split()) <= max_tok


# ---------------------------------------------------------------------------
# Load SinaLab abusive seeds
# ---------------------------------------------------------------------------
def load_sinalab_abusive_seeds(verbose: bool = True) -> list[str]:
    """Return abusive examples from SinaLab AllData CSV."""
    import pandas as pd  # noqa: PLC0415

    df = pd.read_csv(SINALAB_CSV, encoding="utf-8")
    abusive_seeds: list[str] = []

    for _, row in df.iterrows():
        label_raw = str(row.get("Label", "") or "").strip().lower()
        text = str(row.get("TweetText", "") or "").strip()
        if not text:
            continue
        text = normalize_text(text)
        if not passes_length_filter(text):
            continue

        # Match abusive but NOT hate/violence — keep label boundary clean
        if "abusive" in label_raw and "hate" not in label_raw and "violence" not in label_raw:
            abusive_seeds.append(text)

    if verbose:
        print(f"  SinaLab abusive seeds: {len(abusive_seeds)} rows")

    return abusive_seeds


# ---------------------------------------------------------------------------
# Synthesis prompt
# ---------------------------------------------------------------------------
_ABUSIVE_SYSTEM = (
    "You are a researcher creating a Hebrew abusive-language dataset for AI safety training. "
    "Generate realistic examples of Israeli social-media personal insults and crude verbal attacks "
    "based on the provided seeds. These examples train classifiers to DETECT abusive content.\n\n"
    "TARGET CLASS — ABUSIVE (not hate, not violence):\n"
    "  - Personal insults directed at individuals or their character (stupid, worthless, etc.)\n"
    "  - Crude profanity and name-calling in social-media arguments\n"
    "  - Dismissive, demeaning language aimed at a person or their opinion\n"
    "  - Verbally aggressive but NOT: group-based hate speech, dehumanization of ethnic/religious\n"
    "    groups (that is hate speech), or threats to harm someone (that is violence)\n\n"
    "HARD RULES:\n"
    "1. No real named private individuals as incitement targets.\n"
    "2. No content involving minors.\n"
    "3. Stay in the ABUSIVE category: personal insults only; do not drift into hate speech "
    "(racial/ethnic dehumanization) or violence (threats/calls to harm).\n"
    "4. Vary phrasing — do NOT repeat or slightly rephrase seeds.\n"
    "5. Social-media Israeli Hebrew (colloquial, 5–50 words).\n"
    "6. Return ONLY valid JSON with key 'examples': [str, str, ...] (exactly {batch_size} items).\n"
)

_GENERATION_PROMPT_TEMPLATE = (
    "Generate {batch_size} new abusive Hebrew examples DIFFERENT from these seeds:\n\n"
    "Seeds:\n{seeds}\n\n"
    "Generate {batch_size} NEW distinct abusive examples (personal insults, NOT group hate, "
    "NOT violence threats). Return JSON: {{\"examples\": [...]}}"
)


def _make_seed_block(seeds: list[str], n: int, rng: random.Random) -> str:
    sample = rng.sample(seeds, min(n, len(seeds)))
    return "\n".join(f"{i + 1}. {s}" for i, s in enumerate(sample))


# ---------------------------------------------------------------------------
# Cosine near-dedup (same as synthesize_hate_violence.py)
# ---------------------------------------------------------------------------
def cosine_dedup(
    new_texts: list[str],
    existing_texts: list[str],
    threshold: float = COSINE_DEDUP_THRESHOLD,
) -> list[str]:
    """Remove texts too similar (cosine >= threshold) to any existing text."""
    if not existing_texts:
        if not new_texts:
            return []
        try:
            from sklearn.feature_extraction.text import TfidfVectorizer  # noqa: PLC0415
            from sklearn.metrics.pairwise import cosine_similarity  # noqa: PLC0415

            vec = TfidfVectorizer(analyzer="char", ngram_range=(3, 3), max_features=20000)
            mat = vec.fit_transform(new_texts)
            kept: list[str] = []
            kept_indices: list[int] = []
            for i, text in enumerate(new_texts):
                if not kept_indices:
                    kept.append(text)
                    kept_indices.append(i)
                    continue
                sims = cosine_similarity(mat[i], mat[kept_indices])[0]
                if sims.max() < threshold:
                    kept.append(text)
                    kept_indices.append(i)
            return kept
        except Exception:
            return new_texts

    try:
        from sklearn.feature_extraction.text import TfidfVectorizer  # noqa: PLC0415
        from sklearn.metrics.pairwise import cosine_similarity  # noqa: PLC0415

        all_texts = existing_texts + new_texts
        vec = TfidfVectorizer(analyzer="char", ngram_range=(3, 3), max_features=20000)
        mat = vec.fit_transform(all_texts)
        n_existing = len(existing_texts)
        kept: list[str] = []
        for i, text in enumerate(new_texts):
            idx = n_existing + i
            sims_existing = cosine_similarity(mat[idx], mat[:n_existing])[0]
            if sims_existing.max() >= threshold:
                continue
            if kept:
                kept_mat = vec.transform(kept)
                sims_kept = cosine_similarity(mat[idx], kept_mat)[0]
                if sims_kept.max() >= threshold:
                    continue
            kept.append(text)
        return kept
    except Exception:
        return new_texts


# ---------------------------------------------------------------------------
# Generate batch
# ---------------------------------------------------------------------------
def _generate_batch(
    gemini,
    seeds: list[str],
    batch_size: int,
    rng: random.Random,
) -> list[str]:
    seed_block = _make_seed_block(seeds, NUM_FEW_SHOT_SEEDS, rng)
    prompt = _GENERATION_PROMPT_TEMPLATE.format(
        batch_size=batch_size,
        seeds=seed_block,
    )
    try:
        result = gemini.call_json(
            messages=[
                {"role": "system", "content": _ABUSIVE_SYSTEM.format(batch_size=batch_size)},
                {"role": "user", "content": prompt},
            ],
            max_tokens=1024,
            temperature=0.8,
        )
        examples = result.get("examples", [])
        if isinstance(examples, list):
            return [str(e).strip() for e in examples if str(e).strip()]
        return []
    except Exception as exc:  # noqa: BLE001
        print(f"  [WARN] Batch generation failed: {exc}")
        return []


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    print("=" * 60)
    print("Stage-3 abusive synthesis — SinaLab abusive F1 fix")
    print("=" * 60)

    if OUTPUT_PATH.exists():
        count = sum(1 for _ in OUTPUT_PATH.open("r", encoding="utf-8"))
        print(f"\n[CACHE HIT] {OUTPUT_PATH} exists ({count} rows). Delete to re-run.")
        return

    import sys  # noqa: PLC0415
    sys.path.insert(0, str(REPO_ROOT))
    from training.gemini_utils import GeminiSync  # noqa: PLC0415

    gemini = GeminiSync()
    rng = random.Random(42)

    print("\n[1/3] Loading SinaLab abusive seeds...")
    seeds = load_sinalab_abusive_seeds(verbose=True)

    if not seeds:
        raise RuntimeError("No SinaLab abusive seeds found — cannot proceed.")

    print(f"\n[2/3] Synthesizing {TARGET_ABUSIVE} abusive examples...")
    kept: list[str] = []
    attempts = 0
    max_attempts = int(TARGET_ABUSIVE * 3.5 / BATCH_SIZE) + 20

    while len(kept) < TARGET_ABUSIVE and attempts < max_attempts:
        batch = _generate_batch(gemini, seeds, BATCH_SIZE, rng)
        attempts += 1

        # Normalize + length filter
        batch = [normalize_text(b) for b in batch]
        batch = [b for b in batch if passes_length_filter(b)]

        # Exact dedup against kept
        existing_set = {b.lower() for b in kept}
        batch = [b for b in batch if b.lower() not in existing_set]

        # Cosine near-dedup
        batch = cosine_dedup(batch, kept)

        kept.extend(batch)

        if attempts % 10 == 0:
            print(f"  Progress: attempt={attempts}, kept={len(kept)}/{TARGET_ABUSIVE}")

        time.sleep(0.3)

    kept = kept[:TARGET_ABUSIVE]
    print(f"\n  Synthesis complete: {len(kept)} abusive rows in {attempts} attempts")

    # Write output
    rows = [
        {
            "text": t,
            "label": "abusive",
            "label_id": LABEL2ID["abusive"],
            "source": "synthesized_gemini",
        }
        for t in kept
    ]

    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"  Wrote {len(rows)} rows to {OUTPUT_PATH}")

    # QA sample
    print("\n[3/3] Writing QA sample (10%)...")
    sample_size = max(10, len(rows) // 10)
    qa_sample = rng.sample(rows, min(sample_size, len(rows)))
    with QA_PATH.open("w", encoding="utf-8") as f:
        for row in qa_sample:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"  Wrote {len(qa_sample)} QA rows to {QA_PATH}")

    print(
        "\nDone. Next: re-run training/prepare_data_dictabert.py (Stage-3) "
        "to incorporate the new abusive data, then re-train."
    )


if __name__ == "__main__":
    import sys  # noqa: PLC0415
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    main()
