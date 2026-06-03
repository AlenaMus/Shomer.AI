<div dir="rtl">

# משימה T3 — הרצת Tesseract OCR על 1000 התמונות

**מפגש:** 5 (04/06/2026) · **עדיפות:** גבוהה · **הערכת זמן:** 2.0 שעות · **תאריך יעד:** 01/06 · **תלוי ב:** T2

## מטרה

להריץ Tesseract על כל 1000 התמונות ולשמור את הפלט לצד הטקסט המקורי — הכנה למדידת השגיאות בT4.

## הגדרות OCR

| פרמטר | ערך | סיבה |
|---|---|---|
| שפה | `heb+eng` | תמיכה בערבוב עברית-אנגלית (סגנון C) |
| PSM mode | 6 — uniform block of text | מתאים לבועת צ'אט בודדת |
| OEM | 3 (LSTM default) | מדויק יותר מ-OEM 0 |

## צעדים

1. לכתוב `scripts/ocr_validation/03_run_ocr.py`.
2. לעבור על כל תמונה בכל 4 התיקיות (עם tqdm progress bar).
3. לשמור תוצאות ב-`data/ocr_validation/ocr_outputs.jsonl`: `{id, style, original_text, ocr_text, image_path}`.
4. לתעד כשלים (OCR ריק / שגיאת exception) בשדה `ocr_text: null`.
5. להדפיס סיכום: סה"כ עובד, סה"כ כשלים, אורך פלט ממוצע לכל סגנון.

## תוצר

`scripts/ocr_validation/03_run_ocr.py` + `data/ocr_validation/ocr_outputs.jsonl`

## הגדרת "בוצע"

- [ ] `ocr_outputs.jsonl` מכיל בדיוק 1000 רשומות
- [ ] שיעור כשלים מדווח: `X/1000 images produced empty OCR output`
- [ ] הסקריפט לא קורס על פלט OCR ריק (טיפול בשגיאה graceful)
- [ ] זמן ריצה מתועד (עוזר להעריך עלות הרצות עתידיות)
- [ ] `lang='heb+eng'` מוגדר כקבוע בסקריפט (לא hard-coded כאנגלית בלבד)

## הערת ביצועים

זמן ריצה צפוי: 15–20 דקות ל-1000 תמונות על Windows (CPU). אם איטי מדי — אפשר לצמצם ל-500 תמונות (125 לכל סגנון) לצורך תוצאה ראשונית מהירה.

</div>
