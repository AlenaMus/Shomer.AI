<div dir="rtl">

# Shomer.AI — סדר יום למפגש 4

**מועד:** יום א' · 31/05/2026
**מנחה:** ד"ר יורם סגל
**מציגה:** אלונה
**משך מתוכנן:** 60–90 דקות
**מטרת המפגש:** **הקפאת הארכיטקטורה + אישור ה-PRD** → שחרור לבנייה במפגש 5

---

## תוצרים שאני מביאה למפגש

| תוצר | קישור | סטטוס |
|---|---|---|
| **PRD מלא** (15 סעיפים, עם דיאגרמות) | [`PRD.md`](PRD.md) | ✅ מוכן |
| **מסמך החלטות ארכיטקטוניות** | [`architecture.decision.md`](../plan-docs/decisions/architecture.decision.md) | ✅ מוכן |
| **דיאגרמות ארכיטקטורה** (C4 + Data Flow + Sequence) | [`architecture_diagrams.md`](architecture_diagrams.md) | ✅ מוכן |
| **Reframe reconciliation** (סגירת לולאה עם M3) | [`reframe-reconciliation.decision.md`](../plan-docs/decisions/reframe-reconciliation.decision.md) | ✅ מוכן |
| **שאלות פתוחות עם ברירות מחדל** | [`open_questions.md`](open_questions.md) | ✅ מוכן |
| **תכנית עסקית** (מהמפגש הקודם, בלי שינוי) | [`business_plan.md`](business_plan/business_plan.md) | ✅ קיים |

---

## חלק 1 · עדכון סטטוס מאז מפגש 3 (10 דקות)

### מה בוצע בין M3 ל-M4 (3 ימים)

1. **שאלת מחקר מוקדה מחדש** (27/05) — ראו `D-Reframe-2026-05-27`
   - **מ:** RQ3 multimodal image routing
   - **ל:** הוספת הקשר שיחתי להפחתת FP בעברית (RQ ראשי + RQ1 כיסוד)
   - **למה:** ההכרעה הראשית של הקורס דורשת תרומה אקדמית ברורה ומדידה — ציר ההקשר נקי יותר וניתן למדידה ישירה

2. **Phase 0 deliberation** (30/05) — 4 החלטות ארכיטקטוניות + 1 OCR
   - וריאנט ארכיטקטורה: **B** (טקסט + Chat-OCR, לא vision LLM)
   - מודל בסיס: **DictaBERT-base** (Hebrew encoder)
   - צורת המערכת: **Context Agent יחיד** (לא 3 סוכנים)
   - LLM של ה-Context Agent: **GPT-4o-mini** primary, **Haiku 4.5** fallback
   - OCR engine: **Tesseract** (`heb+eng`)

3. **PRD מלא נכתב** — 15 סעיפים, כולל 3 דיאגרמות mermaid, סיכונים, NFRs, KPIs, ו-roadmap למפגשים 5–10

4. **7 שאלות מוצר נדחו** (מתועדות עם ברירות מחדל) — להכרעה בסשנים ייעודיים לפני מפגשים 5/7

### מה לא נעשה (במכוון)

- MoSCoW סופי של פיצ'רים (נדחה למפגש ייעודי)
- בנייה / קוד (חוזה לפני בנייה, per slide 9)

---

## חלק 2 · הצגת הארכיטקטורה (15–20 דקות)

**הצגה לפי דיאגרמה 1 ב-PRD סעיף 7.2** (C4 Container):
- שני קצוות לקוח (טלפון ילד + טלפון הורה)
- שרת FastAPI מקומי ברשת הביתית
- ה-pipeline המקומי: OCR → DictaBERT → Context Agent
- קריאה חיצונית רק על 15% מהמקרים (gray-zone)
- מנגנון fallback אם ה-LLM החיצוני נופל

**מסר עיקרי:** הארכיטקטורה **היא הניסוי**. אפשר להפעיל/לכבות את ה-Context Agent ולקבל ניסוי A/B נקי לסיווג context-blind מול context-aware.

**להזכיר:** דיאגרמה 3 (Sequence) מראה את ה-FP-rescue בפועל — הקייס של "תפסיק להיות כזה לוזר" שמסומן borderline (0.55), עולה ל-Context Agent, הסוכן קורא היסטוריה ומילון סלנג, מסיק שזו הקנטה ידידותית, ולא נשלחת התראה.

---

## חלק 3 · הגנת ההחלטות הארכיטקטוניות (15–20 דקות)

לכל הכרעה — **מה נבחר, למה, ומה הדחיתי**. ראו `architecture.decision.md` להגנה מלאה.

### למה Architecture B ולא A (multimodal)?
- vision LLM חלש בעברית → מערפל את ה-RQ הניסויי
- מפוצץ את התקציב (~$0.008+/interaction אם image traffic > 5%)
- הקייס המסחרי הראשי של "shomer" הוא טקסט + צילומי מסך, לא תמונות עירום
- **Architecture A מתועדת כ-future work, לא נמחקה**

### למה DictaBERT ולא Qwen / DictaLM?
- DictaBERT-base מנצח באיכות-לעלות לעברית במחלקת ה-lightweight
- אין צורך בגנרציה (ה-Context Agent מספק reasoning); encoder מספיק
- רץ על CPU → RTX 5080 פנוי לאימון

### למה Context Agent יחיד ולא 3?
- Triage ו-Alert ניתנים להחלפה בקוד דטרמיניסטי בלי לפגוע באיכות
- ~$2,500/חודש חיסכון בעולם המסחרי
- Context Agent יחיד = ה-mechanism שעונה ישירות על ה-RQ (מנגנון FP-reduction מבודד)

### למה GPT-4o-mini ולא Haiku 4.5?
- אסטרטגיית **test-cheap-first** — שני המודלים פיזית פנויים לבחירה
- מודדים F1 על gold set במפגש 8 → אם mini עומד ביעד, חוסכים $2,500/חודש בעולם המסחרי
- אם לא — Haiku בא להציל כ-fallback מתועד

### למה Tesseract ולא PaddleOCR / MLKit?
- חינם, מקומי (שומר פרטיות)
- מספיק טוב לשלב הזה; קל להחליף אם מפגש 8 יראה שזה bottleneck
- MLKit on-device מתועד כשדרוג עתידי (= פרטיות עוד יותר חזקה)

---

## חלק 4 · בקשת אישור (10 דקות)

**שואלת אישור מפורש על:**

1. ✅ הארכיטקטורה שננעלה (סעיף 7 ב-PRD)
2. ✅ ה-RQ והיעדים המדידים (סעיף 6 ב-PRD)
3. ✅ הרכיבים והגדרותיהם (סעיף 8 ב-PRD)
4. ✅ ה-NFRs וה-KPIs (סעיפים 9, 10 ב-PRD)
5. ✅ ה-Out-of-scope המכוון (סעיף 11 ב-PRD)
6. ✅ Reframe ל-RQ + ל-POC (סעיף 4 + reframe-reconciliation)

**שאלות שאני שואלת את ד"ר סגל:**

1. **האם הוויתור על Vision LLM (Architecture A) מקובל בהתחשב במיקוד ב-RQ?**
   *(אם לא — צריך להחזיר vision branch ולתכנן מפגש 7 מחדש; זמן יקר)*

2. **האם דרישת "3 סוכנים" מההצעה המקורית חייבת לחזור, או שסוכן יחיד מקיים את ה-agent mandate של הקורס?**
   *(אם חייב 3 — נצטרך לבנות Triage/Alert גם אם הם דטרמיניסטיים, רק לעמוד בדרישה)*

3. **האם יש מאמרים נוספים שכדאי לעגן בהם את החלטת הארכיטקטורה?**
   *(אנקור ראשי: Pavlopoulos 2020. מאמרים נוספים שהמנחה יציע נוסיף ל-literature_flagship)*

4. **האם 7 השאלות הפתוחות (open_questions.md) הוגנות לדחייה לסשנים ייעודיים?**
   *(לוודא שלא נופלים על שאלת מוצר קריטית במהלך הבנייה)*

---

## חלק 5 · Roadmap למפגש 5 ואילך (5 דקות)

| מפגש | תוצר ראשי | תלוי ב |
|---|---|---|
| **5** | DictaBERT-base fine-tuned על SinaLab; F1 ≥ 0.78 | אישור היום |
| **6** | סינתזת שיחות עבריות מתויגות; פיילוט Context Agent | סגירת Open Q 1, 4, 6 |
| **7** | Context Agent מלא + 3 tools + נתיב התראה | סגירת Open Q 3, 5, 7 |
| **8** | Gold set אמיתי + הערכה context-blind מול context-aware | מפגש 7 |
| **9** | סרטון Nano-Banana, שיר SUNO, דמו מלוטש | מפגש 8 |
| **10** | הגנת תזה + הגשה סופית | מפגש 9 |

---

## מה אני עושה אחרי המפגש

1. אם מאושר → tag `v0.4 Design Frozen` ב-GitHub + push כל המסמכים
2. אם יש שינויים → תיקון PRD/architecture.decision.md בו ביום, push עם תג `v0.4.1`
3. תוך 3–5 ימים: סשן ייעודי לשאלות הפתוחות 1, 4, 6 (חוסמות את מפגש 5)
4. שבוע אחרי: מתחילים מפגש 5 (fine-tune DictaBERT)

---

## תוצרים מקומיים שיוגשו (קישורים)

| תוצר | נתיב מקומי | סטטוס PDF |
|---|---|---|
| PRD מלא | [`docs/PRD.md`](PRD.md) | ⏳ ייוצר אחרי כתיבה |
| מסמך החלטות ארכיטקטוניות | [`plan-docs/decisions/architecture.decision.md`](../plan-docs/decisions/architecture.decision.md) | אנגלית, נשאר MD |
| Reframe reconciliation | [`plan-docs/decisions/reframe-reconciliation.decision.md`](../plan-docs/decisions/reframe-reconciliation.decision.md) | אנגלית, נשאר MD |
| דיאגרמות ארכיטקטורה | [`docs/architecture_diagrams.md`](architecture_diagrams.md) | ⏳ ייוצר אחרי כתיבה |
| שאלות פתוחות / Next Steps | [`docs/open_questions.md`](open_questions.md) | ⏳ ייוצר אחרי כתיבה |
| סדר יום זה | [`docs/meeting4_agenda.md`](meeting4_agenda.md) | ⏳ ייוצר אחרי כתיבה |

</div>
