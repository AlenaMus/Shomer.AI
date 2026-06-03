<div dir="rtl">

# Shomer.AI — טכניקות עיבוד נתונים לסיווג עברית (DictaBERT)

**מסמך:** מדריך טכניקות לעיבוד נתונים — אילו טכניקות יש, מה כל אחת עושה, איך היא עוזרת ל-F1 / latency, מתי לשלב, מתי לסכן.
**משלים את:** [`dictabert_classifier_architecture.md`](dictabert_classifier_architecture.md) (תכנון הרשת) · [`bullying_data_he.md`](../../data/bullying_data_he.md) (אסטרטגיית מקורות הנתונים)
**סטטוס:** טיוטה למפגש 5 · 2026-06-03
**שימוש:** הברייף ל-`ai-researcher-developer` שיכתוב `training/prepare_data_dictabert.py` מסתמך ישירות על המסמך הזה.

---

## §1 · תקציר מנהלים

יש לנו **עשרות טכניקות נתונים** שיכולות לשפר את F1 או לזרז את האימון/inference. בפועל — לא כולן בטוחות יחד. המסמך הזה:

1. ממפה את **כל הטכניקות** שדנו בהן, בקבוצות לפי מטרה (ניקוי / יעילות / איזון / Split / augmentation).
2. מסביר **מה כל טכניקה עושה** מבחינה מכאנית, ו**איך היא עוזרת**.
3. מנתח **בטיחות שילוב** — אילו טכניקות "מתכפלות" ויוצרות over-correction, ואיך למנע.
4. מתעד **מסלול הרחבה** — מה אפשר להוסיף בעתיד למפגשים 6–8 כדי להגיע ל-best score.

**הסטאק הסופי למפגש 5 (כפי שסוכם — "option 2"):** A1-A7 (ניקוי מלא) + B1-B3 (יעילות) + C2 (Focal Loss עם משקלי מחלקות מובנים) + C4 (label smoothing ε=0.05) + D1-D4 (Split discipline) + E1+E2+E3 (EDA קל על מחלקות מיעוט בלבד, פי-2 augmentation). **לא** משלבים C1 בנפרד (subsumed by C2), C3 (sampler — שמור ל-fallback), E4 (synonym replacement — חלש בעברית), ו-F1-F8 (נדחים למפגשים 6–8).

---

## §2 · קבוצה A — ניקוי ושלמות נתונים (Foundation)

קבוצה זו אחראית על איכות הקלט. כל הטכניקות פה **בטוחות יחד** (אדיטיביות) ועושות אך טוב.

| # | טכניקה | מה היא עושה (מכאנית) | איך היא עוזרת | סיכון אם מוגזם |
|---|---|---|---|---|
| **A1** | **Exact deduplication** | Hash על כל זוג `(text, label)`; שמירת רק unique-keys | מונע נזילה בין train/test — לפעמים אותו ציוץ מופיע מתויג זהה גם ב-train וגם ב-test → F1 מנופח | אין; deterministic |
| **A2** | **Near-dedup (MinHash, Jaccard ≥ 0.85)** | חישוב MinHash signatures; חיפוש זוגות עם Jaccard score ≥ סף; הסרת כפילות לפי סף | SinaLab מכיל retweets ו-quote-tweets שלא נתפסים ב-A1 | סף נמוך מדי (0.6) מוחק parafrazים לגיטימיים |
| **A3** | **NFKC Unicode normalization** | מיפוי תווים לצורה הקנונית (לדוגמה: צורות הצגה ערביות → עברית סטנדרטית) | מקטין vocab fragmentation → ה-tokenizer מוצא את ה-WordPieces הנכונים יותר פעמים | בטוח לחלוטין; תוכנן לזה |
| **A4** | **הסרת ניקוד (nikud)** | regex סטריפ של תווים `֑`-`ׇ` (Hebrew diacritics) | בצ'אט/רשתות כמעט אף פעם לא יש ניקוד; נוכחות ב-train + העדרות ב-inference = train-test mismatch | אין לדומיין שלנו (ניקוד נדיר במדיה דיגיטלית) |
| **A5** | **ניקוי תווי כיוון בלתי-נראים** (U+200E LRM, U+200F RLM, U+202A-E) | regex סטריפ של direction-control characters | נוצרים בהעתק-הדבק; ה-tokenizer רואה אותם כ-junk → vocab pollution | אין |
| **A6** | **החלפת URL/Mention ב-placeholders** (`[URL]`, `[MENTION]`) | regex matching של URLs (`https?://...`) ו-mentions (`@[\w_]+`); החלפה לטוקן placeholder | מונע למידה זיהוי-ספציפי אך שומר על האות הסטרוקטורלי "הייתה כאן הזכרה" | מחיקה במקום החלפה = איבוד אות; חובה להחליף, לא למחוק |
| **A7** | **Outlier filter** (תווים < 3 או > 200 טוקנים) | סינון לפי אורך אחרי tokenization | מסיר שורות בודדות עם emoji או cookie-text שלא ניתן ללמוד מהן | יותר מדי אגרסיבי = הפסד דוגמאות קצרות אינפורמטיביות |

**שילוב A1-A7:** בטוח לחלוטין. כל הטכניקות אדיטיביות; הקלט אחרי A7 הוא תת-קבוצה ניקה של הקלט המקורי.

---

## §3 · קבוצה B — Sequencing & Efficiency

קבוצה זו לא משנה את התנהגות המודל — היא רק מזרזת את האימון/inference. **בטוחה לחלוטין** עם שאר הקבוצות.

| # | טכניקה | מה היא עושה | איך היא עוזרת | סיכון |
|---|---|---|---|---|
| **B1** | **Smart `max_length` מ-percentile** | מדידת p99.5 של אורך טוקן ב-train set; הגדרת `max_length = p99.5` | Attention הוא O(n²); חצי אורך = פי 4 מהיר. עבור SinaLab — p99.5 ≈ 64; הקטנת max_length מ-128 ל-96 = ~2× מהיר עם 0.5% truncation | חיתוך > 0.5% מהמקרים = פגיעה ב-F1 |
| **B2** | **Dynamic padding לפי batch** | במקום padding ל-`max_length` הגלובלי, padding לאורך ה-sample הארוך ביותר בכל batch | 20-30% מהיר יותר ל-epoch; אין הפסד מידע | אין |
| **B3** | **Pre-tokenize once → Arrow cache** | רוץ tokenizer פעם אחת על כל הדאטה, שמור כ-HF Dataset (Arrow format); השתמש כל epoch | מבטל overhead של ~10% מ-train time | Cache invalidation אם משנים את ה-tokenizer |
| **B4** | **Truncation strategy = "longest_first"** | בקיצוץ, שמירת תחילת הטקסט (לא מתיחה אחיד מ-2 הצדדים) | בציוצים, ה-punchline בדרך כלל בהתחלה; שומר רוב האות לתוויות הקשות | במקרים נדירים הסיגנל בסוף — נסיגה לאחר אבל לא דרמטית |

**שילוב B1-B4:** בטוח לחלוטין. אין תלות בין הטכניקות.

---

## §4 · קבוצה C — תיקון Class Imbalance

הקבוצה **הכי קריטית** למודל הצלחת — SinaLab הוא ~60% non_offensive, עם `violence` ו-`pornographic` נדירים מאוד (~1-2% כל אחד). **כאן מתחיל סיכון השילוב.**

| # | טכניקה | מה היא עושה | איך היא עוזרת | סיכון |
|---|---|---|---|---|
| **C1** | **Class-weighted cross-entropy** | הכפלת loss לכל דוגמא ב-`weight[class_id]`; המשקלים מ-`sklearn.compute_class_weight("balanced")` | אומר ל-optimizer "miss על דוגמת violence הוא פי X חמור" | משקלים אגרסיביים (>10×) → overfit למחלקות נדירות |
| **C2** | **Focal Loss (γ=2)** ([Lin 2017](https://arxiv.org/abs/1708.02002)) | `FL = -(1-p_t)^γ · log(p_t)` — down-weights confident-correct predictions | מחזיר את ה-gradient לדוגמאות **קשות**, ללא קשר לתדירות. עוזר ל-rare AND-hard | γ גבוה (>5) = "ratcheting" של gradient על דוגמאות לקויות-תיוג |
| **C3** | **Class-balanced sampler** | sample mini-batches כך שכל מחלקה מיוצגת שווה בכל batch | פתרון של ה-imbalance ב-input side (בניגוד ל-C1/C2 שעובדים ב-loss side) | בשילוב עם C1+C2 = triple correction; overprediction של מיעוטים ב-inference |
| **C4** | **Label smoothing (ε=0.05)** ([Szegedy 2016](https://arxiv.org/abs/1512.00567)) | החלפת `[0,0,1,0,0]` ב-`[0.0125, 0.0125, 0.95, 0.0125, 0.0125]` | מקטין confidence excess; משפר calibration (ECE קטן) | שילוב עם Focal Loss = compound softening; שמור ε=0.05 נמוך |

### §4.1 · האסטרטגיה: C2 עם משקלים מובנים + C4 ε=0.05

ב-Lin 2017, ה-Focal Loss מוגדר עם פרמטר `alpha` שאפשר להגדיר כ-`class_weights`. השילוב הזה הוא מנגנון **אחד** (לא שניים), שמטפל ב-rare-class detection וגם ב-hard-example focus.

```python
class FocalLoss(nn.Module):
    def __init__(self, alpha: torch.Tensor, gamma: float = 2.0, label_smoothing: float = 0.0):
        # alpha: per-class weight tensor of shape (num_classes,)
        super().__init__()
        self.alpha = alpha
        self.gamma = gamma
        self.label_smoothing = label_smoothing
    
    def forward(self, logits, targets):
        ce = F.cross_entropy(
            logits, targets,
            weight=self.alpha,
            label_smoothing=self.label_smoothing,
            reduction="none",
        )
        pt = torch.exp(-ce)  # softmax probability of the true class
        focal = (1 - pt) ** self.gamma * ce
        return focal.mean()
```

**זה ה-loss המומלץ למפגש 5.**

---

## §5 · קבוצה D — Splitting & Evaluation Discipline

| # | טכניקה | מה היא עושה | איך היא עוזרת | סיכון |
|---|---|---|---|---|
| **D1** | **Stratified split** | `sklearn.train_test_split(stratify=labels)` | פיצול עם שמירת היחס הקבוע של כל מחלקה בכל split | אין |
| **D2** | **Cross-split near-dedup check** | אחרי הפיצול, רן MinHash A2 בין splits; הצדקת כשל אם נמצא זוג near-dup | מבטל את ה-F1-inflation bug הנפוץ ביותר | אין |
| **D3** | **Style-stratified holdout (1040 משפטים)** | שמירת כל הדאטה של `data/ocr_validation/sentences.jsonl` ל-evaluation בלבד; דיווח F1 לפי style A/B/C/D | מספק טבלת robustness — F1 על clear / code-switching / poor-spelling / children-mistakes בנפרד | אין; bonus pure |
| **D4** | **Holding test split untouched** | רק test set אחד ב-Meeting 5; אסור לפתוח עד המדידה הסופית | מונע overfit סמוי דרך hyperparameter tuning | אין |

**שילוב D1-D4:** בטוח לחלוטין. discipline בלבד.

---

## §6 · קבוצה E — Augmentation (קל, על מיעוטים בלבד)

הסיכום: רק על מחלקות מיעוט (`violence`, `pornographic`, `hate`), בקצב פי 2 maximum, ורק 3 טכניקות EDA.

| # | טכניקה | מה היא עושה | איך היא עוזרת | סיכון |
|---|---|---|---|---|
| **E1** | **EDA — Random Insertion** | הכנס מילה אקראית (מה-vocab של train) במיקום אקראי | הוספת perturbations קלים שהמודל צריך להיות invariant אליהם | באנגלית — synonyms טובים יותר; בעברית — שימוש ב-vocab של train הוא הבטוח ביותר |
| **E2** | **EDA — Random Swap** | החלפת שתי מילים אקראיות במיקומם | בודק order-invariance של signals bag-of-features | החלפה מרובה הורסת דקדוק עברי |
| **E3** | **EDA — Random Deletion** | מחיקת כל מילה בהסתברות p (לדוגמה 0.1) | הכשרה ל-robustness לחוסר מילים | מחיקה מרובה (>20%) הורסת את ה-label signal |
| **E4** | **EDA — Synonym Replacement** ⚠️ | החלפת מילה לא-stopword ב-synonym | באנגלית — ה-EDA החזק ביותר; בעברית — WordNet-Hebrew דל | **לדלג בעברית** — סיכון של mis-augmentation גובר על תועלת |
| **E5** | **Augment רק מחלקות מיעוט** | augment פי 2 רק את ה-examples של violence/pornographic/hate | מטפל ב-imbalance מבלי להכפיל זמן אימון | אין — היפך הסיכון |
| **E6** | **Augment רק על train split** | אסור על validation או test | evaluation הוגן | אין |

**הגדרה:** "פי 2" משמע — אם המקור הוא 100 דוגמאות של `violence`, אז train יקבל 200 (המקור + 100 augmented variants).

---

## §7 · קבוצה F — נדחה למפגשים 6–8

לרשימה (לא לבצוע במפגש 5):

| # | טכניקה | סיבת דחייה |
|---|---|---|
| F1 | Back-translation (עברית → אנגלית → עברית) | preprocessing כבד; עבודה למפגש 6 |
| F2 | LLM paraphrase augmentation (Claude/GPT-4o) | API cost; דורש human spot-check; מפגש 6 |
| F3 | Synthetic conversational data | האסטרטגיה הראשית של `bullying_data_he.md`; **מפורש למפגש 6** |
| F4 | DAPT (continue MLM על עברית פוגענית) | דורש corpus לא-מתויג שאין לנו במכלל |
| F5 | Confident Learning ([Northcutt 2021](https://arxiv.org/abs/2103.14749)) | שימושי אם F1 נכשל; one-time 30-דק' |
| F6 | Mixup / Manifold Mixup | קשה לדבג ל-BERT; דחייה ל-ablation אם צריך |
| F7 | Curriculum learning | סדר easy→hard; שיפור שולי |
| F8 | Adversarial filtering | זריקת examples טריוויאליים; שיפור שולי |

---

## §8 · ניתוח בטיחות שילוב — האם הטכניקות יחד יכולות לפגוע?

### סיכון #1 — Over-correction של class imbalance (C1 + C2 + C3 בשילוב)

אם נשתמש בשלושת המנגנונים יחד (class-weighted CE + Focal Loss + class-balanced sampler), המודל יוכל לעבור מ-overrepresentation של non_offensive ל-**overprediction של מחלקות מיעוט** ב-inference. תוצאה: precision נמוך על המחלקות הנדירות → אזעקות שווא נוספות.

**מיגון (במסלול המומלץ):**
- שימוש ב-C2 בלבד עם משקלים מובנים (זהו mechanism אחד, לא שניים)
- **דילוג על C3** במפגש 5
- אם per-class recall של `violence` אחרי הריצה הראשונה < 0.5 → **רק אז** הפעלת C3 כניסוי נוסף

### סיכון #2 — Compounding softening (C2 + C4 עם ε גבוה)

Focal Loss כבר ממתן gradient על confident-correct predictions. Label smoothing גם מרכך targets גלובלית. עם ε גבוה (≥ 0.1), ה-confidence של הרשת מרוסק כפול — calibration נראה טוב אך הסיגנל הדיסקרימינטיבי נחלש.

**מיגון:**
- **label smoothing ε=0.05** (לא 0.1) כשמשלבים עם Focal Loss
- מסמך הארכיטקטורה הציע ε=0.1; אנחנו מורידים ל-0.05 לסביבה ה-loss-משולב

### סיכון #3 — Augmentation distribution shift (E1-E3 מוגזם)

אם נעשה augment למיעוטים פי 5 בלי לטפל ברוב, התפיסה של המודל של ההתפלגות המשותפת תהיה מוטעית. הוא יחשוב שהעולם הוא 50% מיעוט-מחלקה כשבפועל זה 5%. ההתפלגות של ה-output תהיה miscalibrated → סף ה-triage יצטרך re-tuning.

**מיגון:**
- הגבלת augmentation למיעוטים ל-**פי 2** מהמקורי (כפי שנמצא בהמלצה)
- re-fit של calibrator (`training/calibrate.py`) על validation split שלא-augmented — כך ה-calibration משקף את ההתפלגות האמיתית

### סיכון #4 — Lossy preprocessing (A6 מוגזם)

אם נמחק (במקום להחליף) URLs/mentions, ה-context הרלוונטי לתווית הולך לאיבוד. "@friend you're an idiot" מאבד את ה-context החברתי (banter ידידותי vs. attack).

**מיגון (במסלול המומלץ):**
- A6 **מחליף** ב-`[URL]` / `[MENTION]` placeholder tokens — שומר את האות הסטרוקטורלי

### זוגות בטוחים מוכחים (משולבים בפרודקשן ב-Google/Meta/etc.)

- A1+A2+A3+A4+A5+A7 (החבילה הניקוי — אדיטיבי, ללא סיכון)
- B1+B2+B3 (החבילה היעילות — אף אחד לא משנה את התנהגות המודל)
- D1+D2+D3+D4 (החבילה ה-discipline — אבן יסוד של evaluation הוגן)
- C2 (Focal עם משקלים מובנים) + C4 (label smoothing ε=0.05)
- E1+E2+E3 capped at 2× on minorities only

---

## §9 · Configuration & הרחבה עתידית

**הצינור יהיה parameterized — כל בחירה היא knob:**

```python
from dataclasses import dataclass

@dataclass
class DataPrepConfig:
    # A. Cleaning
    dedup_jaccard_threshold: float = 0.85
    drop_min_tokens: int = 3
    drop_max_tokens: int = 200
    strip_nikud: bool = True
    url_replacement: str = "[URL]"        # set "" to delete
    mention_replacement: str = "[MENTION]"

    # B. Sequencing
    max_length: int = 96                  # set from p99.5 of training set

    # C. Class balance
    use_focal_loss: bool = True
    focal_gamma: float = 2.0
    use_class_weights_in_focal: bool = True
    use_balanced_sampler: bool = False    # turn ON only if recall_violence < 0.5
    label_smoothing_epsilon: float = 0.05

    # D. Splits
    test_size: float = 0.10
    val_size: float = 0.10
    seed: int = 42
    holdout_ocr_validation: bool = True   # 1040 sentences for stylistic eval

    # E. Augmentation
    augment_minorities: bool = True
    minority_augment_factor: int = 2      # max 5; >2 risks distribution shift
    eda_techniques: tuple = ("random_insert", "random_swap", "random_delete")
    eda_synonym_replacement: bool = False # E4 — keep OFF for Hebrew
```

### מסלול ההרחבה לצורך best score

| מפגש | מה להוסיף | למה |
|---|---|---|
| **מפגש 5** | הסטאק הנוכחי; שער ב-F1 ≥ 0.78 | נעילת ה-baseline |
| **מפגש 6** | + Synthetic conversational data (F3); + revisit augmentation rate; + Confident Learning אם F1 < 0.80 | הוספת ממד שיחתי |
| **מפגש 7** | + DAPT (F4) על corpus עברי-פוגעני מצטבר | דחיפה דומיין ל-1-2 pp אחרונים |
| **מפגש 8** | + Final hyperparameter ablation; + דיווח כל הקומבינציות בתזה | ראייה empirically defendable |

**הכל ניתן להחלפה דרך הקובץ `data_prep_config.yaml` — אין צורך לשנות קוד.**

---

## §10 · אינטגרציה עם מסמך הארכיטקטורה

מסמך [`dictabert_classifier_architecture.md`](dictabert_classifier_architecture.md) §9 מגדיר את ה-**data contract** — מה הקוד של ה-data prep חייב להפיק. המסמך הנוכחי מסביר **למה** המבנה הוא כזה ו**איך** להגיע אליו.

הטבלה ההצלבה:

| §9 בארכיטקטורה דורש | המסמך הנוכחי מנמק | הטכניקה הספציפית |
|---|---|---|
| JSONL `{"text": str, "label": str}` | פורמט סטנדרטי לסיווג; HF `Trainer` קורא ישירות | — |
| `class_weights.json` | תיקון imbalance ב-loss | C1 (משולב לתוך C2 כ-`alpha`) |
| max_length=128 baseline | smart from p99.5 | B1 |
| holdout style-1040 | robustness eval | D3 |
| no-leakage validator | cross-split discipline | A1+A2+D2 |
| NFKC + diacritic-strip | Hebrew normalization | A3+A4+A5 |
| canonical `non_offensive` | label vocabulary alignment | (resolved G-02 in review.md) |

---

## §11 · סיכום למפגש 5

**המסלול המאושר:**
1. ✅ A1+A2+A3+A4+A5+A6+A7 (ניקוי + נורמליזציה מלא)
2. ✅ B1 (max_length=96 מ-p99.5) + B2 (dynamic padding) + B3 (Arrow cache)
3. ✅ C2 (Focal Loss γ=2 עם משקלי מחלקות) + C4 (label smoothing ε=0.05)
4. ✅ D1+D2+D3+D4 (full discipline)
5. ✅ E1+E2+E3 רק על מחלקות מיעוט פי 2

**הימנעות:**
- ❌ C3 (balanced sampler) — שמור ל-fallback אם recall נמוך
- ❌ C1 בנפרד — subsumed by C2
- ❌ E4 (synonym replacement) — חלש בעברית
- ❌ F1-F8 — נדחים למפגשים 6-8

**אבן השומר של המסלול הזה:** F1 ≥ 0.78 על SinaLab test split. אם נכשלים — נסיגה ל-mitigations: הפעלת C3, הגדלת focal γ, הוספת F5 (Confident Learning).

</div>
