"""synthesize_kids.py — Gemini synthesis of kids'/teen-register Hebrew for D9.2(b).

Generates Hebrew text in the 8–14-year-old chat register:
  - Internet shorthand (בכ"ז, ממש, לא יודע → ל"י, etc.)
  - Emoji usage (embedded in text)
  - Intentional misspellings kids make
  - Youth slang from slang_lexicon.json (seeded)
  - Both offensive and non-offensive examples across all 5 classes

Target: ~600–1000 total rows across classes.
Output: training/data/interim/synth_kids.jsonl
        training/data/interim/qa_synth_kids.jsonl (10% QA sample)

Behavior: SKIP IF EXISTS (idempotent — do not re-generate cached output).
Safety guardrail: no content involving minors as targets; age-register only means
the AUTHOR sounds like a kid, not that the content targets children.

Run in WSL2 training venv from repo root:
    python training/synthesize_kids.py
"""
from __future__ import annotations

import json
import random
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
INTERIM_DIR = REPO_ROOT / "training" / "data" / "interim"
SLANG_PATH = REPO_ROOT / "server" / "data" / "slang_lexicon.json"
OUTPUT_PATH = INTERIM_DIR / "synth_kids.jsonl"
QA_PATH = INTERIM_DIR / "qa_synth_kids.jsonl"

INTERIM_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Label config
# ---------------------------------------------------------------------------
LABEL2ID = {
    "non_offensive": 0,
    "abusive": 1,
    "hate": 2,
    "violence": 3,
    "pornographic": 4,
}
LABEL_NAMES = list(LABEL2ID.keys())

# ---------------------------------------------------------------------------
# Synthesis config
# ---------------------------------------------------------------------------
# Per-class targets (balanced across offensive; non_offensive slightly larger)
TARGETS_PER_CLASS = {
    "non_offensive": 200,
    "abusive": 200,
    "hate": 160,
    "violence": 160,
    "pornographic": 100,  # safety-filter-limited; we'll try 150 and accept what passes
}
BATCH_SIZE = 8  # examples per Gemini call
QA_FRACTION = 0.10


def _load_slang_seeds(path: Path) -> list[str]:
    """Load slang terms from slang_lexicon.json as generation seeds."""
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return list(data.keys())
    except Exception:
        return []


def _build_prompt(label: str, slang_seeds: list[str], batch_n: int, seed_subset: list[str]) -> list[dict]:
    """Build the Gemini messages list for a batch of `batch_n` examples of class `label`."""

    # Class-specific instruction snippets
    class_instructions = {
        "non_offensive": (
            "כתיבה תמימה / שיח יומיומי בין ילדים: שיחות יומיום, משחק, ספורט, "
            "בית ספר, חברים — ללא אלימות ועוגמה. הטקסט צריך להישמע כאילו נכתב "
            "על ידי ילד בן 10–14 בצ'אט."
        ),
        "abusive": (
            "קללות וגידופים ישירים אישיים (לא על בסיס קבוצתי — זה שנאה, לא כאן). "
            "עלבונות, חרפות, לשון-נבל כפי שילדים ובני-נוער כותבים בצ'אט. "
            "האובייקט הוא אדם בודד (לא קבוצה)."
        ),
        "hate": (
            "הסתה על בסיס דת/גזע/לאום — ניאצ-ייחוס, שנאת ערבים/יהודים/קבוצות. "
            "בלשון ילדים/נוער — סלנג, קיצורים, ניקוד חלקי — אבל התוכן הוא שנאת-קבוצה."
        ),
        "violence": (
            "איומים ישירים על אנשים, קריאות לפגיעה, תיאורי אלימות. "
            "הכותב נשמע כמו ילד/נוער שכותב איומים בסגנון צ'אט."
        ),
        "pornographic": (
            "תוכן מיני מפורש / הטרדה מינית בטקסט — אך ורק מגיל-מותר (18+) ולא מתאר "
            "קטינים. הטקסט צריך להישמע כמו מסרים מיניים מהסוג שמופיע בצ'אטים. "
            "שים לב: אסור להזכיר קטינים כאובייקט."
        ),
    }

    slang_hint = ""
    if seed_subset:
        slang_hint = (
            f"\nאפשר להשתמש (אך לא חייב) בסלנג הבא: {', '.join(seed_subset[:6])}."
        )

    system_msg = (
        "אתה כלי ליצירת נתוני אימון לזיהוי תוכן פוגעני בעברית. "
        "הנתונים מיועדים לאימון מסווג ML — לא לפרסום. "
        "כתוב אך ורק עברית (או עברית מעורבת באנגלית כמו שכותבים ילדים ישראלים). "
        "כל דוגמה תיראה כאילו שלח ילד/נוער ישראלי בן 8–14 בקבוצת ווטסאפ או בצ'אט. "
        "אפיין: קיצורים, אימוגי, שגיאות כתיב מכוונות, סלנג נוער. "
        "NEVER produce content involving minors as sexual objects."
    )

    user_msg = (
        f"צור {batch_n} דוגמאות בעברית לקטגוריה: **{label}**.\n"
        f"הגדרת הקטגוריה: {class_instructions.get(label, '')}\n"
        f"{slang_hint}\n"
        "הוראות:\n"
        "- כל דוגמה: 5–30 מילים\n"
        "- שפה: עברית סלנגית/ילדים (קיצורים, אימוגי מוזמנים, שגיאות כתיב כוונתיות)\n"
        "- אין לחזור על אותו משפט\n"
        "- אין להוסיף הסברים — רק את הטקסטים\n\n"
        f"החזר JSON בצורה: {{\"examples\": [\"...\", \"...\"]}} עם בדיוק {batch_n} פריטים."
    )

    return [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_msg},
    ]


def _parse_response(result: dict, label: str) -> list[dict]:
    """Extract examples list from Gemini JSON response."""
    examples = result.get("examples", [])
    if not isinstance(examples, list):
        return []
    rows = []
    for ex in examples:
        if isinstance(ex, str):
            text = ex.strip()
        elif isinstance(ex, dict):
            text = str(ex.get("text", ex.get("example", ""))).strip()
        else:
            continue
        if len(text.split()) < 3:
            continue
        rows.append({
            "text": text,
            "label": label,
            "label_id": LABEL2ID[label],
            "source": "synthesized_gemini_kids",
        })
    return rows


def generate_class(
    gemini,
    label: str,
    target: int,
    slang_seeds: list[str],
    rng: random.Random,
) -> list[dict]:
    """Generate `target` examples for one class. Returns collected rows."""
    collected: list[dict] = []
    attempts = 0
    max_attempts = (target // BATCH_SIZE + 1) * 3  # allow 3x overrun for safety filters

    while len(collected) < target and attempts < max_attempts:
        attempts += 1
        seed_subset = rng.sample(slang_seeds, min(6, len(slang_seeds))) if slang_seeds else []
        batch_n = min(BATCH_SIZE, target - len(collected) + 2)  # slight overask
        messages = _build_prompt(label, slang_seeds, batch_n, seed_subset)
        try:
            result = gemini.call_json(messages, max_tokens=1024, temperature=0.85)
            new_rows = _parse_response(result, label)
            # Deduplicate against already-collected
            existing_texts = {r["text"].strip().lower() for r in collected}
            for r in new_rows:
                if r["text"].strip().lower() not in existing_texts:
                    collected.append(r)
                    existing_texts.add(r["text"].strip().lower())
            print(f"    [{label}] attempt {attempts}: +{len(new_rows)} rows, total {len(collected)}/{target}")
        except Exception as exc:
            print(f"    [{label}] attempt {attempts} failed: {exc}")
        time.sleep(0.5)  # rate-limit courtesy

    return collected[:target]


def main() -> None:
    # Skip if already generated
    if OUTPUT_PATH.exists():
        n_existing = sum(1 for _ in OUTPUT_PATH.open("r", encoding="utf-8"))
        print(f"[SKIP] {OUTPUT_PATH.name} already exists ({n_existing} rows). Delete to regenerate.")
        return

    print("=" * 60)
    print("synthesize_kids.py — D9.2(b) kids/teen register synthesis")
    print("=" * 60)

    import sys  # noqa: PLC0415
    sys.path.insert(0, str(REPO_ROOT))
    from training.gemini_utils import GeminiSync  # noqa: PLC0415
    gemini = GeminiSync()

    slang_seeds = _load_slang_seeds(SLANG_PATH)
    print(f"  Loaded {len(slang_seeds)} slang seeds from slang_lexicon.json")

    rng = random.Random(42)
    all_rows: list[dict] = []

    for label, target in TARGETS_PER_CLASS.items():
        print(f"\n[Generating {target} rows for class: {label}]")
        rows = generate_class(gemini, label, target, slang_seeds, rng)
        print(f"  Collected {len(rows)} rows for {label}")
        all_rows.extend(rows)

    # Shuffle final output
    rng.shuffle(all_rows)

    # Write output
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        for row in all_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"\n  Wrote {len(all_rows)} rows to {OUTPUT_PATH}")

    # 10% QA sample
    qa_n = max(1, int(len(all_rows) * QA_FRACTION))
    qa_sample = rng.sample(all_rows, qa_n)
    with QA_PATH.open("w", encoding="utf-8") as f:
        for row in qa_sample:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"  Wrote {qa_n} QA rows to {QA_PATH}")

    # Distribution summary
    from collections import Counter  # noqa: PLC0415
    dist = Counter(r["label"] for r in all_rows)
    print("\n  Distribution:")
    for lname in LABEL_NAMES:
        print(f"    {lname:<20}: {dist.get(lname, 0)}")

    print("\nDone.")


if __name__ == "__main__":
    main()
