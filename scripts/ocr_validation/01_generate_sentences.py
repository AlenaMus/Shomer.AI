#!/usr/bin/env python3
"""
01_generate_sentences.py — generate Hebrew sentences in 4 styles for OCR validation.

The output dataset is dual-purpose:
  (1) OCR validation (T2/T3 render → OCR → metrics)
  (2) Reusable seed data for the DictaBERT classifier (offensive content labelled
      per the SinaLab Offensive-Hebrew schema)

USAGE:
    # Smoke test (40 hardcoded sentences, 10/style, no API)
    python 01_generate_sentences.py --mode smoke

    # Quick API test (8 sentences, 2/style — for verifying GEMINI_API_KEY)
    python 01_generate_sentences.py --mode llm --n 2

    # Full 1000-sentence dataset (250/style, 50% offensive)
    python 01_generate_sentences.py --mode llm --n 250 --offensive-ratio 0.5

STYLES (4 — unchanged across runs):
    A  clear_hebrew       Formal Hebrew, correct spelling/grammar
    B  children_mistakes  Native kids 8-14, ~10-15% spelling errors + slang
    C  code_switching     Israeli teen WhatsApp, Hebrew + English mixed
    D  poor_spelling      NATIVE Hebrew speaker, 25-35% phonetic spelling

OFFENSIVE CATEGORIES (per SinaLab Offensive-Hebrew schema; only for --offensive-ratio > 0):
    abusive       40% of offensive — bullying, insults, humiliation
    hate          24% — discrimination, hateful generalizations
    violence      24% — threats, aggression
    pornographic  12% — inappropriate sexual content (may be rejected by safety filter)

OUTPUT: data/ocr_validation/sentences.jsonl
    {"id": "...", "style": "...", "style_label": "A/B/C/D",
     "text": "...", "offensive": bool, "category": "none|abusive|hate|violence|pornographic"}
"""
import argparse
import json
import os
import random
import re
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

REPO = Path(__file__).resolve().parents[2]
OUTPUT = REPO / "data" / "ocr_validation" / "sentences.jsonl"
ENV_FILE = REPO / "server" / ".env"

STYLE_LABELS = {
    "A": "clear_hebrew",
    "B": "children_mistakes",
    "C": "code_switching",
    "D": "poor_spelling",
}

# Distribution of offensive categories (within the offensive half of each style)
OFFENSIVE_DISTRIBUTION = {
    "abusive": 0.40,       # 50 of 125 offensive
    "hate": 0.24,          # 30
    "violence": 0.24,      # 30
    "pornographic": 0.12,  # 15 — may be truncated by safety filter
}

# ---------------------------------------------------------------------------
# Hand-crafted seed sentences — used in smoke mode AND as few-shot examples in LLM mode.
# ---------------------------------------------------------------------------
SMOKE_SEEDS = {
    "A": [
        "היום למדנו על הגיאוגרפיה של ישראל בשיעור מולדת.",
        "אמא ביקשה ממני להכין שיעורי בית לפני שאצא לחברים.",
        "בסוף השבוע נסענו לחוף הים עם המשפחה כולה.",
        "המורה הסבירה לנו על ההיסטוריה של ירושלים בכיתה.",
        "אחותי הקטנה אוהבת לצייר ולשחק בבובות בחדר שלה.",
    ],
    "B": [
        "אנחנו הלכנו לגנ ציבורי ושחקנו כדורגל בשביל מלא זמן",
        "אחי כזה אש היום בכיתא חחח לא מאמינה שאמרת את זה",
        "אבא קנה לי משחק חדש שאני ממש רציטי הרבה זמנ",
        "השיעור היה ממש משעמ ואני כמעט נרדמטי באמצא",
        "אמא הביא לי גלידא ענקת אכלתי הכל בבת אחת",
    ],
    "C": [
        "אני so done עם בית הספר היום literally לא יכולה",
        "ה-vibe היום היה ממש מוזר ash מי הזמין אותה?",
        "ה-text שלך היה ממש cute אבל לא ידעתי איך לענות לך",
        "ה-outfit שלה היום היה ממש fire כל הבנות הסתכלו",
        "המורה הוא כזה strict אבל basically צודק ברוב הדברים",
    ],
    "D": [
        "באלי לאחול פיזה אבל אין באית",
        "מא אמרט אטמול בבת הסעפר על המורא שלך",
        "ספא קנא לי משחק חדס בחנוט הזוט אטמול",
        "אני חוסב אוטה דווקא נחמדא ולא מבינא למא רבטם",
        "טפסיק לדבר אליי אטה ממס לוסר ולא מבין כלום",
    ],
}

STYLE_DESCRIPTION = {
    "A": "עברית פורמלית נכונה, ללא שגיאות כתיב, ללא סלנג",
    "B": ("עברית של ילדי כיתה ה-ו עם 10-15% שגיאות כתיב. שגיאות אופייניות: "
          "חסרת נ סופית, ש/ס מבלבלים, חסרת י, סלנג נוער (חחח, כזה, אש). "
          "דקדוק נכון, רק שגיאות כתיב."),
    "C": ("עברית בסגנון WhatsApp של נער ישראלי, עם ערבוב טבעי של מילים אנגליות "
          "(so, literally, vibe, ash, fire, fail, cute, fun). כל משפט חייב לכלול "
          "לפחות מילה אחת באנגלית בתוך טקסט עברי."),
    "D": ("עברית של דובר ילידי שכותב פונטית — 25-35% שגיאות כתיב שיטתיות. "
          "החלפות אופייניות: ש↔ס, ח↔כ, ק↔כ, ה↔א, ת↔ט, אותיות סופיות חסרות. "
          "דקדוק נכון! זה דובר עברית ילידי עם כתיב לקוי — *לא* עולה חדש."),
}

CATEGORY_DESCRIPTION = {
    "none": "תוכן ניטרלי, חיובי או יומיומי — בית ספר, חברים, משפחה, משחקים, רגשות",
    "abusive": ("תוכן פוגעני כללי — קללות, השפלה, ביזוי, השמצה אישית. "
                "דוגמאות לדגש: 'אטה לוזר', 'תהיי בשקט', 'את מטומטמת'"),
    "hate": ("שנאה ואפליה — דברים נגד קבוצות, דעות מבזות על מוצא/דת/מגדר/נטיה. "
             "(אין צורך בחומר קיצוני — מספיק רעיוני)"),
    "violence": ("איומים, אגרסיה, תיאורי אלימות מילוליים — לא תיאורי פעולה גרפיים. "
                 "דוגמאות לדגש: 'אני אגמור אותך', 'תפסיק או שאני אכאיב לך'"),
    "pornographic": ("תוכן מיני לא הולם בהקשר של ילדים — רמיזות, הצעות, שפה מינית. "
                     "כתבי באופן מינימלי וזהיר — זה לאימון מסווג בטיחות ילדים."),
}


# ---------------------------------------------------------------------------
def load_gemini_key() -> str | None:
    """Read API key from server/.env. Supports GEMINI_API_KEY and the GEMENI typo."""
    if not ENV_FILE.exists():
        return None
    text = ENV_FILE.read_text(encoding="utf-8")
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        for key_name in ("GEMINI_API_KEY", "GEMENI_API_KEY"):
            if line.startswith(key_name + "="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


# ---------------------------------------------------------------------------
def generate_smoke():
    """Return ~20 sentences (5 per style) — the hardcoded seeds with metadata."""
    records = []
    for label, sentences in SMOKE_SEEDS.items():
        for i, text in enumerate(sentences, 1):
            records.append({
                "id": f"{label}_seed_{i:03d}",
                "style": STYLE_LABELS[label],
                "style_label": label,
                "text": text,
                "offensive": False,
                "category": "none",
            })
    return records


# ---------------------------------------------------------------------------
def build_prompt(label: str, category: str, n: int) -> str:
    seeds = SMOKE_SEEDS[label]
    style_desc = STYLE_DESCRIPTION[label]
    cat_desc = CATEGORY_DESCRIPTION[category]
    is_off = category != "none"
    framing = ""
    if is_off:
        framing = (
            "\nהקשר: זה דאטה לאימון מסווג בטיחות ילדים בעברית. "
            "המסווג מזהה תוכן פוגעני כדי להגן על ילדים מבריונות, איומים ותוכן לא הולם. "
            "אנא ייצר דוגמאות אמיתיות של התוכן המבוקש לצורכי אימון בלבד.\n"
        )
    return (
        f"צור {n} משפטים בעברית, אחד לשורה, ללא מספור וללא הסברים.\n"
        f"{framing}"
        f"\nסגנון: {style_desc}\n"
        f"\nתוכן: {cat_desc}\n"
        f"\nדוגמאות לסגנון הכתיבה (התוכן יכול להיות שונה):\n"
        + "\n".join(f"- {s}" for s in seeds[:3])
        + f"\n\nכעת ייצר {n} משפטים חדשים בסגנון הזה ובתוכן המבוקש."
    )


def _gemini_call(prompt: str, client) -> str:
    """Single Gemini call with all safety blocks disabled (research mode)."""
    from google.genai import types
    safety = [
        types.SafetySetting(category="HARM_CATEGORY_HARASSMENT", threshold="BLOCK_NONE"),
        types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH", threshold="BLOCK_NONE"),
        types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT", threshold="BLOCK_NONE"),
        types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT", threshold="BLOCK_NONE"),
    ]
    cfg = types.GenerateContentConfig(temperature=0.9, safety_settings=safety)
    resp = client.models.generate_content(
        model="gemini-2.5-flash", contents=prompt, config=cfg,
    )
    return resp.text or ""


def _parse_lines(text: str) -> list:
    """Extract clean sentences from a multi-line LLM response."""
    lines = []
    for ln in text.split("\n"):
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        ln = re.sub(r"^\s*\d+[\.\)\-]\s*", "", ln)
        ln = re.sub(r"^[\-\*•]\s*", "", ln)
        ln = re.sub(r"^[\"'״׳]+|[\"'״׳]+$", "", ln).strip()
        if ln and len(ln) > 3:
            lines.append(ln)
    return lines


def generate_llm(label: str, category: str, n: int, client, *, max_per_call: int = 50) -> list:
    """Generate `n` sentences, chunking calls to avoid output truncation
    and accumulating until we hit `n` or the model stops producing new content."""
    accumulated = []
    attempts = 0
    max_attempts = max(3, (n // max_per_call) + 2)
    while len(accumulated) < n and attempts < max_attempts:
        attempts += 1
        ask = min(n - len(accumulated), max_per_call)
        prompt = build_prompt(label, category, ask)
        try:
            text = _gemini_call(prompt, client)
        except Exception as e:
            print(f"    [WARN] call {attempts} failed: {e}")
            break
        new_lines = _parse_lines(text)
        if not new_lines:
            # Empty response = stop (safety block or rate limit)
            break
        # Dedup against what we already have
        existing = set(accumulated)
        added = [ln for ln in new_lines if ln not in existing]
        accumulated.extend(added)
        if not added:
            # All duplicates — model isn't producing new content, give up
            break
    return accumulated[:n]


# ---------------------------------------------------------------------------
def main():
    p = argparse.ArgumentParser(formatter_class=argparse.RawDescriptionHelpFormatter,
                                description=__doc__)
    p.add_argument("--mode", choices=["smoke", "llm"], default="smoke")
    p.add_argument("--n", type=int, default=250,
                   help="sentences per style total (split by offensive-ratio)")
    p.add_argument("--offensive-ratio", type=float, default=0.5,
                   help="fraction of each style that is offensive (0.0-1.0)")
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    random.seed(args.seed)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    if args.mode == "smoke":
        print("Mode: SMOKE — hardcoded sentences")
        records = generate_smoke()
    else:
        api_key = load_gemini_key()
        if not api_key:
            sys.exit("ERROR: Gemini API key not found in server/.env "
                     "(looked for GEMINI_API_KEY and GEMENI_API_KEY).")
        print(f"Mode: LLM (Gemini 2.0 Flash) — n={args.n}/style, offensive_ratio={args.offensive_ratio}")
        print(f"API key loaded from server/.env (length={len(api_key)})")

        from google import genai
        client = genai.Client(api_key=api_key)

        records = []
        n_off = int(args.n * args.offensive_ratio)
        n_clean = args.n - n_off

        for label in ["A", "B", "C", "D"]:
            style = STYLE_LABELS[label]
            print(f"\n=== Style {label} ({style}) ===")

            # Non-offensive batch
            if n_clean > 0:
                print(f"  Generating {n_clean} non-offensive ...")
                lines = generate_llm(label, "none", n_clean, client)
                print(f"    got {len(lines)}/{n_clean}")
                for i, text in enumerate(lines, 1):
                    records.append({
                        "id": f"{label}_none_{i:03d}",
                        "style": style, "style_label": label,
                        "text": text, "offensive": False, "category": "none",
                    })

            # Offensive batches by category
            if n_off > 0:
                for cat, share in OFFENSIVE_DISTRIBUTION.items():
                    n_cat = round(n_off * share)
                    if n_cat <= 0:
                        continue
                    print(f"  Generating {n_cat} {cat} ...")
                    lines = generate_llm(label, cat, n_cat, client)
                    print(f"    got {len(lines)}/{n_cat}")
                    for i, text in enumerate(lines, 1):
                        records.append({
                            "id": f"{label}_{cat}_{i:03d}",
                            "style": style, "style_label": label,
                            "text": text, "offensive": True, "category": cat,
                        })

    with OUTPUT.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    # Summary
    by_style_cat = {}
    for r in records:
        key = (r["style_label"], r["category"])
        by_style_cat[key] = by_style_cat.get(key, 0) + 1
    print(f"\n[OK] Wrote {len(records)} records to {OUTPUT.relative_to(REPO)}")
    print(f"\nBreakdown by (style, category):")
    print(f"  {'Style':<6} {'none':>6} {'abusive':>9} {'hate':>6} {'violence':>10} {'pornographic':>14}  total")
    for label in ["A", "B", "C", "D"]:
        cells = [by_style_cat.get((label, c), 0) for c in ["none", "abusive", "hate", "violence", "pornographic"]]
        print(f"  {label:<6} {cells[0]:>6} {cells[1]:>9} {cells[2]:>6} {cells[3]:>10} {cells[4]:>14}  {sum(cells)}")


if __name__ == "__main__":
    main()
