#!/usr/bin/env python3
"""
01_generate_sentences.py — generate Hebrew sentences in 4 styles for OCR validation.

USAGE:
    python 01_generate_sentences.py --mode smoke              # 8 hardcoded sentences (2/style)
    python 01_generate_sentences.py --mode llm --n 250        # 250/style via GPT-4o-mini

STYLES:
    A - clear_hebrew      Formal Hebrew, correct spelling/grammar, no slang
    B - children_mistakes Native kids ages 8-14, ~10-15% spelling errors + slang
    C - code_switching    Israeli teen WhatsApp, Hebrew + English mixed
    D - poor_spelling     NATIVE Hebrew speaker (not immigrant!) with 25-35% phonetic
                          spelling errors. Grammar correct.

OUTPUT: data/ocr_validation/sentences.jsonl
        {"id": "A_001", "style": "clear_hebrew", "text": "...", "style_label": "A"}
"""
import argparse
import json
import os
import random
import re
import sys
from pathlib import Path

# Force UTF-8 stdout — without this, Windows PowerShell (cp1252) garbles Hebrew prints
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

REPO = Path(__file__).resolve().parents[2]
OUTPUT = REPO / "data" / "ocr_validation" / "sentences.jsonl"

STYLE_LABELS = {
    "A": "clear_hebrew",
    "B": "children_mistakes",
    "C": "code_switching",
    "D": "poor_spelling",
}

# Hand-crafted seeds — used directly in smoke mode AND as few-shot for LLM mode.
SMOKE_SEEDS = {
    # A — Clear Hebrew: formal, correct spelling/grammar. No slang.
    "A": [
        "היום למדנו על הגיאוגרפיה של ישראל בשיעור מולדת.",
        "אמא ביקשה ממני להכין שיעורי בית לפני שאצא לחברים.",
        "בסוף השבוע נסענו לחוף הים עם המשפחה כולה.",
        "המורה הסבירה לנו על ההיסטוריה של ירושלים בכיתה.",
        "אחותי הקטנה אוהבת לצייר ולשחק בבובות בחדר שלה.",
        "נכנסתי לחדר השינה והבחנתי שאבא כבר חזר מהעבודה.",
        "הקבוצה שלנו ניצחה במשחק הכדורסל ארבעים שלושים שש.",
        "אנחנו לומדים מתמטיקה ואנגלית במשך שש שעות בכל יום.",
        "המורה החדש מאוד נחמד ומסביר את החומר בצורה ברורה.",
        "בקיץ אנחנו מתכננים לטוס לאיטליה ולבקר ברומא ובמילאנו.",
        "בחופש הגדול אנחנו טסים ליוון לטיול משפחתי בן שבועיים.",
        "אבא תיקן את הברז במטבח שדלף כל הלילה.",
        "הילדים בכיתה התרגשו מאוד לקראת המסיבה בסוף השנה.",
        "ראיתי סרט מעולה אתמול בלילה עם החברות מבית הספר.",
        "המורה למתמטיקה הסבירה לנו על משוואות חדשות בכיתה.",
        "בן הדודה שלי עולה לכיתה ז' בשנה הבאה ואני שמח בשבילו.",
        "כשירד הגשם בחורף יצאנו לשחק בחוץ עם המעיל החדש.",
        "ביום הולדתי קיבלתי אופניים מתנה מהדודה אורה.",
        "נשארתי בבית הספר עד ארבע בגלל החזרה למחזמר השנתי.",
        "אמא הכינה עוגה לסוף השבוע עם שוקולד צ'יפס ומחית בננה.",
        "סבא של שירי גר ברעננה ובא לבקר אותנו פעם בחודש.",
        "הזמנתי ספר חדש על חיות הבר באפריקה דרך הספרייה.",
        "אנחנו מתכננים לחגוג את חנוכה בבית סבתא בחיפה השנה.",
        "אחרי הצהריים פגשתי את החברה הכי טובה שלי בקניון.",
        "המורה אמרה לנו שמחר יהיה מבחן בלשון על שורשים.",
    ],
    # B — Children's Hebrew: native kids ages 8-14, ~10-15% spelling errors + slang.
    # Common errors: missing nun-sofit, ש/ס confusion, missing yod, casual spelling.
    "B": [
        "אנחנו הלכנו לגנ ציבורי ושחקנו כדורגל בשביל מלא זמן",
        "אחי כזה אש היום בכיתא חחח לא מאמינה שאמרת את זה",
        "אבא קנה לי משחק חדש שאני ממש רציטי הרבה זמנ",
        "המורא בכיטה כעסה כי הילדים דיברו ולא הקשיבו לה",
        "ביטה הסטיברסט שלי גועלי קצת ואני לא אוכלת לסעוד שמ",
        "אמא אמרא לי לא לאחר לבית הספר אבל איחרתי בכ זאט",
        "השיעור היה ממש משעמ ואני כמעט נרדמטי באמצא",
        "החברה שלי כעט כועסת עלי בלי שום סיבא רגישונית",
        "הלכנו לבריכא עם החברות וזה היה כזה כיפ אש",
        "אבא הביא לי גלידה אחרי שעשיתי שיעורי בית כמו ילדה טובא",
    ],
    # C — Code-switching: Israeli teen WhatsApp, Hebrew + English words mixed.
    # Common patterns: English emotion/exclamation words inside Hebrew sentences.
    "C": [
        "אני so done עם בית הספר היום literally לא יכולה",
        "ה-vibe היום היה ממש מוזר ash מי הזמין אותה?",
        "התגלגלתי מצחוק מהמשעמ בשיעור היה ממש funny אתה יודע",
        "הסרט היה כזה boring שנרדמתי באמצא, omg איך זה אפסרי",
        "ה-text שלך היה ממש cute אבל לא ידעתי איך לענות לך",
        "אני so excited לטיול שבת אנחנו holdable למלא דברים",
        "אחותי כל הזמן on her phone ואמא מתעצבנת עליה בטירוף",
        "ה-outfit שלה היום היה ממש fire כל הבנות הסתכלו",
        "אני need ללכת לקנות חולצה חדשה ל-event בסוף שבוע",
        "המורה הוא כזה strict אבל basically צודק ברוב הדברים",
    ],
    # D — Poor spelling (NATIVE Hebrew speaker, phonetic illiterate style).
    # Grammar correct, but heavy phonetic errors: ש↔ס, ח↔כ, ק↔כ, ה↔א, ת↔ט,
    # missing finals, word boundaries off, missing letters.
    "D": [
        "באלי לאחול פיזה אבל אין באית",
        "מא אמרט אטמול בבת הסעפר על המורא שלך",
        "ספא קנא לי משחק חדס בחנוט הזוט אטמול",
        "אני חוסב אוטה דווקא נחמדא ולא מבינא למא רבטם",
        "אמא תעסי לי קפא בבקסא אני ממס עיף עכסיו",
        "טפסיק לדבר אליי אטה ממס לוסר ולא מבין כלום",
        "אכלטי ארוחט ערב כעט אני סבעא מאוד תודא לאמא",
        "פגסטי חבר שלסום בכניון והוא קנא בגדים חדסים",
        "מורי ההסטוריא היא כאן עכסיו מסביר על המלכמא הסניא",
        "האכ סלי עוסא סיעורי בית בכדר ואמא מקיסא לו ספרים",
    ],
}


def generate_smoke():
    """Return exactly 8 sentences (2 per style) — the hardcoded seeds."""
    records = []
    for label, sentences in SMOKE_SEEDS.items():
        for i, text in enumerate(sentences, 1):
            records.append({
                "id": f"{label}_{i:03d}",
                "style": STYLE_LABELS[label],
                "text": text,
                "style_label": label,
            })
    return records


def generate_llm(n_per_style: int):
    """Generate `n_per_style` sentences per style via GPT-4o-mini."""
    if not os.environ.get("OPENAI_API_KEY"):
        sys.exit("ERROR: OPENAI_API_KEY not set. Either set it or use --mode smoke.")
    try:
        from openai import OpenAI
    except ImportError:
        sys.exit("ERROR: openai package missing. pip install openai")

    client = OpenAI()
    records = []
    for label, prompt in _build_prompts(n_per_style).items():
        print(f"  Generating {n_per_style} sentences for style {label} ({STYLE_LABELS[label]}) ...")
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.9,
        )
        raw = resp.choices[0].message.content
        lines = [
            re.sub(r"^\s*\d+[\.\)]\s*", "", ln.strip())
            for ln in raw.split("\n")
            if ln.strip() and not ln.strip().startswith("#")
        ]
        lines = lines[:n_per_style]
        for i, text in enumerate(lines, 1):
            records.append({
                "id": f"{label}_{i:03d}",
                "style": STYLE_LABELS[label],
                "text": text,
                "style_label": label,
            })
    return records


def _build_prompts(n: int) -> dict:
    s = SMOKE_SEEDS
    return {
        "A": (f"צור {n} משפטים בעברית פורמלית ונכונה, אחד לשורה, ללא מספור. "
              "נושאים: חיי בית-ספר, חברים, משחקים, רגשות. ללא תוכן פוגעני. "
              f"דוגמאות:\n{chr(10).join(s['A'])}"),
        "B": (f"צור {n} משפטים בעברית של ילדי כיתה ה-ו עם 10-15% שגיאות כתיב. "
              "שגיאות אופייניות: חסרת נ סופית, ש/ס מבלבלים, חסרת י, סלנג נוער. "
              "דקדוק נכון, רק שגיאות כתיב. אחד לשורה, ללא מספור. "
              f"דוגמאות:\n{chr(10).join(s['B'])}"),
        "C": (f"צור {n} משפטים בעברית בסגנון WhatsApp של נער ישראלי, "
              "עם ערבוב טבעי של מילים אנגליות. "
              "כל משפט חייב לכלול לפחות מילה אחת באנגלית בתוך טקסט עברי. "
              "אחד לשורה, ללא מספור. "
              f"דוגמאות:\n{chr(10).join(s['C'])}"),
        "D": (f"צור {n} משפטים בעברית של דובר ילידי שכותב פונטית — 25-35% שגיאות כתיב שיטתיות. "
              "החלפות אופייניות: ש↔ס, ח↔כ, ק↔כ, ה↔א, אותיות סופיות חסרות. "
              "דקדוק נכון! רק כתיב פונטי-שגוי. "
              "זה דובר עברית ילידי עם כתיב לקוי, *לא* עולה חדש. "
              "אחד לשורה, ללא מספור. "
              f"דוגמאות:\n{chr(10).join(s['D'])}"),
    }


def main():
    p = argparse.ArgumentParser(formatter_class=argparse.RawDescriptionHelpFormatter,
                                description=__doc__)
    p.add_argument("--mode", choices=["smoke", "llm"], default="smoke")
    p.add_argument("--n", type=int, default=250, help="sentences per style (LLM mode only)")
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    random.seed(args.seed)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    if args.mode == "smoke":
        print("Mode: SMOKE — 8 hardcoded sentences (2 per style)")
        records = generate_smoke()
    else:
        print(f"Mode: LLM — {args.n} per style via GPT-4o-mini")
        records = generate_llm(args.n)

    with OUTPUT.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    by_style = {}
    for r in records:
        by_style[r["style_label"]] = by_style.get(r["style_label"], 0) + 1
    print(f"\n[OK] Wrote {len(records)} records to {OUTPUT.relative_to(REPO)}")
    for label in sorted(by_style):
        print(f"    Style {label} ({STYLE_LABELS[label]}): {by_style[label]}")
    print("\nSpot-check (first sentence of each style):")
    seen = set()
    for r in records:
        if r["style_label"] not in seen:
            print(f"  [{r['style_label']}] {r['text']}")
            seen.add(r["style_label"])


if __name__ == "__main__":
    main()
