<div dir="rtl">

# משימה T7 — מסמך החלטה: מנוע OCR (אנגלית)

**מפגש:** 5 (04/06/2026) · **עדיפות:** גבוהה · **הערכת זמן:** 1.0 שעות · **תאריך יעד:** 03/06 · **תלוי ב:** T6

## מטרה

לתעד את החלטת הארכיטקטורה לגבי מנוע ה-OCR בפורמט הסטנדרטי של הפרויקט — עם מספרי CER אמיתיים מהמדידה. מסמך זה סוגר (או פותח מחדש) את `D-Arch-OCR` מ-`plan-docs/decisions/architecture.decision.md`.

## שני מסלולים אפשריים

**מסלול A — Tesseract עובר (CER < 15% לכל הסגנונות):**
- Choice: "Keep Tesseract"
- Why: מספרי CER אמיתיים מאשרים כשירות
- הפרויקט ממשיך לפיין-טון DictaBERT

**מסלול B — Tesseract נכשל (CER ≥ 15% בסגנון אחד או יותר):**
- Choice: "Migrate to EasyOCR"
- Why: מספרי CER מראים כשל מתחת לסף
- Alternatives: ואחר המסמך כולל תכנית מעבר קונקרטית

## דרישות מסמך

- קובץ: `plan-docs/decisions/ocr-engine-validation.decision.md`
- אנגלית (לפי מוסכמות הפרויקט למסמכי החלטה)
- פורמט סטנדרטי: `D-id, Question, Choice, Why, Alternatives considered, Revisit`
- לכלול מספרי CER אמיתיים (לא placeholder)
- לקשר ל-`data/ocr_validation/` ול-`docs/ocr_validation_report.md`

## תוצר

`plan-docs/decisions/ocr-engine-validation.decision.md`

## הגדרת "בוצע"

- [ ] הקובץ עוקב אחרי פורמט ה-`D-id / Question / Choice / Why / Alternatives / Revisit` הסטנדרטי
- [ ] חלק ה-Choice מצטט מספרי CER אמיתיים (לא ערכי placeholder)
- [ ] אם Tesseract נכשל: חלק Alternatives כולל תכנית מעבר קונקרטית ל-EasyOCR עם הערכת מאמץ
- [ ] חלק Revisit מפנה למפגש 8 (הערכת gold-set) כנקודת ביקורת הבאה
- [ ] הקובץ באנגלית
- [ ] הקובץ מפנה לריצת האימות: `data/ocr_validation/` ו-`docs/ocr_validation_report.md`

</div>
