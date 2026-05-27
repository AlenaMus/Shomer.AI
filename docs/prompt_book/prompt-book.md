<div dir="rtl">

# Shomer.AI — ספר פרומפטים (Prompt Book)

**מטרה:** תיעוד כל שימוש משמעותי בסוכן AI בפרויקט — דרישת הקורס (חוק הזהב + ספר פרומפטים, שקופיות 4–5, 14).
**Path A (סוכן ככלי פיתוח):** הרשומות כאן מתעדות את **Claude Code** כסוכן פיתוח לאורך הפרויקט — ניסוח, הרכבה, אימות, ארגון. זהו חלק ממנדט הסוכנים (ראו [`preparatory_report.md`](preparatory_report.md) רכיב 7).
**פורמט:** 7 שדות לכל רשומה — Goal · Context · Prompt · Model · Output · Evaluation · Decision.

> **הערה:** הפרומפטים מצוטטים בתמצית. הניסוח המלא נמצא בהיסטוריית השיחה ובהגדרות הסוכנים שהורצו.

---

## רשומה 1 — הרכבת תוצרי מפגש 3 (במקביל, מבוססת-סוכנים)

| שדה | תוכן |
|---|---|
| **Goal (מטרה)** | להכין את ארבעת תוצרי מפגש 3 — דו"ח מכין, שאלת מחקר, מאמרי דגל, תכנית עסקית — בחלון של 4 ימים. |
| **Context (הקשר)** | מקורות קיימים: Proposal, `plan-he/`, `research_questions.he.md`, `related_work.he.md`, ה-decision log. דרישת "הרכבה והתאמה", לא יצירה מאפס. |
| **Prompt (פרומפט)** | *"בוא נמשיך לבצע את ההכנות לקראת מחר 28-05 ... להכין דו"ח מכין מפורט, למצוא שאלת מחקר ... להכין תכנית עסקית ולהכין מאמרי דגל ... במקביל על ידי skills מתאימים לכל משימה."* |
| **Model (מודל)** | Claude Opus 4.7 (1M context) — orchestrator; שני sub-agents (`general-purpose`) במקביל ברקע. |
| **Output (פלט)** | חלוקה: סוכן A → תכנית עסקית LaTeX; סוכן B → אימות ציטוטים; ה-thread הראשי → דו"ח מכין + ספר פרומפטים. |
| **Evaluation (הערכה)** | זוהתה מראש מתיחות מסגור (Proposal מול docs/) ואומתה מול ה-decision log לפני כתיבה — נמנע תוצר סותר. |
| **Decision (החלטה)** | ✅ התקבל. לעקוב אחרי המסגור המתועד (RQ3 ראשית + ארכיטקטורה פתוחה למפגש 4), לא לפתוח החלטות נעולות. |

---

## רשומה 2 — אימות ציטוטים של מאמרי הדגל

| שדה | תוכן |
|---|---|
| **Goal (מטרה)** | לאמת ולתקן את הציטוטים של מאמרי הדגל לפני ההגשה; לפתור את ה-⚠️ על ציטוט SinaLab. |
| **Context (הקשר)** | `literature_flagship.md` סימן את ציטוט SinaLab כטעון-אימות; "Jarrar et al." היה ניחוש. המסגור (שני עוגנים) נעול ואסור לשנותו. |
| **Prompt (פרומפט)** | *"Verify and format citations ... resolve the SinaLab ⚠️ ... never fabricate a citation, arXiv id, or DOI ... do NOT change the framing."* |
| **Model (מודל)** | Claude (`general-purpose` sub-agent) + WebSearch/WebFetch (arXiv, IEEE Xplore, ACL Anthology, GitHub). |
| **Output (פלט)** | ציטוט SinaLab מתוקן: **Hamad, N., Jarrar, M., Khalilia, M., & Nashif, N. (2023). "Offensive Hebrew Corpus and Detection using BERT." AICCSA. arXiv:2309.02724.** + תיקון DictaLM 2.0 (Shmidman et al., 2024, arXiv:2407.07080) + יצירת `references.bib`. |
| **Evaluation (הערכה)** | מאומת מול arXiv/IEEE/ACL. ה-DOI של SinaLab נגזר מ-doc 10479258 וסומן לאימות-סופי (IEEE החזיר 401). שום ציטוט לא הומצא. |
| **Decision (החלטה)** | ✅ התקבל ועודכן in-place. נותר: אימות סופי של ה-DOI לפני ההגשה הסופית. |

---

## רשומה 3 — כתיבת תכנית עסקית ב-LaTeX

| שדה | תוכן |
|---|---|
| **Goal (מטרה)** | תכנית עסקית 6 סעיפים ב-LaTeX (עברית RTL), מוכנה לקימפול ב-Overleaf (XeLaTeX). |
| **Context (הקשר)** | מקורות: Proposal §2.3/§3/§4/§9.1/§11.3 + `plan-he/03`. אין מנוע LaTeX מקומי → חייב להיות Overleaf-ready. דרישה: לסמן מספרים לא-ממוקרים `[למקור]`, לא להמציא. |
| **Prompt (פרומפט)** | *"Author a 6-section business plan in LaTeX ... XeLaTeX + polyglossia + bidi ... token-economics formula + worked example ... mark unsourced numbers [למקור]. No invented citations."* |
| **Model (מודל)** | Claude (`general-purpose` sub-agent) + WebSearch (גודל שוק, דמוגרפיה CBS, תמחור מתחרים, תמחור טוקנים). |
| **Output (פלט)** | `docs/business_plan/business_plan.tex` + `README.md` עם הוראות קימפול ורשימת מספרים טעוני-מקור. *(ראו דוח הסוכן בסיום הריצה.)* |
| **Evaluation (הערכה)** | אומתו בוויב (footnotes): גודל שוק ~$1.55B→$1.74B/CAGR ~9.8–12.25%; ~2.25M משפחות בישראל (CBS); תמחור Bark/Qustodio/Canopy; מחירי טוקנים Claude Haiku/GPT-4o-mini/Gemini Flash. נשארו `[למקור]`: קוהורט SAM מדויק (6–16 עם סמארטפון), SOM (5,000 / ₪40 — יעד פנימי), מחירי Keepers/Bosco, והנחות נפח ה-token-economics. שום ציטוט לא הומצא. |
| **Decision (החלטה)** | טיוטה מובנית להצגה במפגש 3; מספרי token-economics ממוקרים-במלואם נדחים לאחרי המפגש (ראו `next-meeting-prep`). |

---

## תבנית לרשומה חדשה (להעתיק)

| שדה | תוכן |
|---|---|
| **Goal** | |
| **Context** | |
| **Prompt** | |
| **Model** | |
| **Output** | |
| **Evaluation** | |
| **Decision** | |

</div>
