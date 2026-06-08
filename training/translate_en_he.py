"""translate_en_he.py — EN→HE translation of Jigsaw threat/identity_hate examples.

Stage-2 Task 1: Translate Jigsaw Toxic Comment rows to Hebrew using Gemini
context-preserving translation (meaning + register preserved; slurs kept as slurs).

Sources:
  - tasksource/jigsaw_toxicity  (accessible without Kaggle auth)
    threat==1        -> label: violence  (take all available ~478)
    identity_hate==1 -> label: hate      (cap at 1200)

Outputs:
  - training/data/interim/jigsaw_he.jsonl
    schema: {text, label, label_id, source:"translated_jigsaw"}
  - training/data/interim/qa_translate_sample.jsonl
    back-translation QA on 10% sample (EN->HE->EN cosine similarity)

Behavior: skip-if-exists (idempotent / cache-friendly).
Run in WSL2 training venv from repo root:
    python training/translate_en_he.py
"""
from __future__ import annotations

import json
import os
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
OUTPUT_PATH = INTERIM_DIR / "jigsaw_he.jsonl"
QA_PATH = INTERIM_DIR / "qa_translate_sample.jsonl"

INTERIM_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Label constants (must match prepare_data_dictabert.py)
# ---------------------------------------------------------------------------
LABEL2ID = {
    "non_offensive": 0,
    "abusive": 1,
    "hate": 2,
    "violence": 3,
    "pornographic": 4,
}

# Caps
CAP_VIOLENCE = 500   # all threat==1 rows (dataset has ~478; cap is a safety ceiling)
CAP_HATE = 1200      # cap identity_hate==1 at 1,200

# ---------------------------------------------------------------------------
# Gemini system prompt for translation
# ---------------------------------------------------------------------------
_SYSTEM_PROMPT = (
    "You are a professional translator from English to Hebrew. "
    "Your task is to translate hate speech and threatening text ACCURATELY. "
    "CRITICAL RULES:\n"
    "1. Preserve the meaning, register, and emotional intensity EXACTLY.\n"
    "2. Slurs, insults, dehumanizing language must be translated as slurs/insults. DO NOT sanitize.\n"
    "3. Threats must be translated as threats. DO NOT soften or euphemize.\n"
    "4. Use colloquial Israeli Hebrew (not formal/literary). Social-media register.\n"
    "5. Keep any mentioned group names (Jews, Arabs, Muslims, immigrants) faithfully translated.\n"
    "6. Return ONLY valid JSON with key 'translated_text'. No explanations.\n"
)

_TRANSLATE_PROMPT_TEMPLATE = (
    "Translate the following English text to Hebrew (social-media register, preserve all offensive content):\n\n"
    "Text: {text}\n\n"
    "Return JSON: {{\"translated_text\": \"...\"}}"
)

# Back-translation prompt
_BACK_TRANSLATE_PROMPT_TEMPLATE = (
    "Translate the following Hebrew text to English (accurate, no sanitization):\n\n"
    "Hebrew: {text}\n\n"
    "Return JSON: {{\"translated_text\": \"...\"}}"
)

# ---------------------------------------------------------------------------
# Text normalization (same as prepare_data_dictabert.py)
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
# Load Jigsaw
# ---------------------------------------------------------------------------
def load_jigsaw_rows(verbose: bool = True) -> list[dict]:
    """Load Jigsaw threat + identity_hate rows from HF."""
    from datasets import load_dataset  # noqa: PLC0415

    print("  Loading tasksource/jigsaw_toxicity from HuggingFace...")
    ds = load_dataset("tasksource/jigsaw_toxicity", split="train")
    if verbose:
        print(f"  Total Jigsaw rows: {len(ds)}")

    rng = random.Random(42)

    violence_candidates = []
    hate_candidates = []

    for row in ds:
        text = str(row.get("comment_text", "") or "").strip()
        if not text:
            continue
        if int(row.get("threat", 0)) == 1:
            violence_candidates.append(text)
        if int(row.get("identity_hate", 0)) == 1:
            hate_candidates.append(text)

    if verbose:
        print(f"  Jigsaw violence candidates (threat==1): {len(violence_candidates)}")
        print(f"  Jigsaw hate candidates (identity_hate==1): {len(hate_candidates)}")

    # Deduplicate
    def dedup(lst: list[str]) -> list[str]:
        seen: set[str] = set()
        result = []
        for t in lst:
            k = t.lower()[:200]
            if k not in seen:
                seen.add(k)
                result.append(t)
        return result

    violence_candidates = dedup(violence_candidates)
    hate_candidates = dedup(hate_candidates)

    # Apply caps
    if len(violence_candidates) > CAP_VIOLENCE:
        rng.shuffle(violence_candidates)
        violence_candidates = violence_candidates[:CAP_VIOLENCE]
    if len(hate_candidates) > CAP_HATE:
        rng.shuffle(hate_candidates)
        hate_candidates = hate_candidates[:CAP_HATE]

    # Compose rows
    rows = (
        [{"text": t, "label": "violence", "en_text": t} for t in violence_candidates]
        + [{"text": t, "label": "hate", "en_text": t} for t in hate_candidates]
    )
    if verbose:
        from collections import Counter  # noqa: PLC0415
        dist = Counter(r["label"] for r in rows)
        print(f"  After dedup + cap: {dict(dist)} (total {len(rows)})")

    return rows


# ---------------------------------------------------------------------------
# Translation (single row)
# ---------------------------------------------------------------------------
def _try_repair_json(raw: str) -> dict | None:
    """Try to repair a truncated JSON string from Gemini.

    Gemini sometimes returns {"translated_text": "...truncated (no closing quote/brace).
    We attempt to extract the value by finding the string opening and closing manually.
    """
    import re as _re  # noqa: PLC0415

    # Pattern: {"translated_text": "...value..."}
    m = _re.search(r'"translated_text"\s*:\s*"(.*)', raw, _re.DOTALL)
    if m:
        partial = m.group(1)
        # Remove trailing incomplete escape sequences or braces
        # Find the last complete character (not a trailing backslash or partial escape)
        partial = partial.rstrip()
        if partial.endswith('"') or partial.endswith('"}'):
            # Clean ending
            partial = partial.rstrip('"}').rstrip('"')
        elif partial.endswith('\\'):
            partial = partial[:-1]
        if len(partial) >= 3:
            return {"translated_text": partial}
    return None


def _translate_row(gemini, row: dict) -> dict | None:
    """Translate a single EN row to Hebrew. Returns row with translated text or None on failure."""
    import sys  # noqa: PLC0415

    en_text = row["en_text"]
    # Clip very long inputs to avoid max_tokens overflow
    en_text_clipped = en_text[:1500]
    prompt = _TRANSLATE_PROMPT_TEMPLATE.format(text=en_text_clipped)

    # Use 768 tokens (generous — Hebrew can be longer than English in some encodings)
    # max_retries=1, base_backoff=0.3: fail fast for JSON parse errors (retrying same
    # input won't fix a truncated Hebrew string from Gemini safety refusal)
    for attempt in range(2):  # 2 attempts max total via our outer loop
        try:
            result = gemini.call_json(
                messages=[
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=768,
                temperature=0.2,
                max_retries=1,
                base_backoff=0.3,
            )
            he_text = str(result.get("translated_text", "")).strip()
            if not he_text:
                return None
            return {
                "text": normalize_text(he_text),
                "label": row["label"],
                "label_id": LABEL2ID[row["label"]],
                "source": "translated_jigsaw",
                "en_text": en_text,
            }
        except Exception as exc:  # noqa: BLE001
            exc_str = str(exc)
            if attempt == 0 and "Unterminated string" in exc_str:
                # Gemini truncated mid-JSON — try to extract partial translation from the raw response
                # Re-call without json_object mode to get the raw text
                time.sleep(1.0)
                continue
            if attempt == 1 and "Unterminated string" in exc_str:
                # Try raw text mode as fallback
                try:
                    from openai import OpenAI as _OAI  # noqa: PLC0415
                    import os as _os, dotenv  # noqa: PLC0415
                    dotenv.load_dotenv(
                        Path(__file__).resolve().parent.parent / "server" / ".env",
                        override=False
                    )
                    key = _os.environ.get("GEMINI_API_KEY", "")
                    client = _OAI(api_key=key, base_url="https://generativelanguage.googleapis.com/v1beta/openai/")
                    resp = client.chat.completions.create(
                        model="gemini-2.5-flash",
                        messages=[
                            {"role": "system", "content": _SYSTEM_PROMPT},
                            {"role": "user", "content": prompt + "\nReturn ONLY the JSON, nothing else."},
                        ],
                        max_tokens=768,
                        temperature=0.2,
                        extra_body={"reasoning_effort": "none"},
                    )
                    raw = (resp.choices[0].message.content or "").strip()
                    # Strip markdown fences
                    if raw.startswith("```"):
                        raw = "\n".join(l for l in raw.splitlines() if not l.startswith("```")).strip()
                    # Try standard JSON first
                    try:
                        parsed = json.loads(raw)
                        he_text = str(parsed.get("translated_text", "")).strip()
                        if he_text:
                            return {"text": normalize_text(he_text), "label": row["label"],
                                    "label_id": LABEL2ID[row["label"]], "source": "translated_jigsaw",
                                    "en_text": en_text}
                    except json.JSONDecodeError:
                        pass
                    # Try repair
                    repaired = _try_repair_json(raw)
                    if repaired:
                        he_text = repaired.get("translated_text", "").strip()
                        if he_text:
                            return {"text": normalize_text(he_text), "label": row["label"],
                                    "label_id": LABEL2ID[row["label"]], "source": "translated_jigsaw",
                                    "en_text": en_text}
                except Exception:
                    pass
            # Non-Unterminated error, or final attempt
            if attempt == 1:
                print(f"  [WARN] Translation failed for row: {type(exc).__name__}")
            time.sleep(0.5)

    return None


# ---------------------------------------------------------------------------
# Back-translation QA
# ---------------------------------------------------------------------------
def run_backtranslation_qa(gemini, translated_rows: list[dict], sample_frac: float = 0.10) -> list[dict]:
    """Back-translate a sample from HE→EN, compute cosine similarity with original EN."""
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer  # noqa: PLC0415
        from sklearn.metrics.pairwise import cosine_similarity  # noqa: PLC0415
    except ImportError:
        print("  [WARN] sklearn not available for back-translation QA cosine check; skipping.")
        return []

    rng = random.Random(42)
    sample_size = max(10, int(len(translated_rows) * sample_frac))
    sample = rng.sample(translated_rows, min(sample_size, len(translated_rows)))

    print(f"  Back-translation QA on {len(sample)} rows (HE→EN + cosine)...")

    qa_rows = []
    for i, row in enumerate(sample):
        he_text = row["text"]
        en_orig = row["en_text"]

        prompt = _BACK_TRANSLATE_PROMPT_TEMPLATE.format(text=he_text)
        try:
            result = gemini.call_json(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=512,
                temperature=0.2,
            )
            en_back = str(result.get("translated_text", "")).strip()
        except Exception as exc:  # noqa: BLE001
            print(f"    [WARN] Back-translation failed: {exc}")
            en_back = ""
            continue

        # Cosine similarity (TF-IDF character 3-gram)
        try:
            vec = TfidfVectorizer(analyzer="char", ngram_range=(3, 3))
            tfidf = vec.fit_transform([en_orig, en_back])
            sim = float(cosine_similarity(tfidf[0], tfidf[1])[0, 0])
        except Exception:
            sim = -1.0

        qa_rows.append({
            "label": row["label"],
            "en_original": en_orig,
            "he_translated": he_text,
            "en_back_translated": en_back,
            "cosine_sim": round(sim, 4),
        })

        if (i + 1) % 20 == 0:
            print(f"    QA progress: {i + 1}/{len(sample)}")
        time.sleep(0.3)

    # Summary stats
    if qa_rows:
        sims = [r["cosine_sim"] for r in qa_rows if r["cosine_sim"] >= 0]
        if sims:
            import statistics  # noqa: PLC0415
            mean_sim = statistics.mean(sims)
            low_count = sum(1 for s in sims if s < 0.2)
            print(f"  QA summary: mean cosine={mean_sim:.3f}, low-sim (<0.2): {low_count}/{len(sims)}")

    return qa_rows


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    import sys  # noqa: PLC0415
    print("=" * 60)
    print("Stage-2 Task 1: Jigsaw EN→HE translation")
    print("=" * 60)

    # Check cache
    if OUTPUT_PATH.exists():
        import subprocess  # noqa: PLC0415
        count = sum(1 for _ in OUTPUT_PATH.open("r", encoding="utf-8"))
        print(f"\n[CACHE HIT] {OUTPUT_PATH} exists ({count} rows). Delete to re-run.")
        # Still run QA if QA file is missing
        if QA_PATH.exists():
            print(f"[CACHE HIT] QA file exists: {QA_PATH}")
            print("Nothing to do. Exiting.")
            return
        else:
            print("[INFO] QA file missing; will run back-translation QA on cached translations.")
            translated_rows = []
            with OUTPUT_PATH.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        translated_rows.append(json.loads(line))
            _run_qa_only(translated_rows)
            return

    # Load Gemini
    from training.gemini_utils import GeminiSync  # noqa: PLC0415
    gemini = GeminiSync()

    # Load Jigsaw rows
    print("\n[1/3] Loading Jigsaw from HuggingFace...")
    source_rows = load_jigsaw_rows(verbose=True)

    # Translate
    print(f"\n[2/3] Translating {len(source_rows)} rows EN→HE...")
    translated_rows: list[dict] = []
    failed = 0
    for i, row in enumerate(source_rows):
        result = _translate_row(gemini, row)
        if result is None or not passes_length_filter(result["text"]):
            failed += 1
            continue
        translated_rows.append(result)

        if (i + 1) % 50 == 0:
            print(f"  Progress: {i + 1}/{len(source_rows)}, translated={len(translated_rows)}, failed={failed}")
        time.sleep(0.2)  # polite rate-limiting

    print(f"\n  Translation complete: {len(translated_rows)} rows, failed/filtered={failed}")
    from collections import Counter  # noqa: PLC0415
    dist = Counter(r["label"] for r in translated_rows)
    print(f"  Label distribution: {dict(dist)}")

    # Write output
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        for row in translated_rows:
            # Write without en_text in final output (space)
            out = {k: v for k, v in row.items() if k != "en_text"}
            f.write(json.dumps(out, ensure_ascii=False) + "\n")
    print(f"\n  Wrote {len(translated_rows)} rows to {OUTPUT_PATH}")

    # Back-translation QA
    print("\n[3/3] Back-translation QA (10% sample)...")
    qa_rows = run_backtranslation_qa(gemini, translated_rows, sample_frac=0.10)
    with QA_PATH.open("w", encoding="utf-8") as f:
        for row in qa_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"  Wrote {len(qa_rows)} QA rows to {QA_PATH}")

    print("\nDone. Next: run training/synthesize_hate_violence.py")


def _run_qa_only(translated_rows: list[dict]) -> None:
    """Run QA only (used when OUTPUT_PATH cached but QA_PATH missing)."""
    from training.gemini_utils import GeminiSync  # noqa: PLC0415
    gemini = GeminiSync()
    qa_rows = run_backtranslation_qa(gemini, translated_rows, sample_frac=0.10)
    with QA_PATH.open("w", encoding="utf-8") as f:
        for row in qa_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"  Wrote {len(qa_rows)} QA rows to {QA_PATH}")


if __name__ == "__main__":
    # Allow running as a script from repo root (add repo root to path)
    import sys  # noqa: PLC0415
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    main()
