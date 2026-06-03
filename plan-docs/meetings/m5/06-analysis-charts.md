<div dir="rtl">

# משימה T5 — גרפי ניתוח (היסטוגרמות, bar chart, confusion matrix)

**מפגש:** 5 (04/06/2026) · **עדיפות:** גבוהה · **הערכת זמן:** 2.5 שעות · **תאריך יעד:** 02/06 · **תלוי ב:** T4

## מטרה

להמחיש את תוצאות המדידה בצורה ויזואלית שניתן להציג לד"ר סגל ולכלול בדו"ח.

## 5 הגרפים הנדרשים

| מס' | סוג | תוכן |
|---|---|---|
| 1 | היסטוגרמת CER | 4 פיזורים מוחפים לפי סגנון, בצבעים שונים |
| 2 | היסטוגרמת cosine distance | 4 פיזורים (1 - cosine_sim) לפי סגנון |
| 3 | Bar chart: mean CER לפי סגנון | עם error bars (std) + קו אדום מקווקו ב-15% |
| 4 | Bar chart: mean cosine distance לפי סגנון | עם error bars |
| 5 | Confusion matrix תווים | Heatmap של 20 הזוגות הנפוצים ביותר שבלבל Tesseract |

**שמות קבצים:** `data/ocr_validation/charts/01_cer_histogram_by_style.png` ... `05_character_confusion_matrix.png`

## צעדים

1. לכתוב `scripts/ocr_validation/05_analysis_charts.py`.
2. לקרוא `metrics.csv` ו-`metrics_summary.csv`.
3. לצייר 5 גרפים ולשמור ב-`data/ocr_validation/charts/`.
4. לוודא שכותרות הגרפים באנגלית (למצגת לד"ר סגל).
5. לוודא שאותיות עבריות ב-confusion matrix מוצגות נכון (צריך גופן עברי ב-matplotlib backend).

## תוצר

`scripts/ocr_validation/05_analysis_charts.py` + `data/ocr_validation/charts/` (5 קבצי PNG)

## הגדרת "בוצע"

- [ ] כל 5 הגרפים קיימים ב-`data/ocr_validation/charts/`
- [ ] היסטוגרמת CER: ציר x מסומן 'CER', 4 פיזורים ניתנים להבחנה (legend קיים)
- [ ] Bar chart: קו 15% מצויר כקו אדום מקווקו ("pass threshold")
- [ ] Confusion matrix: 20 הזוגות המובילים מוצגים, תווים עבריים קריאים
- [ ] כל הגרפים שמורים ב-≥150 DPI (קריאים ב-PDF/מצגת)
- [ ] כותרות גרפים באנגלית

## הערה לד"ר סגל

הקו האדום ב-15% בbar chart ממחיש את קריטריון ה-pass/fail שנקבע לפני הריצה — זה מחזק את הטענה שהסף לא נקבע בדיעבד לאחר ראיית התוצאות.

</div>
