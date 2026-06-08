"""synthesize_hate_violence.py — Gemini-based Hebrew synthesis for hate + violence classes.

Stage-2 Task 2: Generate ~1,000 hate + ~1,000 violence Hebrew examples matched to the
SinaLab Israel/Palestine political-ethnic distribution.

Seeds: real SinaLab hate/violence examples (few-shot prompts preserve the register).
QA:    diversity-dedup (cosine>0.85 / exact dups), 10% sample back-check.

Output:
  - training/data/interim/synth_hate_violence.jsonl
    schema: {text, label, label_id, source:"synthesized_gemini"}
  - training/data/interim/qa_synth_hv_sample.jsonl
    10% QA sample with generation metadata

Guardrails:
  - No real personal targets that constitute actionable incitement against a named
    private individual.
  - Representative of documented Israeli-Palestinian online discourse patterns,
    not operational threat planning.
  - No CSAM or content involving minors.

Behavior: skip-if-exists (idempotent / cache-friendly).
Run in WSL2 training venv from repo root:
    python training/synthesize_hate_violence.py
"""
from __future__ import annotations

import json
import random
import re
import time
import unicodedata
from collections import Counter
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
INTERIM_DIR = REPO_ROOT / "training" / "data" / "interim"
SINALAB_CSV = REPO_ROOT / "training" / "data" / "raw" / "sinalab" / "AllData_OffensiveHebrew.csv"
OUTPUT_PATH = INTERIM_DIR / "synth_hate_violence.jsonl"
QA_PATH = INTERIM_DIR / "qa_synth_hv_sample.jsonl"

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

TARGET_HATE = 1000
TARGET_VIOLENCE = 1000
NUM_FEW_SHOT_SEEDS = 6          # seeds shown in each prompt
BATCH_SIZE = 10                  # examples per Gemini call
COSINE_DEDUP_THRESHOLD = 0.85   # drop if cosine sim to any kept row > this

# ---------------------------------------------------------------------------
# Text normalization (match prepare_data_dictabert.py)
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
# Load SinaLab few-shot seeds
# ---------------------------------------------------------------------------
def load_sinalab_seeds(verbose: bool = True) -> tuple[list[str], list[str]]:
    """Return (hate_seeds, violence_seeds) from SinaLab AllData CSV."""
    import pandas as pd  # noqa: PLC0415

    df = pd.read_csv(SINALAB_CSV, encoding="utf-8")
    hate_seeds: list[str] = []
    violence_seeds: list[str] = []

    for _, row in df.iterrows():
        label_raw = str(row.get("Label", "") or "").strip().lower()
        text = str(row.get("TweetText", "") or "").strip()
        if not text:
            continue
        # Normalize and filter
        text = normalize_text(text)
        if not passes_length_filter(text):
            continue

        if any(x in label_raw for x in ("hate", "racism", "racist")):
            hate_seeds.append(text)
        elif "violence" in label_raw:
            violence_seeds.append(text)

    if verbose:
        print(f"  SinaLab seeds loaded: hate={len(hate_seeds)}, violence={len(violence_seeds)}")

    return hate_seeds, violence_seeds


# ---------------------------------------------------------------------------
# Synthesis prompts
# ---------------------------------------------------------------------------
_HATE_SYSTEM = (
    "You are a researcher creating a Hebrew hate speech dataset for AI safety training. "
    "Generate realistic examples of Israeli social-media hate speech based on the provided seeds. "
    "These examples train classifiers to DETECT hate speech — they are not endorsements.\n\n"
    "TARGET DISTRIBUTION: Israeli/Palestinian political-ethnic hate speech (Arabs, Jews, settlers, "
    "Palestinians, leftists, rightists, specific religious or ethnic groups). "
    "Dehumanization, ethnic slurs, calls for expulsion, group-based hatred.\n\n"
    "HARD RULES:\n"
    "1. No real named private individuals as targets of incitement.\n"
    "2. No content involving minors.\n"
    "3. Vary the phrasing — do NOT repeat or slightly rephrase the seeds.\n"
    "4. Social-media Hebrew (colloquial, tweets/comments style, 8–60 words).\n"
    "5. Return ONLY valid JSON with key 'examples': [str, str, ...] (exactly {batch_size} items).\n"
)

_VIOLENCE_SYSTEM = (
    "You are a researcher creating a Hebrew violent-threat dataset for AI safety training. "
    "Generate realistic examples of Israeli social-media threats and calls to violence based on the provided seeds. "
    "These examples train classifiers to DETECT violent content — they are not endorsements.\n\n"
    "TARGET DISTRIBUTION: Threats to harm/kill, calls for violence against groups or figures, "
    "glorification of violent acts, explicit harm wishes — in the context of Israeli public discourse.\n\n"
    "HARD RULES:\n"
    "1. No actionable operational plans targeting real named private individuals.\n"
    "2. No content involving minors.\n"
    "3. Vary the phrasing — do NOT repeat or slightly rephrase the seeds.\n"
    "4. Social-media Hebrew (colloquial, tweets/comments style, 8–60 words).\n"
    "5. Return ONLY valid JSON with key 'examples': [str, str, ...] (exactly {batch_size} items).\n"
)

_GENERATION_PROMPT_TEMPLATE = (
    "Generate {batch_size} new examples that are DIFFERENT from these seeds but follow the same register:\n\n"
    "Seeds:\n{seeds}\n\n"
    "Generate {batch_size} NEW distinct examples. Return JSON: {{\"examples\": [...]}}"
)


def _make_seed_block(seeds: list[str], n: int, rng: random.Random) -> str:
    sample = rng.sample(seeds, min(n, len(seeds)))
    return "\n".join(f"{i + 1}. {s}" for i, s in enumerate(sample))


# ---------------------------------------------------------------------------
# Cosine near-dedup
# ---------------------------------------------------------------------------
def _build_tfidf_matrix(texts: list[str]):
    """Build TF-IDF char-3gram matrix for cosine similarity dedup."""
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer  # noqa: PLC0415
        vec = TfidfVectorizer(analyzer="char", ngram_range=(3, 3), max_features=20000)
        matrix = vec.fit_transform(texts)
        return matrix, vec
    except Exception:
        return None, None


def cosine_dedup(
    new_texts: list[str],
    existing_texts: list[str],
    threshold: float = COSINE_DEDUP_THRESHOLD,
) -> list[str]:
    """Remove texts that are too similar (cosine >= threshold) to any existing text."""
    if not existing_texts:
        # Dedup within new_texts only
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
                kept_mat = mat[kept_indices]
                sims = cosine_similarity(mat[i], kept_mat)[0]
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
            # Check against existing
            sims_existing = cosine_similarity(mat[idx], mat[:n_existing])[0]
            if sims_existing.max() >= threshold:
                continue
            # Check against already-kept new texts
            if kept:
                kept_mat = vec.transform(kept)
                sims_kept = cosine_similarity(mat[idx], kept_mat)[0]
                if sims_kept.max() >= threshold:
                    continue
            kept.append(text)
        return kept
    except Exception:
        # Fallback: no dedup
        return new_texts


# ---------------------------------------------------------------------------
# Generate batch
# ---------------------------------------------------------------------------
def _generate_batch(
    gemini,
    system_prompt: str,
    seeds: list[str],
    batch_size: int,
    rng: random.Random,
) -> list[str]:
    """Generate one batch of synthetic examples. Returns list of texts (may be shorter than batch_size)."""
    seed_block = _make_seed_block(seeds, NUM_FEW_SHOT_SEEDS, rng)
    prompt = _GENERATION_PROMPT_TEMPLATE.format(
        batch_size=batch_size,
        seeds=seed_block,
    )
    try:
        result = gemini.call_json(
            messages=[
                {"role": "system", "content": system_prompt.format(batch_size=batch_size)},
                {"role": "user", "content": prompt},
            ],
            max_tokens=1024,
            temperature=0.8,  # higher temp = more diversity
        )
        examples = result.get("examples", [])
        if isinstance(examples, list):
            return [str(e).strip() for e in examples if str(e).strip()]
        return []
    except Exception as exc:  # noqa: BLE001
        print(f"  [WARN] Batch generation failed: {exc}")
        return []


# ---------------------------------------------------------------------------
# Main synthesis loop
# ---------------------------------------------------------------------------
def synthesize_class(
    gemini,
    label: str,
    seeds: list[str],
    target: int,
    system_prompt: str,
    rng: random.Random,
    verbose: bool = True,
) -> list[dict]:
    """Generate `target` synthetic rows for a given label."""
    kept: list[str] = []
    attempts = 0
    max_attempts = int(target * 3.5 / BATCH_SIZE) + 20  # generous ceiling

    while len(kept) < target and attempts < max_attempts:
        batch = _generate_batch(gemini, system_prompt, seeds, BATCH_SIZE, rng)
        attempts += 1

        # Basic cleaning
        batch = [normalize_text(b) for b in batch]
        batch = [b for b in batch if passes_length_filter(b)]

        # Exact dedup against kept
        existing_set = {b.lower() for b in kept}
        batch = [b for b in batch if b.lower() not in existing_set]

        # Cosine near-dedup (incremental against kept pool)
        batch = cosine_dedup(batch, kept, threshold=COSINE_DEDUP_THRESHOLD)

        kept.extend(batch[:target - len(kept)])  # don't exceed target

        if verbose and attempts % 10 == 0:
            print(f"  {label}: attempt {attempts}, kept={len(kept)}/{target}")
        time.sleep(0.3)

    if verbose:
        print(f"  {label}: generated {len(kept)} rows in {attempts} API calls")

    return [
        {
            "text": t,
            "label": label,
            "label_id": LABEL2ID[label],
            "source": "synthesized_gemini",
        }
        for t in kept[:target]
    ]


# ---------------------------------------------------------------------------
# QA: 10% sample check
# ---------------------------------------------------------------------------
def write_qa_sample(rows: list[dict], sample_frac: float = 0.10) -> list[dict]:
    """Write a sample of generated rows with metadata for human QA review."""
    rng = random.Random(42)
    sample_size = max(10, int(len(rows) * sample_frac))
    sample = rng.sample(rows, min(sample_size, len(rows)))

    qa_rows = []
    for row in sample:
        qa_rows.append({
            "label": row["label"],
            "text": row["text"],
            "word_count": len(row["text"].split()),
            "source": row["source"],
        })

    with QA_PATH.open("w", encoding="utf-8") as f:
        for row in qa_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"  QA sample written: {len(qa_rows)} rows to {QA_PATH}")
    return qa_rows


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    print("=" * 60)
    print("Stage-2 Task 2: Hebrew hate + violence synthesis")
    print("=" * 60)

    # Check cache
    if OUTPUT_PATH.exists():
        count = sum(1 for _ in OUTPUT_PATH.open("r", encoding="utf-8"))
        print(f"\n[CACHE HIT] {OUTPUT_PATH} exists ({count} rows). Delete to re-run.")
        return

    # Load Gemini
    import sys  # noqa: PLC0415
    sys.path.insert(0, str(REPO_ROOT))
    from training.gemini_utils import GeminiSync  # noqa: PLC0415

    gemini = GeminiSync()
    rng = random.Random(42)

    # Load seeds
    print("\n[1/3] Loading SinaLab few-shot seeds...")
    hate_seeds, violence_seeds = load_sinalab_seeds(verbose=True)

    if not hate_seeds:
        raise RuntimeError("No hate seeds found in SinaLab CSV — cannot synthesize.")
    if not violence_seeds:
        raise RuntimeError("No violence seeds found in SinaLab CSV — cannot synthesize.")

    # Synthesize hate
    print(f"\n[2/3] Synthesizing {TARGET_HATE} hate examples...")
    hate_rows = synthesize_class(
        gemini,
        label="hate",
        seeds=hate_seeds,
        target=TARGET_HATE,
        system_prompt=_HATE_SYSTEM,
        rng=rng,
        verbose=True,
    )

    # Synthesize violence
    print(f"\n[3/3] Synthesizing {TARGET_VIOLENCE} violence examples...")
    violence_rows = synthesize_class(
        gemini,
        label="violence",
        seeds=violence_seeds,
        target=TARGET_VIOLENCE,
        system_prompt=_VIOLENCE_SYSTEM,
        rng=rng,
        verbose=True,
    )

    all_rows = hate_rows + violence_rows
    print(f"\n  Total synthesized: {len(all_rows)} rows")
    dist = Counter(r["label"] for r in all_rows)
    print(f"  Distribution: {dict(dist)}")

    # Write output
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        for row in all_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"\n  Wrote {len(all_rows)} rows to {OUTPUT_PATH}")

    # Write QA sample
    print("\n[QA] Writing 10% sample for human review...")
    write_qa_sample(all_rows, sample_frac=0.10)

    print(f"\nDone. Next: run training/fetch_porn_real_seed.py (Task 3)")


if __name__ == "__main__":
    import sys  # noqa: PLC0415
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    main()
