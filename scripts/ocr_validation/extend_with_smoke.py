#!/usr/bin/env python3
"""Append 40 hand-crafted smoke seeds (10 per style) to sentences.jsonl.

These are validated, controlled samples — not from any LLM. They give us
ground-truth baseline samples per style alongside the 1000 LLM-generated
samples. Total after this: 1040.

All smoke records are labelled offensive=false, category="none" — they
exist only to add per-style ground-truth diversity.
"""
import json
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

REPO = Path(__file__).resolve().parents[2]
SENTENCES = REPO / "data" / "ocr_validation" / "sentences.jsonl"

EXTRA_SEEDS = {
    "A": [
        "השעון על הקיר בכיתה מראה רבע אחרי שלוש בצהריים.",
        "הזמנתי בקיוסק שתי סוכריות גומי ושוקולד חלב.",
        "הסבא של חברתי נולד בפולין ועלה לישראל בילדותו.",
        "מה דעתך לבוא אלי הביתה אחרי בית הספר ולעשות שיעורים?",
        "הכלב של השכנה מאוד נחמד אבל קצת גדול ועוקצני.",
        "בקיץ אנחנו אוהבים ללכת לבריכת השכונה כל יום.",
        "אחותי הגדולה מתחתנת בקיץ הבא וכבר התחילו להכין.",
        "ראיתי בטיסה הראשונה שלי את הים מאוד גדול ויפה מלמעלה.",
        "למדנו היום בכיתה על הצמחים ועל איך הם גדלים בטבע.",
        "הסבתא הכינה לי ארוחת בוקר עם חביתה ולחם שום טעים.",
    ],
    "B": [
        "אכלטי בארוכת בוקר חביטא וגבינא וזה היה מצויאן",
        "אחי הגדול שיחק עם המשקפים שלי וסבר אותם בטעות",
        "אבא אמ אני יכולה ללכת לסחק אבל לפני זה לעסות סיעורים",
        "ראיטי סרט פעם סני אטמול בלילא והוא יוטר מצחיק",
        "הילדים בכיטה צוחקים על אורי מטי סאוט לא בא לאספא",
        "אמא סמא אחותי מירל רוזא לישון אבל היה כבר מאוחר",
        "כתבטי שיעור בית בעבודאת אסתר אבל לא הגענו לזא",
        "החברה שלי כעסת על הילדים סהציקו לה במגרס",
        "אבא לא רוצא שאני אסכק במחסב יותר משעא ביום",
        "סבא שלי מספר לי סיפורים מטחילתת הילדות סלו",
    ],
    "C": [
        "הסרט בסוף היה ממש cliché אבל אני בכלל נהניתי",
        "אני need לקנות ספר חדש לבית הספר היום מתישהו",
        "תראי איזה new bag רכשתי אתמול בקניון ב-sale",
        "אמא thought שאני לא אבחין ב-surprise אבל הצלחתי לראות",
        "הכיתה היתה total mess בסוף השיעור היום אש",
        "ה-summer הזה אנחנו נוסעים for sure לים תיכון",
        "אחותי has been crying all morning כי איבדה את הצעצוע",
        "למדתי לעצב בעצמי את האתר ה-website שלי הקטן",
        "ה-classroom שלנו ממש hot היום ה-air conditioning שבור",
        "אני lowkey רוצא ללכת לחגיגה אבל אני also לא בטוחא",
    ],
    "D": [
        "כעט אני יוסבט בכדר וכוסב לעסות אט הסיעורים",
        "אטמול ראיטי טמונא יפא סל ים אדום בכרט סל אבא",
        "סלסום הלכטי לסחק בפרק עם הכברים סלי וכלם נהנו",
        "הסטוריא היא מקסוע סאני סונא בעולמ הכי הרבא",
        "הכי טוב בעולמ זא לאחול גלידא אכרי המסעיא",
        "סלסום הסטוריא היטא ארוכא ולא הספאקטי לסטוט הקול",
        "כעט אני הולכט לסון כי אני עיף ממס מהיום הזא",
        "אכי הקטן רא בוכא הוא רוצא אט הצאצוע סהיא גנבא",
        "טפסיק לדבר אלי אטה ממס אי לא רוצא אטכא",
        "סלסום נסענו לסטכ בכי טוב מהעולמ הזא היא מקום ביאט",
    ],
}

STYLE_LABELS = {
    "A": "clear_hebrew",
    "B": "children_mistakes",
    "C": "code_switching",
    "D": "poor_spelling",
}


def main():
    records = [json.loads(l) for l in SENTENCES.read_text(encoding="utf-8").splitlines()]
    print(f"Existing records: {len(records)}")

    appended = 0
    for label, texts in EXTRA_SEEDS.items():
        for i, text in enumerate(texts, 1):
            rec = {
                "id": f"{label}_smoke_{i:03d}",
                "style": STYLE_LABELS[label],
                "style_label": label,
                "text": text,
                "offensive": False,
                "category": "none",
            }
            records.append(rec)
            appended += 1

    with SENTENCES.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"Appended: {appended}")
    print(f"Total now: {len(records)}")


if __name__ == "__main__":
    main()
