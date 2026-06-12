#!/usr/bin/env python3
"""Generate a larger multi-turn Hebrew conversation set for the HARM-CONTEXT reframe.

Target variable is NOT "is this message offensive?" but "is this message part of a
HARMFUL CONTEXT that warrants a parent alert?" -- two separate labels per item:

  * offensive_content : does the message contain offensive words on its surface?
  * alert_worthy      : is it part of a genuinely harmful situation (repetition /
                        escalation / threat / coercion / exclusion / doxxing /
                        targeting a distressed victim)?  <-- the new decision target

Ground truth comes from the GENERATION CELL (we tell Gemini what to produce, so the
label is by construction, not by Gemini's own judgment) -- this limits the
generator==judge circularity.  Still synthetic: for the MVP only, disclosed.

Output: data/gold/context_harm_v2.jsonl   (one JSON object per line)

Run from repo root:
    server\\.venv\\Scripts\\python.exe scripts\\gen_harm_context.py --per-cell 10
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "training"))
from gemini_utils import GeminiSync  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "gold" / "context_harm_v2.jsonl"

# group, offensive_content, alert_worthy, harm_signals, scenario (Hebrew instruction)
CELLS = [
    # ---- HARMFUL (alert_worthy = True) ----
    ("sustained_pileon", "harmful", True, True, ["repetition", "group_targeting"],
     "כמה משתתפים תוקפים שוב ושוב ילד אחד באותה קבוצה. ההיסטוריה מראה דפוס מתמשך של השפלות, וההודעה האחרונה היא עוד מתקפה ממוקדת."),
    ("escalation_to_threat", "harmful", True, True, ["escalation", "threat"],
     "ויכוח שמתחיל קליל ומסלים תור-אחרי-תור, עד שההודעה האחרונה היא איום פיזי מפורש ('אני אחכה לך אחרי בית הספר')."),
    ("explicit_threat", "harmful", True, True, ["threat", "violence"],
     "איום ישיר באלימות או 'אני יודע איפה אתה גר ואני מגיע אליך'. ההודעה האחרונה היא האיום."),
    ("sexual_coercion", "harmful", True, True, ["sextortion", "sexual"],
     "לחץ או סחיטה לשליחת תמונות אינטימיות ('תשלחי או שכולם יראו'). בלי תוכן מפורש — רק הדינמיקה הכופה. ההודעה האחרונה היא הסחיטה."),
    ("exclusion_campaign", "harmful", True, True, ["exclusion", "coordination"],
     "ארגון חרם חברתי מתואם נגד ילד/ה ('פתחנו קבוצה בלעדיו, אל תענו לו'). ההודעה האחרונה מארגנת את ההחרמה."),
    ("doxxing", "harmful", True, True, ["doxxing", "harassment"],
     "שיתוף פרטים אישיים (כתובת/טלפון) של מישהו כדי שיטרידו אותו. ההודעה האחרונה חושפת את הפרטים בכוונה להזיק."),
    # ---- VEILED HARMFUL: benign-looking message, harmful in context (recall-critical) ----
    ("veiled_in_context", "veiled_harmful", False, True, ["coded_threat", "continuation"],
     "ההיסטוריה קובעת איום או לעג מפורש; ההודעה האחרונה נשמעת תמימה לגמרי בפני עצמה ('נתראה מחר', 'אל תשכח מה שאמרנו') אבל בהקשר היא המשך ישיר של האיום. ההודעה האחרונה חייבת להיראות לא-פוגענית כשקוראים אותה לבד."),
    # ---- OFFENSIVE BUT NOT HARMFUL (alert_worthy = False, offensive surface) ----
    ("mutual_banter", "offensive_not_harmful", True, False, ["mutual", "consensual"],
     "הקנטות הדדיות שוויוניות בין חברים סביב משחק/ספורט. ההודעה האחרונה נשמעת עוקצנית ('שתוק יא בוט') אבל זו צחוקים הדדיים — הנמען עונה באותו טון. אין קורבן, אין יחסי כוח."),
    ("isolated_jab", "offensive_not_harmful", True, False, ["one_off", "no_pattern"],
     "עלבון חד-פעמי בודד בלי שום דפוס מתמשך; הנמען לא נפגע ועונה קליל או מתעלם. אין חזרתיות, אין הסלמה, אין יחסי כוח לא-שוויוניים."),
    ("sarcasm_friendly", "offensive_not_harmful", True, False, ["sarcasm", "supportive"],
     "סרקזם חברי/תומך בתגובה להלקאה עצמית או לסיטואציה משותפת ('וואו גאון, כל הכבוד') — נשמע עוקצני אבל נאמר בחיבה בין חברים."),
    ("reclaimed_slang", "offensive_not_harmful", True, False, ["ingroup", "affectionate"],
     "סלנג חיבה פנים-קבוצתי ('בוא הנה אחי המטורף', 'יא מטומטם שלי') שנשמע פוגעני אבל הוא רושם חיבה בין חברים קרובים."),
    # ---- BENIGN (both False) ----
    ("friendly_chat", "benign", False, False, [],
     "שיחה יומיומית רגילה בין חברים/בני משפחה: שיעורים, תכנונים, ממים, ספורט. שום דבר פוגעני."),
    ("self_or_report", "benign", False, False, ["self_directed_or_reporting"],
     "או הילד/ה מדווח/ת להורה על כך שפגעו בו/ה ומצטט/ת את התוקפן ('ילד אמר לי תמות, נפגעתי'), או הלקאה עצמית ('אני כזה לוזר היום'). הילד הוא הקורבן/הדובר — אסור לסמן זאת כתוקפנות."),
]

GEN_SYSTEM = (
    "אתה יוצר דוגמאות שיחה ריאליסטיות בעברית לבניית מערכת בטיחות שמזהה בריונות דיגיטלית בקרב בני נוער. "
    "הדוגמאות משמשות להערכה בלבד. כתוב עברית טבעית של בני 12-16 בוואטסאפ (סלנג, אימוג'ים, שגיאות קלות). "
    "החזר JSON תקין בלבד."
)

def gen_prompt(scenario: str, k: int) -> str:
    return (
        f"צור {k} שיחות וואטסאפ שונות בעברית, כל אחת מתאימה לתרחיש הבא:\n"
        f"תרחיש: {scenario}\n\n"
        f"דרישות לכל שיחה:\n"
        f"- 3 עד 6 תורים, כל תור הוא {{\"speaker\": <שם או תפקיד>, \"text\": <ההודעה>}}.\n"
        f"- התור האחרון הוא ההודעה שתנותח ('target'); שאר התורים הם ההקשר שלפניה.\n"
        f"- שמות מגוונים, סיטואציות מגוונות, עברית ריאליסטית של נוער.\n"
        f"- בלי תוכן מיני מפורש; אם התרחיש מיני — רק הדינמיקה, לא תיאור גרפי.\n\n"
        f'החזר בדיוק במבנה: {{"conversations": [{{"turns": [{{"speaker": "...", "text": "..."}}, ...]}}, ...]}}'
    )

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-cell", type=int, default=10)
    args = ap.parse_args()
    g = GeminiSync()
    rows, seen = [], set()
    for key, group, off, alert, signals, scenario in CELLS:
        try:
            res = g.call_json(
                messages=[{"role": "system", "content": GEN_SYSTEM},
                          {"role": "user", "content": gen_prompt(scenario, args.per_cell)}],
                max_tokens=4096, temperature=0.95)
        except Exception as exc:  # noqa: BLE001
            print(f"[{key}] generation FAILED: {exc}"); continue
        convs = res.get("conversations", []) if isinstance(res, dict) else []
        n_added = 0
        for conv in convs:
            turns = conv.get("turns", []) if isinstance(conv, dict) else []
            turns = [{"role": str(t.get("speaker", "peer")), "text": str(t.get("text", "")).strip()}
                     for t in turns if str(t.get("text", "")).strip()]
            if len(turns) < 2:
                continue
            message = turns[-1]["text"]
            history = turns[:-1]
            if message in seen:
                continue
            seen.add(message)
            n_added += 1
            rows.append({
                "id": f"HV-{key}-{n_added:02d}",
                "group": group, "subtype": key,
                "harm_signals": signals,
                "history": history, "message": message,
                "offensive_content": off,
                "alert_worthy": alert,
                "isolated_appearance": "offensive" if off else "non_offensive",
                "provenance": "gemini_synthetic_harm_v2",
            })
        print(f"[{key:22s}] {n_added:2d} conversations  (group={group}, alert_worthy={alert})")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    # summary
    import collections
    grp = collections.Counter(r["group"] for r in rows)
    alert = collections.Counter(r["alert_worthy"] for r in rows)
    print(f"\nTOTAL {len(rows)} items -> {OUT}")
    print("by group:", dict(grp))
    print("alert_worthy True/False:", dict(alert))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
