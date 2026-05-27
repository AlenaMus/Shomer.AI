<div dir="rtl">

# Shomer.AI — מאמרי דגל וקשר לשאלת המחקר

**סטטוס:** עודכן 2026-05-27 — מותאם לשאלת המחקר ה**מחודשת** (בריונות תלוית-הקשר + הפחתת false positives). הגרסה הקודמת (2026-05-24) עיגנה ציר רב-מודאלי שירד עתה לסטטוס **משני** — ראו `../plan-docs/decisions/research-framing.decision.md` (החלטה D-Reframe-2026-05-27).
**מקור היסטורי:** [`../plan-docs/related_work.he.md`](../plan-docs/related_work.he.md).
**ביבליוגרפיה מאומתת:** [`references.bib`](references.bib).

שאלת המחקר החדשה יושבת בצומת: **זיהוי בריונות בעברית (שפה דלת-משאבים) + שימוש בהקשר שיחתי כדי להפחית התרעות-שווא + נתונים סינתטיים-שיחתיים**. אף מאמר יחיד אינו מכסה את הצומת הזה — ובמיוחד **אין מאמר עברי על בריונות תלוית-הקשר**. זה בדיוק הפער שהפרויקט ממלא. להצהיר על כך במפורש ב-Related Work.

---

## 🇮🇱 זמינות בעברית — קודם כול, התשובה הישירה

את ביקשת דגש על עברית. האמת ההוגנת, שכדאי להציג לוועדה כ**הצדקה לפער**:

| מה קיים בעברית | מה זה נותן | מה חסר (= התרומה) |
|---|---|---|
| **SinaLab / Hamad et al. (2023)** — קורפוס פוגעני עברי | סכמת תוויות + baseline טקסטואלי | **הודעות בודדות, לא שיחות** — אין בו הקשר שיחתי כלל |
| **DictaLM 2.0 / DictaBERT / AlephBERT** | מודלים עבריים לבסיס ה-fine-tune | מודלים, לא דאטה; אינם עוסקים בבריונות או בהקשר |

**מסקנה:** אין דאטהסט עברי של **שיחות** בריונות, ואין מאמר עברי על **הקשר שיחתי**. כל מאמרי ההקשר (Pavlopoulos, Sap, SynBullying) הם **באנגלית**. זה ההצדקה: הפרויקט מעביר תובנה מוכחת באנגלית אל עברית, שבה היא טרם נבדקה — וזו תרומה לגיטימית, לא חזרה.

---

## עוגן 1 (עברי) — דאטהסט ומסגרת המשימה

**Hamad, N., Jarrar, M., Khalilia, M., & Nashif, N. (2023). "Offensive Hebrew Corpus and Detection using BERT." AICCSA 2023. arXiv:2309.02724.** `[hamad2023offensive_hebrew]`

- **דאטהסט:** https://huggingface.co/datasets/SinaLab/Offensive-Hebrew · **קוד:** https://github.com/SinaLab/OffensiveHebrew · **מאמר:** https://arxiv.org/abs/2309.02724
- **מה מספק:** 15,881 ציוצים, תיוג רב-תוויתי בחמש מחלקות — `abusive | hate | violence | pornographic | none-offensive`. רק ~1,200 פוגעניים.
- **קשר לשאלה החדשה:** מגדיר את סכמת התוויות ואת ה-baseline הטקסטואלי המבודד; **הוא בדיוק התנאי ה-context-blind** שמולו השאלה משווה. החיסרון שלו (ציוצים בודדים) הוא **המנוף** של התזה.
- ✅ **אומת (2026-05-27):** המחבר הראשי הוא **Hamad** (לא Jarrar). שם המחלקה החמישית: `none-offensive`.

---

## עוגן 2 (הקשר) — האם הקשר חשוב? *העוגן האינטלקטואלי החדש*

**Pavlopoulos, J., Sorensen, J., Dixon, L., Thain, N., & Androutsopoulos, I. (2020). "Toxicity Detection: Does Context Really Matter?" ACL 2020, עמ' 4296–4305.** `[pavlopoulos2020context]`

- **מאמר:** https://aclanthology.org/2020.acl-main.396/
- **מה מספק:** המאמר הקאנוני על הקשר. ממצא מפתח: הקשר *יכול* גם להגביר וגם להחליש רעילות נתפסת — אך שרשור-הקשר נאיבי נותן שיפור **שולי**. כלומר *איך* לנצל הקשר ביעילות הוא בעיה פתוחה.
- **קשר לשאלה החדשה:** מעגן את כל ציר ה-context-aware מול context-blind. הממצא ה"שולי" שלהם הוא בדיוק מה שהשאלה שלך בודקת מחדש — הפעם בעברית, עם מודל מודרני, ובמיקוד על **FPR** ולא רק accuracy.
- **תוסף עדכני:** *"Humans Need Context, What about Machines?"* (LREC-COLING 2024, `[humans2024context]`, https://aclanthology.org/2024.lrec-main.740/) — מראה שהתחום חי ב-2024 ומציע ארכיטקטורות מעבר ל-concatenation.

---

## עוגן 3 (התרעות-שווא) — מחיר הסיווג חסר-ההקשר

**Sap, M., Card, D., Gabriel, S., Choi, Y., & Smith, N. A. (2019). "The Risk of Racial Bias in Hate Speech Detection." ACL 2019, עמ' 1668–1678.** `[sap2019risk]`

- **מאמר:** https://aclanthology.org/P19-1163/
- **מה מספק:** הוכחה ש-classifiers חסרי-הקשר מתייגים בטעות **עד ~50%** מטקסט לא-פוגעני (בניב מסוים) כפוגעני. זו בדיוק כשל ה-false-positive שהשאלה שלך מכוונת אליו — "הנחות על בסיס המידע כמו שהוא".
- **קשר לשאלה החדשה:** מעגן את ציר ה-FP. משלים: Davidson et al. (2019), `[davidson2019racial]`, arXiv:1905.12516.

---

## עוגן 4 (מתודולוגיית נתונים) — סינתזת שיחות

מאחר שאין דאטה שיחתי עברי, הנתונים **חייבים להיווצר**. שלושת אלה מעגנים את השיטה:

- **SynBullying (Kazemi et al., 2025).** `[kazemi2025synbullying]` arXiv:2511.11599 — **התקדים הקרוב ביותר**: דאטהסט שיחתי-סינתטי לבריונות, שנוצר במספר LLMs. תבנית-שיטה ישירה.
- **ToxiGen (Hartvigsen et al., ACL 2022).** `[hartvigsen2022toxigen]` — prompting מבוסס-דוגמאות + classifier-in-the-loop; fine-tune על הסינתטי **שיפר ביצועים על טקסט אנושי**. הביסוס לכך שסינתטי עובד.
- **"Synthetic vs. Gold" (Kazemi et al., 2025).** `[kazemi2025synthetic]` arXiv:2502.15860 — עד כמה לסמוך על תוויות/דאטה סינתטיים. מבסס את עקרון **train-on-synthetic / evaluate-on-real**.

---

## עוגן 5 (מתודולוגיה) — QLoRA *(נשמר מהגרסה הקודמת)*

**Dettmers, T., Pagnoni, A., Holtzman, A., & Zettlemoyer, L. (2023). "QLoRA." NeurIPS 2023. arXiv:2305.14314.** `[dettmers2023qlora]`

- מצדיק את ה-fine-tune יעיל-הפרמטרים על מודל עברי (Qwen2.5-7B / DictaLM 2.0) → GGUF → Ollama מקומי. ✅ אומת.

---

## ציר משני (לא ראשי) — מודרציה רב-מודאלית של תמונות

ציר ה-routing של OCR-מול-VLM **ירד מסטטוס "עמוד שדרה" למסלול משני/אופציונלי** עם המעבר לשאלה השיחתית. נשמר כי תמונות מופיעות בשיחות צ'אט, וההנדסה כבר בנויה (Phase 2/4). אנלוגים תומכים: **LLaVA** (Liu et al., 2023, `[liu2023llava]`) ל-VisionBackend; **Tesseract** (Smith, 2007, `[smith2007tesseract]`) ל-OCR. ✅ שניהם אומתו. ההכרעה הסופית על מקומו של הציר הזה — במפגש 4 (ארכיטקטורה).

---

## מיפוי מאמר → שאלת מחקר (מחודש)

| מאמר | שפה | תומך ב- |
|---|---|---|
| SinaLab Offensive-Hebrew | 🇮🇱 עברית | סכמה + baseline מבודד (context-blind) |
| Pavlopoulos 2020 | אנגלית | ציר ההקשר (RQ ראשית) |
| Sap 2019 / Davidson 2019 | אנגלית | ציר ה-false-positives (RQ ראשית) |
| SynBullying / ToxiGen / Synthetic-vs-Gold | אנגלית | מתודולוגיית הנתונים הסינתטיים |
| QLoRA | — | מתודולוגיית fine-tune |
| LLaVA / Tesseract | — | ציר רב-מודאלי (משני) |

---

## פעולות פתוחות
- לאמת את רשימת המחברים של `[humans2024context]` (LREC-COLING 2024) מול ACL Anthology לפני ההגשה הסופית.
- לעדכן את קטלוג 8 ה-RQs (`../plan-docs/research_questions.md`) כך ש-RQ הראשית תהיה ההקשר/FP ולא RQ3 הרב-מודאלי — לתאם במפגש 4.

</div>
