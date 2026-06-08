"""expand_slang_lexicon.py — Expand server/data/slang_lexicon.json to ~60-80 entries.

Decision D9.2(d): expand the slang lexicon from 10 → ~60–80 youth/internet Hebrew
slang terms using Gemini. The expanded lexicon seeds synthesize_kids.py and
synthesize_codeswitch.py AND serves the Context Agent RAG.

Same schema as existing entries:
  {
    "term": {
      "meaning": str,
      "common_use": str,
      "valence": str,         # "positive"|"neutral"|"negative"|"highly_negative"
      "age_group": str        # e.g. "10-18", "13-18", "all"
    }
  }

Behavior:
  1. Backs up the original file to slang_lexicon.json.bak BEFORE modifying.
  2. SKIP IF BACKUP EXISTS and new count >= 60 (idempotent).
  3. Generates new terms in batches, deduplicates against existing.
  4. Merges and writes back valid JSON.

Run in WSL2 training venv from repo root:
    python training/expand_slang_lexicon.py
"""
from __future__ import annotations

import json
import random
import shutil
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
SLANG_PATH = REPO_ROOT / "server" / "data" / "slang_lexicon.json"
SLANG_BAK_PATH = SLANG_PATH.with_suffix(".json.bak")

# ---------------------------------------------------------------------------
# Targets
# ---------------------------------------------------------------------------
TARGET_TOTAL = 70  # aim for 70; accept 60–80
BATCH_SIZE = 15   # terms per Gemini call


def _load_existing() -> dict:
    if SLANG_PATH.exists():
        return json.loads(SLANG_PATH.read_text(encoding="utf-8"))
    return {}


def _build_prompt(existing_terms: list[str], batch_n: int) -> list[dict]:
    existing_str = ", ".join(existing_terms[:30]) if existing_terms else "none"

    system_msg = (
        "אתה מומחה לסלנג ישראלי, שפת נוער ואינטרנט עברית. "
        "עבודתך: לספק נתונים מדויקים על סלנג עברי לצורך אימון מסווג ML לזיהוי תוכן פוגעני. "
        "התמקד בסלנג שנוער (10–18) משתמש בו בווטסאפ, אינסטגרם, טיקטוק — "
        "כולל ביטויים שיכולים לשמש להטרדה, בריונות, קיצורים, ביטויים חיוביים ושליליים."
    )

    user_msg = (
        f"צור {batch_n} ערכי סלנג עברי חדשים (שלא נמצאים כבר ברשימה: {existing_str}).\n\n"
        "כלול:\n"
        "- ביטויי אינטרנט / מים (memes)\n"
        "- ביטויי בריונות / הטרדה (שהמסווג צריך לזהות)\n"
        "- קיצורים נפוצים בצ'אט\n"
        "- מחמאות ושלילות רגילות\n"
        "- סלנג גיימינג\n"
        "- ביטויים שמערבים אנגלית ועברית\n\n"
        "לכל ביטוי ספק:\n"
        "  meaning: משמעות בעברית / אנגלית קצרה\n"
        "  common_use: הקשר השימוש הנפוץ\n"
        f"  valence: אחד מ: positive / neutral / negative / highly_negative\n"
        "  age_group: טווח גיל (כגון '13-18', '10-18', 'all')\n\n"
        "החזר JSON:\n"
        "{\n"
        "  \"terms\": {\n"
        "    \"מילה\": {\"meaning\": \"...\", \"common_use\": \"...\", \"valence\": \"...\", \"age_group\": \"...\"},\n"
        "    ...\n"
        "  }\n"
        "}"
    )

    return [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_msg},
    ]


def _parse_response(result: dict) -> dict:
    """Extract terms dict from Gemini response."""
    terms = result.get("terms", {})
    if not isinstance(terms, dict):
        return {}
    valid = {}
    required_fields = {"meaning", "common_use", "valence", "age_group"}
    for term, entry in terms.items():
        if not isinstance(entry, dict):
            continue
        if not required_fields.issubset(entry.keys()):
            # Tolerate partial entries — fill missing fields with defaults
            for field in required_fields:
                if field not in entry:
                    entry[field] = "unknown"
        term_str = str(term).strip()
        if term_str:
            valid[term_str] = {k: str(v) for k, v in entry.items() if k in required_fields}
    return valid


def main() -> None:
    existing = _load_existing()

    # Idempotency check
    if SLANG_BAK_PATH.exists() and len(existing) >= 60:
        print(
            f"[SKIP] slang_lexicon.json already has {len(existing)} entries "
            f"(>= 60) and backup exists. Delete .bak to re-expand."
        )
        return

    print("=" * 60)
    print("expand_slang_lexicon.py — D9.2(d) slang lexicon expansion")
    print("=" * 60)
    print(f"  Current entries: {len(existing)}")
    print(f"  Target: {TARGET_TOTAL}")

    # Backup original
    if not SLANG_BAK_PATH.exists():
        shutil.copy2(SLANG_PATH, SLANG_BAK_PATH)
        print(f"  Backed up to {SLANG_BAK_PATH.name}")

    import sys  # noqa: PLC0415
    sys.path.insert(0, str(REPO_ROOT))
    from training.gemini_utils import GeminiSync  # noqa: PLC0415
    gemini = GeminiSync()

    merged = dict(existing)  # start with what we have
    rng = random.Random(42)
    attempts = 0
    max_attempts = ((TARGET_TOTAL - len(existing)) // BATCH_SIZE + 1) * 4

    while len(merged) < TARGET_TOTAL and attempts < max_attempts:
        attempts += 1
        existing_terms = list(merged.keys())
        # Shuffle so the model doesn't always see the same terms as context
        rng.shuffle(existing_terms)

        messages = _build_prompt(existing_terms, BATCH_SIZE)
        try:
            result = gemini.call_json(messages, max_tokens=2048, temperature=0.7)
            new_terms = _parse_response(result)
            added = 0
            for term, entry in new_terms.items():
                if term not in merged:
                    merged[term] = entry
                    added += 1
            print(f"  attempt {attempts}: +{added} new terms, total {len(merged)}/{TARGET_TOTAL}")
        except Exception as exc:
            print(f"  attempt {attempts} failed: {exc}")
        time.sleep(0.8)

    print(f"\n  Final lexicon size: {len(merged)} terms")

    # Validate: all entries have required schema
    required_fields = {"meaning", "common_use", "valence", "age_group"}
    valid_merged = {}
    for term, entry in merged.items():
        if isinstance(entry, dict) and required_fields.issubset(entry.keys()):
            valid_merged[term] = entry
        else:
            print(f"  [WARN] Skipping malformed entry: {term!r}")

    print(f"  Valid entries: {len(valid_merged)}")

    # Write back
    SLANG_PATH.write_text(
        json.dumps(valid_merged, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"  Wrote updated lexicon to {SLANG_PATH}")

    # Show valence distribution
    from collections import Counter  # noqa: PLC0415
    valences = Counter(v.get("valence", "unknown") for v in valid_merged.values())
    print(f"\n  Valence distribution: {dict(valences)}")

    # QA: print 5 sample new terms
    new_terms_sample = [
        (t, e) for t, e in valid_merged.items()
        if t not in existing
    ]
    rng.shuffle(new_terms_sample)
    print(f"\n  Sample of {min(5, len(new_terms_sample))} new terms:")
    for term, entry in new_terms_sample[:5]:
        print(f"    {term!r}: {entry}")

    print("\nDone.")


if __name__ == "__main__":
    main()
