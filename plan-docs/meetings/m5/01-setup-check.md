<div dir="rtl">

# משימה T0 — הכנת סביבה

**מפגש:** 5 (04/06/2026) · **עדיפות:** חסימה · **הערכת זמן:** 1.5 שעות · **תאריך יעד:** 31/05 · **תלוי ב:** —

## מטרה

להתקין ולאמת את כל הכלים הדרושים לאימות OCR לפני כל הרצה אחרת. אם שלב זה נכשל — שאר המשימות חסומות.

## צעדים

1. להתקין Tesseract 5.x לחלונות (Installer מ-UB Mannheim אם לא מותקן).
2. לאמת כי `heb.traineddata` קיים בתיקיית `TESSDATA_PREFIX`.
3. להתקין חבילות Python:
   - `pytesseract`, `Pillow`, `numpy`
   - `sentence-transformers` (לטעינת DictaBERT בT4)
   - `jiwer` (לחישוב CER/WER בT4)
   - `matplotlib`, `seaborn`, `pandas`, `tqdm`
4. לכתוב `scripts/ocr_validation/00_setup_check.py` — סקריפט בדיקה שמדפיס טבלת גרסאות + מריץ smoke test על 3 תמונות.
5. לשמור `requirements-ocr-validation.txt` עם גרסאות מוצמדות.

## תוצר

`scripts/ocr_validation/00_setup_check.py` + `requirements-ocr-validation.txt`

## הגדרת "בוצע"

- [ ] `tesseract --version` מציג 5.x
- [ ] `heb.traineddata` נמצא ונטען ללא שגיאה
- [ ] Smoke test: 3 תמונות נוצרו ו-OCR הורץ; פלט הודפס למסוף
- [ ] `requirements-ocr-validation.txt` נוצר עם גרסאות מוצמדות
- [ ] הסקריפט יוצא עם קוד שגיאה 1 אם Tesseract/heb.traineddata חסרים (fail-fast)

## סיכון

אם `heb.traineddata` לא מותקן — Tesseract עובד אך מחזיר זבל אנגלי. הסקריפט חייב לבדוק זאת במפורש ולא להסתמך על הנחה שהחבילה הותקנה.

</div>
