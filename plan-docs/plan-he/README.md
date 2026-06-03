<div dir="rtl">

# plan-he — תוכנית פגישות Shomer.AI בעברית

**תיקיה זו:** מבט מסונכרן-קורס על תוכנית הפרויקט, בעברית, מיושר מול המדריך המתודי הרשמי של ד"ר יורם סגל.
**מקור האמת הטכני:** `plan-docs/plan/` (קבצי האנגלית המפורטים).
**תיקיה זו היא:** מבט הקורס — מה נדרש לפי ד"ר סגל בכל פגישה, ומה Shomer.AI עושה כדי לענות.

---

## מיפוי 10 הפגישות

| פגישה | שם רשמי (קורס) | קובץ | סטטוס |
|---|---|---|---|
| 1 | בחירת נושא | [01-בחירת-נושא.md](01-בחירת-נושא.md) | ⬜ |
| 2 | שאלת מחקר | [02-שאלת-מחקר.md](02-שאלת-מחקר.md) | ⬜ |
| 3 | תכנית עסקית | [03-תכנית-עסקית.md](03-תכנית-עסקית.md) | ⬜ |
| 4 | ארכיטקטורה | [04-ארכיטקטורה.md](04-ארכיטקטורה.md) | ⬜ |
| 5 | שלד מערכת | [05-שלד-מערכת.md](05-שלד-מערכת.md) | ⬜ |
| 6 | ליבת AI | [06-ליבת-AI.md](06-ליבת-AI.md) | ⬜ |
| 7 | בדיקות | [07-בדיקות.md](07-בדיקות.md) | ⬜ |
| 8 | סרטון תדמית | [08-סרטון-תדמית.md](08-סרטון-תדמית.md) | ⬜ |
| 9 | דוח ומצגת | [09-דוח-ומצגת.md](09-דוח-ומצגת.md) | ⬜ |
| 10 | הגנה | [10-הגנה.md](10-הגנה.md) | ⬜ |

---

## טבלת פערים (Gap Analysis) — plan/ קיים מול דרישות ד"ר סגל

| נושא | קיים ב-plan/ | דרישת סגל | מצב |
|---|---|---|---|
| מסגרת VALID לבחירת נושא | ✅ `01-research-foundation` — VALID table מתועד | Value + AI-Core + Learned + Innovative + Doable | ✅ תואם |
| GitHub ריפו + מבנה תיקיות | ✅ `01` — `src/ docs/ tests/ notebooks/ results/` | GitHub מהיום הראשון, branches/tags/releases | ✅ תואם |
| שאלת מחקר מדידה | ✅ `02` + `research_questions.he.md` — 8 RQs ממוספרות | RQ מגדיר מה נמדד, מה baseline, מה = הצלחה | ✅ תואם |
| סקירת ספרות עם funnel | ✅ `02` — 15–20 מקורות, 2 anchor papers (SinaLab + QLoRA) | 15–20 → 5–8 core → 2 anchor → baseline | ✅ תואם |
| Baseline מדויק | ✅ `02` — TF-IDF + LR + F1 מספרי | baseline ≠ "כ-70%" | ✅ תואם |
| תכנית עסקית + TAM/SAM/SOM | ✅ `03` — TAM chart, competitive map, token economics | 6 חלקים, Price-vs-Value map, token costs | ✅ תואם |
| Cohen's Kappa + gold set | ✅ `08` — 3 labellers, Kappa ≥ 0.65, 300–500 דוגמאות | gold set עם inter-annotator agreement | ✅ תואם |
| 4 גרפים חובה | ✅ `08` — baseline comparison, model benchmark, sensitivity, flagship gap | 4 graph types mandatory | ✅ תואם |
| Code quality gate | ✅ `08` — Ruff, pytest, coverage, `.env` secrets | modularity, OOP, Ruff, pytest, .env | ✅ תואם |
| Prompt book | ✅ `01`+`06` — מוזכר אבל לא מובנה מלא | 7 שדות לכל רשומה: Goal/Context/Prompt/Model/Output/Evaluation/Decision | ⚠️ חסרה מבנה מפורש של 7 שדות |
| SDK — שכבת כניסה יחידה | ⚠️ `server/sdk/` placeholder בלבד; POC_Plan מגדיר כ-optional Phase 5 | SDK חובה, כל client עובר דרכו, ב-meeting 5 | ⚠️ פער קריטי — יש להכניס כ-mandatory |
| מנדט סוכני AI | ⚠️ ארכיטקטורה פתוחה עד פגישה 4; סוכנים מוזכרים כאפשרות | חובה — Path A (agent כלי פיתוח) ו/או Path B (agent במוצר) | ⚠️ פער — חייב להבטיח בפגישה 4 |
| Nano Banana — סרטון תדמית | ⚠️ `09` — מוזכר כאופציונלי | חובה: 60–90 שניות, SUNO theme song, shot list, CTA | ⚠️ צריך הפיכה ל-first-class deliverable |
| SUNO שיר נושא | ⚠️ `09` — "(Optional)" | חובה מפורשת של ד"ר סגל | ⚠️ פער — להסיר את "אופציונלי" |
| מיפוי development vs presentation | ⚠️ plan/ שם פיתוח = פגישות 5–8, הצגה = 9–10 | dev = 5–7, **סרטון = 8**, דוח = 9, הגנה = 10 | ⚠️ פגישה 8 צריכה להיות סרטון; gold set+metrics עוברים ל-7 |
| PRD לכל אלגוריתם מרכזי | ✅ `04` — PRD.md מלא + per-component PRDs | Purpose/Inputs/Outputs/Metrics/Risks/Tests לכל component | ✅ תואם |
| מטריצת בחירת מודלים | ✅ `03` — model comparison table (cost/quality/latency) | Cost/Quality/Latency/Risk/Best-use decision matrix | ✅ תואם |
| Defense backups (3 רמות) | ✅ `10` — live/recorded/screenshots | 3 demo backup levels | ✅ תואם |

### סיכום פערים קריטיים

1. **SDK** — חייב לעלות ממעמד "אופציונלי" ל-mandatory בפגישה 5.
2. **מנדט סוכנים** — חייב להיסגר בפגישה 4: Path A (Claude Code/agent בפיתוח) ו/או Path B (context/alert כסוכן).
3. **Nano Banana + SUNO** — פגישה 8 מוקדשת לסרטון תדמית + שיר נושא, לא לפיתוח.
4. **מיפוי מחדש של dev phases** — gold set + metrics עוברים לפגישה 7; פגישה 8 = סרטון בלבד.
5. **Prompt book structure** — 7 שדות מפורשים לכל רשומה, מ-meeting 1.

</div>
