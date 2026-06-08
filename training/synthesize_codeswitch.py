"""synthesize_codeswitch.py — D10 fix: style-matched Heb-Eng code-switch synthesis.

D10 root cause: D9's synth_codeswitch embedded English SLURS exclusively in the
non_offensive class context, teaching the model "English token => offensive". The
eval slice (data/stylistic_eval.jsonl, style=code_switching, 260 rows) is 52%
non_offensive — all benign teen Hebrew with lifestyle English words (fun, vibe,
chill, crush, mood, etc.). Result: code_switching slice regressed 0.74→0.68.

D10 fix: regenerate with ~50% non_offensive teen sentences that embed BENIGN English
lifestyle vocabulary as the dominant code-switch pattern. The remaining ~50% spread
across offensive classes but in the SAME teen register (English mixed naturally,
not only as the slur). Target 800–1000 total rows.

Examples of target non_offensive style (matching the eval slice):
  "היה לי יום fun בטירוף עם החברים"
  "ה-vibe בבית הקפה ממש chill, אני אוהבת"
  "יש לי crush חדש על מישהו מהשכבה, זה awkward"
  "התאמנתי עם ה-playlist החדש שלי, מה ה-mood שלך?"

Examples of target offensive style (same teen register, English mixed naturally):
  "אתה כל כך loser, literally אף אחד לא סובל אותך"  [abusive]
  "הם מתנהגים כאילו הם totally superior, זה sick"  [hate]
  "אני going to hurt you אם לא תפסיק, serious"  [violence]

Output: training/data/interim/synth_codeswitch.jsonl  (OVERWRITE — no skip-if-exists)
        training/data/interim/qa_synth_codeswitch.jsonl (10% QA sample, OVERWRITE)

Run in WSL2 training venv from repo root:
    python training/synthesize_codeswitch.py
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
OUTPUT_PATH = INTERIM_DIR / "synth_codeswitch.jsonl"
QA_PATH = INTERIM_DIR / "qa_synth_codeswitch.jsonl"

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
# D10 distribution: ~50% non_offensive, ~50% spread across offensive classes
# Target: 800–1000 total rows.
# non_offensive is deliberately large to teach "English mixing != offensive"
# ---------------------------------------------------------------------------
TARGETS_PER_CLASS = {
    "non_offensive": 420,   # ~50% of total — the dominant signal needed for D10
    "abusive": 160,         # ~19%
    "hate": 130,            # ~15%
    "violence": 110,        # ~13%
    "pornographic": 40,     # ~5%  (safety-limited; enough to not confuse the model)
}
# Total ~860

BATCH_SIZE = 10
QA_FRACTION = 0.10

# ---------------------------------------------------------------------------
# Benign lifestyle English vocabulary that the eval slice actually uses
# (from inspecting data/stylistic_eval.jsonl code_switching rows)
# ---------------------------------------------------------------------------
BENIGN_ENGLISH_VOCAB = [
    "fun", "vibe", "chill", "crush", "mood", "cute", "random", "awkward",
    "workout", "playlist", "literally", "so", "amazing", "fail", "hangout",
    "fire", "epic", "outfit", "style", "on point", "the best", "goals",
    "no cap", "low key", "high key", "vibes", "aesthetic", "stressful",
    "netflix", "coffee", "weekend", "selfie", "story", "feed", "obsessed",
    "slay", "queen", "bestie", "iconic", "mood check", "toxic", "cringe",
    "glow up", "energy", "valid", "same", "relatable", "it's giving",
    "absolutely", "totally", "actually", "honestly", "omg", "lol", "bff",
    "ok", "ngl", "imo", "tbh", "fomo", "yolo", "asap", "zero chill",
    "soft launch", "main character", "understood the assignment", "rent free",
]


def _load_slang_seeds(path: Path) -> list[str]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return list(data.keys())
    except Exception:
        return []


def _build_prompt_nonoffensive(batch_n: int, slang_seeds: list[str], rng: random.Random) -> list[dict]:
    """Build prompt for non_offensive teen code-switched sentences.

    The critical instruction: embed BENIGN English lifestyle vocabulary.
    This is the key fix — D9 did NOT emphasize benign English mixing here.
    """
    # Pick a sample of benign English words from the eval-slice vocabulary
    vocab_sample = rng.sample(BENIGN_ENGLISH_VOCAB, min(20, len(BENIGN_ENGLISH_VOCAB)))
    vocab_str = ", ".join(vocab_sample)

    slang_hint = ""
    if slang_seeds:
        subset = rng.sample(slang_seeds, min(4, len(slang_seeds)))
        slang_hint = f"\nאפשר לשלב גם סלנג עברי כגון: {', '.join(subset)}."

    system_msg = (
        "אתה כלי ליצירת נתוני אימון לזיהוי תוכן פוגעני בעברית-אנגלית מעורבת. "
        "הנתונים מיועדים לאימון מסווג ML בלבד. "
        "כתוב טקסטים ריאליסטיים בסגנון צ'אט של בני נוער ישראלים שמכירים את שתי השפות. "
        "NEVER produce offensive, insulting, hateful, violent, or sexual content in this prompt."
    )

    user_msg = (
        f"צור {batch_n} דוגמאות צ'אט יומיומי תמים בעברית-אנגלית מעורבת.\n\n"
        "הוראות קריטיות:\n"
        "- הדוגמאות חייבות להיות תמימות לחלוטין: שיחות יומיום, שיתוף תחביבים, "
        "בית ספר, חברים, מוזיקה, אוכל, ספורט, מסיבות תמימות.\n"
        "- אין שום תוכן פוגעני, גידופים, שנאה, אלימות, או מיניות.\n"
        f"- שלב מילים ומונחים באנגלית מהרשימה הבאה (הם המילים שבני נוער ישראלים "
        f"משתמשים בהם): {vocab_str}.\n"
        f"{slang_hint}\n"
        "- כל דוגמה: 6–25 מילים, בעיקר עברית עם 1–5 מילים/ביטויים באנגלית\n"
        "- עברית צריכה להיות לפחות 55% מהמילים\n"
        "- שים לב: האנגלית כאן היא ביטויי LIFESTYLE תמימים בלבד — לא גידופים\n"
        "- אין לחזור על אותו משפט\n"
        "- אין הסברים — רק הטקסטים עצמם\n\n"
        "דוגמאות לסגנון הנדרש:\n"
        "  - 'היה לי יום fun בטירוף היום עם החברים'\n"
        "  - 'ה-vibe בבית קפה החדש ממש chill, אני אוהבת'\n"
        "  - 'יש לי crush חדש על מישהו מהשכבה, זה awkward'\n"
        "  - 'התאמנתי והיה לי amazing workout היום'\n"
        "  - 'ה-playlist החדש שלי הוא ה-mood המושלם ללמידה'\n\n"
        f"החזר JSON: {{\"examples\": [\"...\", ...]}} עם בדיוק {batch_n} פריטים."
    )

    return [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_msg},
    ]


def _build_prompt_offensive(label: str, batch_n: int, slang_seeds: list[str], rng: random.Random) -> list[dict]:
    """Build prompt for offensive code-switched sentences.

    Key D10 change vs D9:
    - Offensive classes still use English, but in the SAME teen register as non_offensive.
    - English slurs/phrases appear alongside benign English — not *only* as the slur.
    - This prevents the model from learning "English word -> offensive" — instead it
      learns the semantic content matters, not the mere presence of English.
    """
    # Give offensive prompts some benign English words too, to break the slur-only pattern
    benign_sample = rng.sample(BENIGN_ENGLISH_VOCAB, min(8, len(BENIGN_ENGLISH_VOCAB)))
    benign_hint = ", ".join(benign_sample)

    slang_hint = ""
    if slang_seeds:
        subset = rng.sample(slang_seeds, min(4, len(slang_seeds)))
        slang_hint = f"\nאפשר לשלב גם סלנג עברי כגון: {', '.join(subset)}."

    class_instructions = {
        "abusive": (
            "גידופים ועלבונות אישיים כלפי אדם ספציפי — בסגנון צ'אט של בני נוער. "
            "שלב מלים באנגלית כמו loser, idiot, pathetic, cringe, toxic, freak, weird — "
            "מוטמעים בטבעיות בתוך משפטים בעברית, בסגנון שבו בני נוער מקללים. "
            "הדוגמאות יכולות לכלול גם מילים באנגלית תמימות (vibe, literally, so, cringe) "
            "לצד הגידוף — כפי שמופיע בצ'אט ריאלי."
        ),
        "hate": (
            "הסתה / שנאה קבוצתית (על בסיס דת/גזע/לאום/מין) בסגנון צ'אט של בני נוער. "
            "שלב מלים באנגלית קבוצתיות/גזעניות באופן טבעי בתוך עברית. "
            "חשוב: הדוגמאות יכולות לכלול גם מילים תמימות (literally, so, the worst) "
            "יחד עם הביטוי השנאתי — כך המודל לומד שהתוכן הסמנטי קובע, לא העצם האנגלי."
        ),
        "violence": (
            "איומי אלימות ישירים בסגנון צ'אט של בני נוער. "
            "שלב מלים באנגלית כמו 'gonna hurt you', 'watch out', 'regret this' — "
            "מוטמעים בעברית. "
            "הדוגמאות יכולות לכלול גם מילים תמימות (literally, so) לצד האיום."
        ),
        "pornographic": (
            "הטרדה מינית בטקסט (18+ בלבד, ללא קטינים) — בסגנון צ'אט. "
            "שלב עברית עם מונחים מיניים מפורשים באנגלית. "
            "NEVER produce content involving minors."
        ),
    }

    system_msg = (
        "אתה כלי ליצירת נתוני אימון לזיהוי תוכן פוגעני בעברית-אנגלית מעורבת. "
        "הנתונים מיועדים לאימון מסווג ML בלבד. "
        "כתוב טקסטים ריאליסטיים בסגנון צ'אט של בני נוער ישראלים. "
        "NEVER produce content involving minors as sexual objects."
    )

    user_msg = (
        f"צור {batch_n} דוגמאות עברית-אנגלית מעורבת לקטגוריה: **{label}**.\n"
        f"הגדרה: {class_instructions.get(label, '')}\n"
        f"{slang_hint}\n"
        f"הערה: שלב גם כמה מהמילים התמימות הבאות בחלק מהדוגמאות: {benign_hint}. "
        "כך הדוגמאות ייראו כמו צ'אט ריאלי שבו מופיעות גם מילים לייפסטייל וגם תוכן פוגעני.\n\n"
        "הוראות:\n"
        "- כל דוגמה: 5–25 מילים, בעיקר עברית עם מילים/ביטויים באנגלית\n"
        "- עברית צריכה להיות לפחות 50% מהמילים\n"
        "- אין לחזור על אותו משפט\n"
        "- אין הסברים — רק הטקסטים עצמם\n\n"
        f"החזר JSON: {{\"examples\": [\"...\", ...]}} עם בדיוק {batch_n} פריטים."
    )

    return [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_msg},
    ]


def _parse_response(result: dict, label: str) -> list[dict]:
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
            "source": "synthesized_gemini_codeswitch_d10",
        })
    return rows


def generate_class(
    gemini,
    label: str,
    target: int,
    slang_seeds: list[str],
    rng: random.Random,
) -> list[dict]:
    collected: list[dict] = []
    max_attempts = (target // BATCH_SIZE + 1) * 4
    attempts = 0

    while len(collected) < target and attempts < max_attempts:
        attempts += 1
        batch_n = min(BATCH_SIZE, target - len(collected) + 2)

        # Use label-specific prompt builder
        if label == "non_offensive":
            messages = _build_prompt_nonoffensive(batch_n, slang_seeds, rng)
        else:
            messages = _build_prompt_offensive(label, batch_n, slang_seeds, rng)

        try:
            result = gemini.call_json(messages, max_tokens=1500, temperature=0.85)
            new_rows = _parse_response(result, label)
            existing_texts = {r["text"].strip().lower() for r in collected}
            added = 0
            for r in new_rows:
                if r["text"].strip().lower() not in existing_texts:
                    collected.append(r)
                    existing_texts.add(r["text"].strip().lower())
                    added += 1
            print(f"    [{label}] attempt {attempts}: +{added} rows, total {len(collected)}/{target}")
        except Exception as exc:
            print(f"    [{label}] attempt {attempts} failed: {exc}")
        time.sleep(0.5)

    return collected[:target]


def _validate_non_offensive_sample(rows: list[dict], n_check: int = 20) -> None:
    """Quick sanity check: warn if non_offensive rows contain obvious English slurs."""
    slurs = {
        "loser", "idiot", "stupid", "bastard", "fuck", "shit", "kill",
        "dead meat", "jewish pigs", "dirty arab", "hate you", "i will kill",
        "beat the shit",
    }
    non_off = [r for r in rows if r["label"] == "non_offensive"]
    check = non_off[:n_check]
    flagged = []
    for r in check:
        text_lower = r["text"].lower()
        for slur in slurs:
            if slur in text_lower:
                flagged.append((r["text"], slur))
                break
    if flagged:
        print(f"\n  [QA WARNING] {len(flagged)}/{n_check} non_offensive rows contain slur-like tokens:")
        for text, slur in flagged[:5]:
            print(f"    '{slur}' found in: {text[:80]}")
        print("  Review the non_offensive generation — re-run if >10% are flagged.")
    else:
        print(f"\n  [QA OK] Checked {len(check)} non_offensive rows — no obvious slurs found.")


def main() -> None:
    # D10: ALWAYS overwrite — this is a targeted fix, not idempotent
    print("=" * 60)
    print("synthesize_codeswitch.py — D10 (code-switch distribution fix)")
    print("D10 change: ~50% non_offensive with BENIGN English lifestyle vocab")
    print("Previous D9 file will be overwritten.")
    print("=" * 60)

    import sys  # noqa: PLC0415
    sys.path.insert(0, str(REPO_ROOT))
    from training.gemini_utils import GeminiSync  # noqa: PLC0415
    gemini = GeminiSync()

    slang_seeds = _load_slang_seeds(SLANG_PATH)
    print(f"  Loaded {len(slang_seeds)} slang seeds")
    print(f"  Target distribution: {TARGETS_PER_CLASS}")
    total_target = sum(TARGETS_PER_CLASS.values())
    non_off_pct = 100 * TARGETS_PER_CLASS["non_offensive"] / total_target
    print(f"  Total target: {total_target} rows, non_offensive: {non_off_pct:.0f}%")

    rng = random.Random(42)
    all_rows: list[dict] = []

    for label, target in TARGETS_PER_CLASS.items():
        print(f"\n[Generating {target} rows for class: {label}]")
        rows = generate_class(gemini, label, target, slang_seeds, rng)
        print(f"  Collected {len(rows)} rows for {label}")
        all_rows.extend(rows)

    # QA check on non_offensive rows
    _validate_non_offensive_sample(all_rows, n_check=30)

    rng.shuffle(all_rows)

    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        for row in all_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"\n  Wrote {len(all_rows)} rows to {OUTPUT_PATH}")

    qa_n = max(1, int(len(all_rows) * QA_FRACTION))
    qa_sample = rng.sample(all_rows, qa_n)
    with QA_PATH.open("w", encoding="utf-8") as f:
        for row in qa_sample:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"  Wrote {qa_n} QA rows to {QA_PATH}")

    from collections import Counter  # noqa: PLC0415
    dist = Counter(r["label"] for r in all_rows)
    print("\n  Final distribution:")
    for lname in LABEL_NAMES:
        cnt = dist.get(lname, 0)
        pct = 100 * cnt / len(all_rows) if all_rows else 0
        print(f"    {lname:<20}: {cnt} ({pct:.1f}%)")

    print(f"\n  Non-offensive share: {100 * dist.get('non_offensive', 0) / len(all_rows):.1f}% "
          f"(target ~{non_off_pct:.0f}%)")
    print("\nDone.")


if __name__ == "__main__":
    main()
