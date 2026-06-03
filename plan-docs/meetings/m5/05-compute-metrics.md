<div dir="rtl">

# משימה T4 — חישוב מטריקות (CER / WER / DictaBERT cosine)

**מפגש:** 5 (04/06/2026) · **עדיפות:** גבוהה · **הערכת זמן:** 3.0 שעות · **תאריך יעד:** 02/06 · **תלוי ב:** T3

## מטרה

לחשב שלוש מטריקות השוואה לכל אחת מ-1000 הרשומות: שגיאת תווים (CER), שגיאת מילים (WER), ומרחק וקטורי בין embedding של המקור לבין embedding של פלט OCR.

## הגדרות מטריקות

| מטריקה | הגדרה | ספרייה |
|---|---|---|
| **CER** | `Levenshtein(original, ocr) / len(original)` | `jiwer` או `python-Levenshtein` |
| **WER** | Levenshtein ברמת מילה / מספר מילים במקור | `jiwer` |
| **DictaBERT cosine similarity** | `cosine(embed(original), embed(ocr))` | `sentence-transformers` + `dicta-il/dictabert` |

**טיפול בכשלים:** רשומות עם `ocr_text: null` → `CER=1.0, WER=1.0, cosine_sim=0.0` (worst-case imputation, מתועד בסקריפט).

## צעדים

1. לכתוב `scripts/ocr_validation/04_compute_metrics.py`.
2. לטעון מודל DictaBERT (HuggingFace, הורדה אוטומטית בהרצה ראשונה, ~500MB).
3. לחשב 3 מטריקות לכל רשומה.
4. לשמור לכל-רשומה: `data/ocr_validation/metrics.csv` — עמודות: `id, style, cer, wer, dictabert_cosine_sim`.
5. לחשב ולשמור ממוצעים לכל סגנון: `data/ocr_validation/metrics_summary.csv` — mean / median / p90 / p95 / std.

## תוצר

`scripts/ocr_validation/04_compute_metrics.py` + `data/ocr_validation/metrics.csv` + `data/ocr_validation/metrics_summary.csv`

## הגדרת "בוצע"

- [ ] `metrics.csv` מכיל בדיוק 1000 שורות
- [ ] CER בטווח [0, 1] — assert בסקריפט
- [ ] WER חושב ואינו שלילי
- [ ] מודל DictaBERT נטען בהצלחה (הודפס לוג הטעינה)
- [ ] `metrics_summary.csv` מציג breakdown לכל סגנון עם mean/median/p90/p95/std
- [ ] fallback ל-TF-IDF cosine מתועד בסקריפט אם DictaBERT לא זמין

## אחרי ריצת T4 — בדיקת ביניים

לאחר הרצת T4, לבדוק: האם mean CER < 15% לכל 4 הסגנונות? תשובה ל"כן/לא" נמצאת כבר כאן, לפני כתיבת הגרפים והדו"ח. אם CER >> 15% — אפשר להתחיל לתכנן מעבר ל-EasyOCR במקביל לT5–T7.

</div>
