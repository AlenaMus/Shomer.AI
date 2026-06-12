<div dir="rtl">

# Shomer.AI — רשימת משימות נותרות לקראת דמו מלא + מצגת

**תאריך הפקה:** 11/06/2026 · **מצב בסיס:** ראי "Current status" ב-`CLAUDE.md` (2026-06-08 + עדכונים 2026-06-11)

---

## סיכום מצב נוכחי (מה בנוי ומה רץ)

| תחום | מצב |
|---|---|
| **שרת Python (FastAPI)** | בנוי במלואו ובדוק. כל 10 מודולי LLD מחוברים. 564 בדיקות עוברות. monitor flow (S1→S4) רץ end-to-end. |
| **מסווג DictaBERT D10** | אומן (macro-F1 0.836, ECE 0.034) ומחובר לשרת (`CLASSIFIER_MODEL_VERSION=v1.1-dictabert`). |
| **לקוח Android** | שני flavors מתקמפלים (`poc` + `client`). Child-mode (Accessibility+upload) ו-Parent-mode (alerts+digest) קיימים. **טרם רץ on-device.** |
| **Dashboard (Web)** | `dashboard/index.html` עברית RTL, קורא API של S4. |
| **SDK Kotlin** | SDK v1.0.0 — 10/10 בדיקות contract עוברות, fat-jar בנוי. |
| **שאלת המחקר — ניסוי context FP** | **MVP רץ (11/06/2026):** 61 פריטים, DictaBERT D10 + Gemini 2.5 Flash. F1 (product-level): ΔFPR −29.4pp (p=0.002) ✅ H1 עבר; Recall −7.4pp ❌ non-inferiority נכשל. F2 (prompt-level scientific): ΔFPR −2.9pp ❌ H1 לא עבר. גרפים קיימים ב-`docs/research_question/plots/`. |
| **גרפי אימון** | 7 גרפים קיימים ב-`training/outputs/dictabert-offensive/plots/`. |
| **דוחות דיוק** | `docs/accuracy_eval/ollama_vs_dictabert.md` (head-to-head DictaBERT vs Ollama). |
| **מסמך שאלת המחקר** | `docs/research_question/research_question.md`, `context_fp_test_plan.md`, `context_fp_mvp_results.md` קיימים. |
| **Gold set** | `data/gold/context_mvp_combined.jsonl` — 61 פריטים (עבר MVP); `context_gold_v1.jsonl` — 34 פריטים non-synthetic. חסר: הרחבה ל-150-200 + double-annotation (κ). |

---

## א — פערי פונקציונליות end-to-end

### א1. בדיקת אינטגרציה on-device (Android ↔ שרת)

**שם:** On-device live integration test

**למה נחוץ:** הלקוח נבנה ואומת לוגית, אבל **המסלול השלם מעולם לא רץ על מכשיר אמיתי** — זה הפריט הלא-מאומת היחיד בפרויקט כולו. בלי הרצה זו, הדמו פגיע להפתעות (הרשאות, URL base, pairing flow, accessibility).

**בעלים:** android-developer + צעד ידני של Alona

**מאמץ:** S (3-4 שעות, בעיקר setup)

**עדיפות:** **חובה לדמו** — בלוקר ראשון בדרך לדמו מלא

**מה לעשות:**
1. הפעל שרת: `.\server\.venv\Scripts\python.exe -m uvicorn server.app.main:app --host 0.0.0.0 --port 8011`
2. בנה + התקן flavor `client` (הסר APK של `poc` קודם)
3. הגדר base URL (`http://10.0.2.2:8011` לאמולטור / IP ב-LAN לטלפון)
4. בצע pairing via `/v1/parent/pairing-code`
5. הפעל AccessibilityService, שלח הודעה עברית ב-WhatsApp — ראה flag בשרת + ב-dashboard
6. ראה `integration/manual-test-flows.md` לרשימת צ'קים מלאה

---

### א2. הפעלת `MONITOR_STORE_RAW=false` (S5 privacy)

**שם:** מחיקת טקסט גולמי של הודעות שאינן מסומנות

**למה נחוץ:** כרגע הגדרה `MONITOR_STORE_RAW` קיימת אבל לא אוכפת מחיקה של טקסט לא-מסומן. זהו פריט עיקרי ב-S5 (Privacy Hardening) ונחוץ כדי להראות למרצה שהמערכת שומרת על פרטיות.

**בעלים:** backend-developer

**מאמץ:** S

**עדיפות:** **חובה לדמו** (פגיעה בפרטיות + המרצה ישאל)

---

### א3. wiring לקוח Android על `:sdk`

**שם:** החלפת `ApiService.kt` הישן בלקוח SDK

**למה נחוץ:** `ApiService.kt` בנוי ידנית ולא עובר דרך ה-SDK — כפילות לוגיקה. עבור דמו ומצגת אקדמית, הזה מדגים ש-SDK באמת בשימוש.

**בעלים:** android-developer

**מאמץ:** M

**עדיפות:** nice-to-have לדמו, חובה למצגת אקדמית

---

### א4. FCM — push notifications אמיתיות

**שם:** Firebase project + service-account JSON + `ALERTS_CHANNEL=fcm`

**למה נחוץ:** כרגע `FcmNotifier` מממומש אבל לא מחובר (`LogNotifier` הוא ה-default). הדמו מראה digest push. בלי FCM אמיתי — הדמו מראה log בלבד.

**בעלים:** backend-developer + צעד ידני של Alona (יצירת Firebase project)

**מאמץ:** M (כולל הגדרת Firebase)

**עדיפות:** nice-to-have — הדמו עובד גם עם `log`, אבל FCM אמיתי מרשים יותר

**חלופה לדמו:** הצג בשרת ש-`DigestScheduler` רץ + ה-log מציג את ה-digest.

---

### א5. Screenshot OCR path — אינטגרציה מלאה

**שם:** ScreenCaptureService + ScreenshotCoordinator + ScreenshotUploader → `/v1/monitor/image`

**למה נחוץ:** נוספו קבצי Kotlin חדשים (`ScreenCaptureService`, `ScreenshotCoordinator`, `ScreenshotUploader`) שמוסיפים מסלול screenshot OCR כגיבוי לטקסט ה-Accessibility. צריך לבדוק שהמסלול רץ end-to-end ומגיע לשרת.

**בעלים:** android-developer

**מאמץ:** M

**עדיפות:** nice-to-have לדמו בסיסי (Accessibility path מספיק), חובה אם רוצים לדמות זיהוי תמונות

---

### א6. serve-time calibration (Temperature Scaling)

**שם:** חיבור calibrator.pkl לנתיב ה-inference

**למה נחוץ:** כרגע `CALIBRATION_METHOD=none` ב-`.env.example` — raw softmax עובר לוגיקת ה-triage, מה שגורם לאזהרה ב-CLAUDE.md ש-"over-escalates benign → Context Agent". Calibration מפחית שגיאות borderline.

**בעלים:** ai-researcher-developer

**מאמץ:** M (אימון calibrator על validation set + שמירת pkl + שינוי `.env`)

**עדיפות:** nice-to-have לדמו; חשוב לדיוק מדעי

---

### א7. TLS + cleartext-off בפרודקשן

**שם:** הסרת `cleartext` permission ב-manifest לפרודקשן

**למה נחוץ:** כרגע ה-manifest מאפשר cleartext (HTTP) לצורך פיתוח. לדמו ולמצגת — חשוב לציין שבפרודקשן הדבר יוסר, ושהקוד מכיל את ה-config לכך.

**בעלים:** android-developer

**מאמץ:** S

**עדיפות:** nice-to-have (דיון תיאורטי מספיק לדמו)

---

## ב — עבודת שאלת מחקר ותוצאות

### ב1. הרחבת Gold Set מ-61 ל-150-200 פריטים

**שם:** Gold set v2 — הרחבה + double-annotation

**למה נחוץ:** ה-MVP רץ על 61 פריטים (`context_mvp_combined.jsonl`). `context_gold_v1.jsonl` מכיל 34 פריטים non-synthetic. המדגם קטן מדי לטענה מדעית חזקה. גם: **double-annotation לחישוב Cohen's κ (pre-registered D-CFP-3: κ≥0.6) לא בוצע** — זה דרישה מפורשת של פרוטוקול המחקר.

**בעלים:** ai-researcher-developer + עבודה ידנית של Alona (annotation)

**מאמץ:** L (כולל annotation)

**עדיפות:** **חובה מדעי** — H1 על 61 פריטים (בעיקר synthetic) אינו מספיק חזק לתיזה; κ הוא דרישה pre-registered

**פעולות:**
1. הוסף 44+ פריטים benign-control מ-`whatsapp_humor_examples.md` (44 placeholders)
2. הוסף more Category-A flip-cases (screenshots אמיתיים)
3. בצע double-annotation — Alona ואנוטטור שני לפריטי A/B (Category C ברור יחסית)
4. חשב κ; פריטים עם אי-הסכמה → ב-Category C או הוצאה

---

### ב2. הרצת ניסוי מלא על Gold Set מורחב

**שם:** eval_context_fp.py על gold set v2 (N≥150)

**למה נחוץ:** תוצאות MVP (61 פריטים): F2 scientific primary — H1 **לא עבר** (ΔFPR −2.9pp בלבד). F1 product-level — H1 **עבר** (ΔFPR −29.4pp, p=0.002) אבל recall non-inferiority **נכשל** (−7.4pp, threshold Y=3pp). נדרש: (א) מדגם גדול יותר להפחתת שונות; (ב) ניתוח הסבר ל-F2 weakness; (ג) E6 (selective vs naive-concat) — התרומה לספרות.

**בעלים:** ai-researcher-developer

**מאמץ:** M (הרצת הסקריפט הקיים, ניתוח תוצאות)

**עדיפות:** **חובה מדעי**

---

### ב3. ניתוח תוצאות MVP — הסבר לפערים בין F1 ל-F2

**שם:** Analysis memo: why F1 passes H1 but F2 doesn't

**למה נחוץ:** הפער בין F1 (product-level, −29.4pp) ל-F2 (prompt-level, −2.9pp) צריך הסבר מדעי. הסיבה הסבירה: ב-F2 המסווג עצמו (DictaBERT D10) ב-FPR=0% context-blind (המסווג עצמו לא מסמן false positives בבסיס F2 כלל), בעוד שב-F1 ה-triage שולח borderlines ל-CA. יש לתעד זאת כ-**finding** לתיזה — לא failure.

**בעלים:** ai-researcher-developer

**מאמץ:** S

**עדיפות:** חובה מדעי לתיזה

---

### ב4. E6 — Selective-Agent vs Naive-Concat

**שם:** ניסוי E6: הוספת זרוע naive-concat לניסוי

**למה נחוץ:** E6 הוא ה**תרומה** לספרות — תשובה לשאלת Pavlopoulos (2020) "האם context עוזר ואיך?" בעברית. כרגע רק הזרוע selective-CA נמדדת. הוספת naive-concat (ממש שרשור היסטוריה לפרומפט המסווג) מאפשרת השוואה.

**בעלים:** ai-researcher-developer

**מאמץ:** M

**עדיפות:** nice-to-have לדמו, **חובה לפרסום / חשיבות אקדמית**

---

### ב5. Honest real-only eval (D8 caveat)

**שם:** הפרדת מדדים: data synthetic-only vs real-only

**למה נחוץ:** CLAUDE.md מציין: "minority val/test partly synthetic → in-distribution numbers overstate real-world". D8 = Alona בחרה לשמור synthetic בval/test. תיזה דורשת להראות גם "honest eval" על real-only (כ-companion metric), כדי להיות כנים לגבי ה-limitation.

**בעלים:** ai-researcher-developer

**מאמץ:** S

**עדיפות:** חובה אקדמי — ה-limitation מתועדת, צריך להדגים אותה כ-finding

---

## ג — הכנת דמו

### ג1. תסריט דמו + רשימת בדיקות סביבה

**שם:** Demo script + environment checklist

**למה נחוץ:** כבר קיים `integration/manual-test-flows.md` ו-`scripts/monitor_demo.py`. נדרש **תסריט מובנה** שמראה: (1) DictaBERT D10 מסווג הודעה עברית; (2) Context Agent מוריד false positive; (3) Android child שולח → parent מקבל alert; (4) Dashboard מציג. הכנה מראש מונעת תקלות בפגישה.

**בעלים:** צעד ידני של Alona (עם הנחיות מ-backend-developer)

**מאמץ:** S

**עדיפות:** **חובה לדמו**

---

### ג2. LLM keys בסביבת הדמו

**שם:** GEMINI_API_KEY + CONTEXT_AGENT_ENABLED=true ב-server/.env

**למה נחוץ:** בלי keys — Context Agent הוא mock שמחזיר "not a threat" לכל. דמו של הפחתת false positives דורש CA אמיתי. Keys כבר הוגדרו ב-2026-06-07 (Session Update ב-CLAUDE.md) אך יש לוודא שהם עדיין בתוקף ב-`.env`.

**בעלים:** Alona (task ידני — key בתוקף)

**מאמץ:** S (אימות)

**עדיפות:** **חובה לדמו**

---

### ג3. תסריט fallback לדמו

**שם:** Fallback plan — אם Android לא עובד

**למה נחוץ:** הרצת on-device (א1) עשויה לצוץ בעיות של הרשאות / מכשיר. צריך תסריט חלופי שמדגים את כל הפונקציונליות דרך `scripts/monitor_demo.py` (in-process TestClient, ירוק ב-2026-06-08) + Dashboard ב-browser.

**בעלים:** backend-developer (עדכון demo script אם נחוץ)

**מאמץ:** S

**עדיפות:** **חובה לדמו** — ביטוח

---

### ג4. אימות שרת DictaBERT D10 — smoke test לדמו

**שם:** smoke test `/v1/model/info` + `/classify` לפני הדמו

**למה נחוץ:** לוודא שהמסווג נטען (`v1.1-dictabert`, לא fallback ל-standin), שהשרת עונה תוך זמן סביר, ושהודעה עברית מסווגת נכון.

**בעלים:** backend-developer / צעד ידני של Alona

**מאמץ:** S

**עדיפות:** **חובה לדמו**

---

## ד — מצגת ותוצרים

### ד1. מצגת גמר (PowerPoint / Reveal.js / Canva)

**שם:** בניית מצגת סיכום לדמו ולהגשה

**למה נחוץ:** הדמו דורש מצגת שמסכמת: background + RQ, ארכיטקטורה, תהליך הנתונים, תוצאות DictaBERT, תוצאות context-FP experiment, מסקנות, הגבלות.

**בעלים:** Alona (designer / co-authoring עם מנחה AI)

**מאמץ:** L

**עדיפות:** **חובה לדמו + להגשה**

**קלט מוכן (שקפים אפשריים):**
- גרפי DictaBERT: `training/outputs/dictabert-offensive/plots/` (7 גרפים: confusion matrix, per-class F1, training curves, calibration, stylistic slices)
- גרפי context-FP: `docs/research_question/plots/` (fpr_by_category, mcnemar_pairs, mvp_dashboard)
- ארכיטקטורה: `docs/design/README.md` + LLDs
- תוצאות MVP: `docs/research_question/context_fp_mvp_results.md`
- head-to-head: `docs/accuracy_eval/ollama_vs_dictabert.md` (DictaBERT 89.4% vs Ollama 37.8%, 424× faster)

---

### ד2. דוח תוצאות מסכם (עברית)

**שם:** דוח תוצאות לתיזה / למרצה (Hebrew RTL Markdown → PDF)

**למה נחוץ:** מסמך אחד שמסכם: שאלת המחקר, מה נבדק, התוצאות המספריות, מה עבר / לא עבר H1/H2, המגבלות המתועדות.

**בעלים:** hebrew-ai-project-manager skill (כאן)

**מאמץ:** M

**עדיפות:** חובה להגשה

---

### ד3. Honest eval figure — synthetic vs real numbers (companion table)

**שם:** טבלת השוואה: D10 numbers synthetic+real vs real-only

**למה נחוץ:** ב1 בתיזה. מראה כנות מדעית. נדרש להכין כ-figure או טבלה (לא רק כתוב).

**בעלים:** ai-researcher-developer

**מאמץ:** S

**עדיפות:** חובה אקדמי

---

### ד4. תיעוד מגבלות ומחקר המשך

**שם:** Limitations + Future Work section (תיזה / מצגת)

**למה נחוץ:** המגבלות ידועות ומתועדות (porn 100% synthetic, poor_spelling 0.615, F2 H1 לא עבר, gold set קטן, no κ). יש לנסח אותן כ-section ברור לתיזה.

**בעלים:** ai-researcher-developer + Alona

**מאמץ:** S

**עדיפות:** חובה לתיזה

---

## מסלול קריטי — סדר מומלץ לדמו-readiness

```
שלב 1 (חובה, לפני הדמו):
  ג2  → ודא LLM keys בתוקף ב-.env                [Alona, 30 דקות]
  ג4  → smoke test שרת DictaBERT D10               [15 דקות]
  א1  → on-device integration test                 [android-developer + Alona, 3-4 שעות]
  ג3  → fallback demo script מוכן                  [backend-developer, 1 שעה]
  א2  → MONITOR_STORE_RAW=false                    [backend-developer, 2 שעות]

שלב 2 (מדעי — לפני מצגת / הגשה):
  ב3  → ניתוח F1 vs F2 gap → כתיבת finding         [ai-researcher-developer, 2 שעות]
  ב5  → honest real-only eval                      [ai-researcher-developer, 3 שעות]
  ד3  → synthetic vs real table                    [ai-researcher-developer, 1 שעה]
  ב1  → הרחבת gold set + double-annotation         [Alona + ai-researcher-developer, L]
  ב2  → הרצת eval מלאה על N≥150                   [ai-researcher-developer, 3 שעות]

שלב 3 (מצגת + הגשה):
  ד1  → מצגת גמר                                  [Alona + doc-coauthoring, L]
  ד2  → דוח תוצאות עברית                          [hebrew-ai-project-manager, M]
  ד4  → Limitations + Future Work section          [ai-researcher-developer + Alona, S]
  א3  → wire Android על :sdk (nice-to-have)        [android-developer, M]
  ב4  → E6 selective vs naive-concat (תרומה)       [ai-researcher-developer, M]
```

---

## טבלת סיכום — עדיפויות ומאמץ

| # | משימה | עדיפות | מאמץ | בעלים |
|---|---|---|---|---|
| א1 | On-device integration test | חובה לדמו | S | android-developer + Alona |
| א2 | MONITOR_STORE_RAW=false | חובה לדמו | S | backend-developer |
| ג2 | LLM keys אמיתיים ב-.env | חובה לדמו | S | Alona |
| ג3 | Fallback demo script | חובה לדמו | S | backend-developer |
| ג4 | Smoke test DictaBERT D10 | חובה לדמו | S | Alona |
| ג1 | תסריט דמו מובנה | חובה לדמו | S | Alona |
| ב3 | ניתוח F1 vs F2 gap | חובה מדעי | S | ai-researcher-developer |
| ב5 | Honest real-only eval | חובה אקדמי | S | ai-researcher-developer |
| ד3 | Synthetic vs real table | חובה אקדמי | S | ai-researcher-developer |
| ד4 | Limitations + Future Work | חובה לתיזה | S | ai-researcher-developer + Alona |
| ב1 | Gold set v2 (150-200 + κ) | חובה מדעי | L | Alona + ai-researcher-developer |
| ב2 | Eval מלאה על gold set v2 | חובה מדעי | M | ai-researcher-developer |
| ד1 | מצגת גמר | חובה להגשה | L | Alona |
| ד2 | דוח תוצאות עברית | חובה להגשה | M | hebrew-ai-project-manager |
| א5 | Screenshot OCR path | nice-to-have | M | android-developer |
| א6 | Serve-time calibration | nice-to-have | M | ai-researcher-developer |
| א3 | Wire Android על :sdk | nice-to-have | M | android-developer |
| ב4 | E6 selective vs naive-concat | חשוב אקדמי | M | ai-researcher-developer |
| א4 | FCM push notifications | nice-to-have | M | backend-developer + Alona |
| א7 | TLS cleartext-off prod | nice-to-have | S | android-developer |

---

## הערות שדורשות שיפוט של Alona

1. **תוצאות MVP context-FP:** F2 (primary scientific) לא עבר H1 (ΔFPR = −2.9pp, p=1.00). הסיבה הסבירה: DictaBERT D10 עם FPR=0% baseline ב-F2 — כלומר המסווג עצמו לא עושה FPs בתנאי "context blind" ב-F2. **שאלה לAlona:** האם להציג את F1 (product-level, ΔFPR −29.4pp, p=0.002) כ-primary result במצגת? זה positive result. F2 כ-companion analysis ייסביר למה לוגיקת ה-triage היא המקום שבו context עוזר. **או** — להרחיב את gold set ולחזור.

2. **Gold set size:** 61 פריטים (MVP) לעומת היעד 150-200 של הפרוטוקול הרשום. האם יש לדחות את המצגת עד שהאוסף יהיה גדול יותר, או להציג MVP כ-"preliminary results" ולציין בבירור שמדובר בתוצאות ראשוניות?

3. **Double-annotation (κ):** D-CFP-3 pre-registered κ≥0.6. טרם בוצע. **שאלה:** האם יש אנוטטור שני? אם לא — יש לתעד זאת כ-limitation.

---

**קבצים רלוונטיים:**
- `docs/research_question/context_fp_mvp_results.md` — תוצאות MVP
- `docs/research_question/plots/` — גרפי ניסוי context-FP
- `training/outputs/dictabert-offensive/plots/` — גרפי אימון DictaBERT
- `data/gold/context_mvp_combined.jsonl` — gold set MVP (61 פריטים)
- `data/gold/context_gold_v1.jsonl` — gold set non-synthetic (34 פריטים)
- `docs/accuracy_eval/ollama_vs_dictabert.md` — head-to-head comparison
- `integration/manual-test-flows.md` — checklist לדמו on-device
- `scripts/monitor_demo.py` — demo script (in-process, ירוק)
- `scripts/eval_context_fp.py` — paired runner לניסוי המחקר

</div>
