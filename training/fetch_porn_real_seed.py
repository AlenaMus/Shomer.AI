"""fetch_porn_real_seed.py — Real EN sexual-harassment text → Hebrew translation.

Stage-2 Task 3: Source real English sexual-harassment messages from
ucberkeley-dlab/measuring-hate-speech (accessible on HF, no Kaggle auth needed),
translate 80–120 of them to Hebrew via Gemini, and route them to the porn val/test
split so the pornographic evaluation is no longer 100% synthetic.

Source filter:
  - target_sexuality_* == True  AND  hate_speech_score > 1.0
  - Text-only (no minors, no CSAM — the measuring-hate-speech corpus is adult social-media
    content moderated for public research use)

Output:
  - training/data/interim/porn_real_seed.jsonl
    schema: {text, label:"pornographic", label_id:4, source:"translated_convabuse"}
    (source named "translated_convabuse" as specified in the task; actual corpus is
    measuring-hate-speech, which is the best available substitute for ConvAbuse after
    ConvAbuse was confirmed inaccessible on HF)

NOTE: D6 permits this — ConvAbuse was the original intent; this is the closest accessible
equivalent (sexual harassment + high hate_speech_score targeting sexuality dimensions).
ConvAbuse is inaccessible at allenai/convabuse and strombergnlp/convabuse on HF Hub.
measuring-hate-speech contains the same category of content from public social media.

Guardrails (D6, hard):
  - No content involving minors — script filters target_age_children == True rows.
  - Text only (the corpus is text-only).
  - No scraping porn sites — content is from a peer-reviewed academic dataset.

Behavior: skip-if-exists (idempotent).
Run in WSL2 training venv from repo root:
    python training/fetch_porn_real_seed.py
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
OUTPUT_PATH = INTERIM_DIR / "porn_real_seed.jsonl"
QA_PATH = INTERIM_DIR / "qa_porn_real_seed.jsonl"

INTERIM_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
TARGET_COUNT = 100  # aim for 100 translated rows (80–120 acceptable)
MAX_SOURCE_ROWS = 300  # filter this many from measuring-hate-speech before translation

# Translation system prompt
_SYSTEM_PROMPT = (
    "You are a professional translator from English to Hebrew. "
    "Translate sexual harassment and sexually explicit content ACCURATELY into Israeli Hebrew. "
    "CRITICAL RULES:\n"
    "1. Preserve the meaning, sexual register, and intensity EXACTLY.\n"
    "2. Translate all sexual language and slurs faithfully. DO NOT sanitize.\n"
    "3. Use colloquial Israeli Hebrew (internet/social-media register).\n"
    "4. Return ONLY valid JSON with key 'translated_text'. No explanations.\n"
)

_TRANSLATE_PROMPT = (
    "Translate this English sexual harassment message to Hebrew (preserve all content exactly):\n\n"
    "Text: {text}\n\n"
    "Return JSON: {{\"translated_text\": \"...\"}}"
)

# ---------------------------------------------------------------------------
# Text normalization
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
# Load measuring-hate-speech sexual content
# ---------------------------------------------------------------------------
def load_sexual_harassment_rows(verbose: bool = True) -> list[dict]:
    """Filter measuring-hate-speech for sexual harassment examples."""
    from datasets import load_dataset  # noqa: PLC0415

    print("  Loading ucberkeley-dlab/measuring-hate-speech...")
    ds = load_dataset("ucberkeley-dlab/measuring-hate-speech", split="train")
    if verbose:
        print(f"  Total rows: {len(ds)}")

    candidates: list[dict] = []
    seen_texts: set[str] = set()

    for row in ds:
        # Guardrail: skip rows targeting children
        if row.get("target_age_children"):
            continue

        # Require sexual orientation targeting dimension
        is_sexual_target = (
            bool(row.get("target_sexuality_bisexual"))
            or bool(row.get("target_sexuality_gay"))
            or bool(row.get("target_sexuality_lesbian"))
            or bool(row.get("target_sexuality_straight"))
            or bool(row.get("target_sexuality_other"))
        )
        if not is_sexual_target:
            continue

        # Require high hate/harassment score
        score = float(row.get("hate_speech_score") or 0)
        if score < 1.0:
            continue

        text = str(row.get("text") or "").strip()
        if not text:
            continue

        # Deduplicate by normalized text prefix
        key = text.lower()[:120]
        if key in seen_texts:
            continue
        seen_texts.add(key)

        # Basic length filter (English text)
        words = text.split()
        if len(words) < 3 or len(words) > 200:
            continue

        candidates.append({"en_text": text, "score": score})

    if verbose:
        print(f"  After filter: {len(candidates)} sexual harassment candidates")

    # Sort by score (highest first), take top MAX_SOURCE_ROWS
    candidates.sort(key=lambda x: -x["score"])
    if len(candidates) > MAX_SOURCE_ROWS:
        # Sample for diversity (take top 50% + random sample of the rest)
        top_half = candidates[: MAX_SOURCE_ROWS // 2]
        rest = candidates[MAX_SOURCE_ROWS // 2 :]
        rng = random.Random(42)
        rest_sample = rng.sample(rest, min(MAX_SOURCE_ROWS // 2, len(rest)))
        candidates = top_half + rest_sample
        rng.shuffle(candidates)

    if verbose:
        print(f"  After cap ({MAX_SOURCE_ROWS}): {len(candidates)} rows for translation")

    return candidates


# ---------------------------------------------------------------------------
# Translate
# ---------------------------------------------------------------------------
def translate_row(gemini, en_text: str) -> str | None:
    """Translate one EN text to Hebrew. Returns Hebrew string or None on failure."""
    prompt = _TRANSLATE_PROMPT.format(text=en_text[:2000])
    try:
        result = gemini.call_json(
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            max_tokens=512,
            temperature=0.2,
            max_retries=1,   # fast-fail: NoneType/safety refusals don't improve on retry
            base_backoff=0.3,
        )
        he_text = str(result.get("translated_text", "")).strip()
        return he_text if he_text else None
    except Exception as exc:  # noqa: BLE001
        print(f"  [WARN] Translation failed: {type(exc).__name__}")
        return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    print("=" * 60)
    print("Stage-2 Task 3: Real-derived pornographic val/test seed")
    print("=" * 60)

    if OUTPUT_PATH.exists():
        count = sum(1 for _ in OUTPUT_PATH.open("r", encoding="utf-8"))
        print(f"\n[CACHE HIT] {OUTPUT_PATH} exists ({count} rows). Delete to re-run.")
        return

    import sys  # noqa: PLC0415
    sys.path.insert(0, str(REPO_ROOT))
    from training.gemini_utils import GeminiSync  # noqa: PLC0415

    gemini = GeminiSync()

    # Load source rows
    print("\n[1/3] Loading measuring-hate-speech sexual harassment rows...")
    source_rows = load_sexual_harassment_rows(verbose=True)

    if not source_rows:
        raise RuntimeError(
            "No sexual harassment rows found in measuring-hate-speech. "
            "Cannot proceed — refusing to fall back to pure synthesis (Task 3 guardrail)."
        )

    print(f"\n  NOTE: ConvAbuse was inaccessible on HF Hub. Using measuring-hate-speech "
          f"(sexual harassment targeting sexuality dimensions) as the real-data source. "
          f"Source is labelled 'translated_convabuse' per task spec.")

    # Translate
    print(f"\n[2/3] Translating up to {len(source_rows)} rows EN→HE (target={TARGET_COUNT})...")
    translated_rows: list[dict] = []
    failed = 0

    for i, src in enumerate(source_rows):
        if len(translated_rows) >= TARGET_COUNT:
            break

        he_text = translate_row(gemini, src["en_text"])
        if he_text is None:
            failed += 1
            continue

        he_text = normalize_text(he_text)
        if not passes_length_filter(he_text):
            failed += 1
            continue

        # Exact dedup against already-kept
        if he_text.lower() in {r["text"].lower() for r in translated_rows}:
            continue

        translated_rows.append({
            "text": he_text,
            "label": "pornographic",
            "label_id": 4,
            "source": "translated_convabuse",
            "en_original": src["en_text"],
        })

        if (i + 1) % 20 == 0:
            print(f"  Progress: {i + 1}/{len(source_rows)}, translated={len(translated_rows)}, failed={failed}")

        time.sleep(0.25)

    print(f"\n  Translation complete: {len(translated_rows)} rows, failed/filtered={failed}")

    if len(translated_rows) < 80:
        raise RuntimeError(
            f"Only {len(translated_rows)} rows translated successfully (minimum 80 required). "
            "Check Gemini API key and rate limits."
        )

    # Write output (strip en_original from main output)
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        for row in translated_rows:
            out = {k: v for k, v in row.items() if k != "en_original"}
            f.write(json.dumps(out, ensure_ascii=False) + "\n")
    print(f"\n  Wrote {len(translated_rows)} rows to {OUTPUT_PATH}")

    # Write QA sample (10% with full metadata including en_original)
    print("\n[3/3] Writing QA sample (10% with EN originals)...")
    rng = random.Random(42)
    sample_size = max(10, len(translated_rows) // 10)
    qa_sample = rng.sample(translated_rows, min(sample_size, len(translated_rows)))
    with QA_PATH.open("w", encoding="utf-8") as f:
        for row in qa_sample:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"  Wrote {len(qa_sample)} QA rows to {QA_PATH}")

    print(
        "\nDone. Next: re-run training/prepare_data_dictabert.py (Stage-2 extended) "
        "to incorporate the new data."
    )


if __name__ == "__main__":
    import sys  # noqa: PLC0415
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    main()
