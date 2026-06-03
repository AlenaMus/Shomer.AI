**פרויקט גמר**
**קורס מומחי AI**
**Shomer.AI**
**מערכת AI רב-מודאלית לזיהוי בריונות מקוונת וסיכון נפשי בקרב ילדים דוברי עברית**

*הצעת פרויקט ושאלת מחקר*

מוגש למרצה: ד"ר יורם סגל
מסגרת: 10 מפגשים – פרויקט גמר מקצועי

# **תוכן העניינים**
**1.  **תקציר מנהלים
**2.  **הצגת הבעיה והערך העסקי
**3.  **סקירת שוק – אפליקציות קיימות
**4.  **ניתוח חולשות וייחוד הפרויקט (USP)
**5.  **שאלת מחקר ושאלות משנה
**6.  **סקירת ספרות אקדמית
**7.  **מאגרי נתונים (Datasets) לאימון המודל
**8.  **יצירת נתונים סינתטיים (Synthetic Data)
**9.  **כלים, ספריות וטכנולוגיות
**10.  **ארכיטקטורת סוכני AI (Agents)
**11.  **מסמך דרישות מוצר (PRD)
**12.  **תכנית 10 מפגשים ומדדי הצלחה
**13.  **סיכום והצדקה אקדמית
**14.  **מקורות ורפרנסים

# **1. תקציר מנהלים**
פרויקט Shomer.AI מציע פתרון AI רב-מודאלי לזיהוי בריונות מקוונת, אלימות וסיכון נפשי בתקשורת הדיגיטלית של ילדים ובני נוער דוברי עברית. הפרויקט נשען על ארכיטקטורת סוכנים (Multi-Agent Architecture) המשלבת מודל שפה בעברית (DictaBERT) עם סוכן הקשר (Context Agent) מבוסס LLM, ומספק להורים התראות איכותיות, מבוססות הקשר ומחושבות-עלות.
הפרויקט נבנה בהתאמה מלאה לדרישות הקורס: שאלת מחקר מדידה עם Baseline ברור, ליבת AI מהותית (לא קוסמטית), שימוש בסוכני AI הן בתהליך הפיתוח (Path A) והן כרכיב פעיל במוצר הסופי (Path B), מאגר GitHub מתועד, ספר פרומפטים, ניתוח עלויות טוקנים, ותכנית עסקית מבוססת מתחרים אמיתיים.
### **ערך עסקי ייחודי (USP)**
- פתרון עברית-ראשון: המתחרים העיקריים (Bark, Qustodio, Canopy) עובדים באנגלית בלבד או באופן חלקי בעברית.
- הבנת הקשר רב-מודאלית: סוכן ייעודי שמבדיל בין משחק/בדיחה לבין איום אמיתי – פתרון לבעיית ה-False Positives של המתחרים.
- ארכיטקטורה היברידית חסכונית: classifier זול ב-frontline, LLM יקר רק כשנדרשת הכרעה.
- שקיפות והסבר (Explainability): כל התראה מלווה בהסבר ובציטוט, להבדיל מ-"קופסה שחורה" של המתחרים.

# **2. הצגת הבעיה והערך העסקי**
## **2.1 כאב המשתמש**
בשנים האחרונות עלייה דרמטית בחשיפת ילדים ובני נוער לסיכונים דיגיטליים: בריונות מקוונת, איומים, תכנים מיניים לא רצויים, גרומינג ושיח אובדני. סקרים מצביעים על כך שכ-35% מהילדים מדווחים על איום מקוון כלשהו, וחלק ניכר מהם אינם משתפים את ההורים. ההורים, מצידם, חסרים כלים אמיתיים לזהות מצוקה בזמן.
הכלים הקיימים בשוק מבוססים בעיקרם על מילים מפתח באנגלית, אינם מבינים הקשר תרבותי-לשוני ישראלי, וגורמים להצפת התראות (Alert Fatigue) המובילה לכך שהורים מבטלים את האפליקציה תוך ימים.
## **2.2 קהל היעד**
- **הורים לילדים בגילי 8-17 **שמחזיקים סמארטפון – בישראל כ-1.5 מיליון בתי אב.
- **מוסדות חינוך ויועצים חינוכיים **המעוניינים בכלי גילוי מוקדם לאיתור מצוקה.
- **ארגונים העוסקים בבטיחות ילדים **כגון "105" המטה הלאומי להגנה על ילדים.
## **2.3 גודל שוק (TAM/SAM/SOM)**
- **TAM: **שוק ה-Parental Control העולמי נאמד ב-1.6 מיליארד דולר (2025), צמיחה שנתית של 9.4%.
- **SAM: **שוק דוברי עברית – כ-1.5 מיליון בתי אב עם ילדים בגיל הרלוונטי בישראל.
- **SOM: **יעד שנה ראשונה – 5,000 משתמשים פעילים, ב-ARPU של 40 ש"ח לחודש.

# **3. סקירת שוק – אפליקציות קיימות**
שוק ה-Parental Control רווי בשחקנים, אך רובם פותרים את הבעיה באופן חלקי בלבד. ניתוח מעמיק של המתחרים העיקריים מגלה פערים משמעותיים שמאפשרים כניסה ייחודית לפרויקט זה.
## **3.1 מתחרים בינלאומיים**
### **Bark (ארה"ב) – מובילת השוק**
- **טכנולוגיה: **AI לסריקת טקסט, תמונות, וידאו ואודיו ב-30+ פלטפורמות (אינסטגרם, סנאפצ'ט, דיסקורד, וואטסאפ).
- **יתרונות: **כיסוי רחב מאוד (29 קטגוריות סיכון), דיוק 97% במחקרים עצמאיים, חיסכון בפרטיות (סיכומים ולא הודעות מלאות).
- **חסרונות: **אנגלית בלבד – לא מזהה סיכונים בעברית. False positives ברגישות גבוהה (זוהה איום באימייל על תרומה לקורבנות מלחמה). דירוג 2.9/5 ב-Trustpilot. תמיכה דלה ב-iOS עקב מגבלות אפל.
- **תמחור: **~$100 לשנה.
### **Qustodio (ספרד) – ניטור פעיל**
- **טכנולוגיה: **פילטור אתרים, ניהול זמן מסך, מיקום ו-geofencing, AI-driven alerts.
- **יתרונות: **כיסוי קרוס-פלטפורמה מצוין (Android, iOS, Windows, Mac), דשבורד מקיף, רב-לשוני בסיסי.
- **חסרונות: **AI שטחי יחסית – מבוסס keywords ופחות הקשר. אינו מזהה ניואנסים תרבותיים-ישראליים.
### **Canopy (ארה"ב) – AI לתמונות**
- **טכנולוגיה: **ראייה ממוחשבת בזמן אמת, חסימת תוכן מיני לפני טעינה.
- **יתרונות: **מתקדם בתמונות וסרטונים, פחות פולשני.
- **חסרונות: **ממוקד עירום בלבד, לא בבריונות. אינו פותר את בעיית הטקסט והשיח.
### **Aura, Net Nanny, FamilyKeeper – שחקני המשנה**
מתחרים נוספים עם פילטור אתרים מתקדם ו-AI סטנדרטי. ללא יתרון טכנולוגי משמעותי בזיהוי שיח רגשי או בריונות בהקשר תרבותי.
## **3.2 מתחרים ישראליים**
### **Keepers Child Safety (ירושלים)**
- **טכנולוגיה: **אלגוריתם NLP מבוסס IBM Watson לניתוח מצב רגשי של שיחות.
- **יתרונות: **פעילים גם באירופה, מבינים את האתגר של רב-לשוניות, מתריעים תוך 20 דקות, מודעים לפרטיות הילד.
- **חסרונות: **לפי הצהרת ה-CEO עצמו, סלנג מקומי הוא אתגר מרכזי שלא נפתר. לא מנצלים LLMs מודרניים.
### **Sentry Parental Control (רעננה)**
- **פעילות: **ניטור הודעות בפייסבוק, וואטסאפ, אינסטגרם, SMS וצילומים.
- **יתרונות: **הצלחה מבצעית מתועדת (איתור מקרה הטרדה מינית מצד מורה בארה"ב, הוביל למעצר).
- **חסרונות: **טכנולוגיה ותיקה יחסית, לא מבוססת LLMs מודרניים, גישה פולשנית.
### **Bosco (ישראל)**
- **טכנולוגיה ייחודית: **ניתוח דפוסי התנהגות (לא תוכן) – שינוי במצב רוח, ירידה במספר החברים.
- **יתרונות: **פתרון מגן-פרטיות, חכם פסיכולוגית.
- **חסרונות: **אינדיקציה איטית – מאתר תסמינים אחרי הפגיעה, לא לפניה.

# **4. ניתוח חולשות וייחוד הפרויקט (USP)**
הניתוח לעיל מגלה שלוש חולשות מבניות בכל המתחרים, ושלוש הן ההזדמנויות שבהן הפרויקט מתמקד:

| **חולשה בשוק** | **איך זה מתבטא במתחרים** | **פתרון Shomer.AI** |
| --- | --- | --- |
| **ללא תמיכה אמיתית בעברית** | Bark – אנגלית בלבד. Qustodio – תמיכה בסיסית. Keepers – מודה שסלנג ישראלי בעייתי. | DictaBERT fine-tuned + Synthetic Data של סלנג נוער עברי |
| **False Positives גבוהים** | Bark – זוהה איום באימייל על תרומה. Net Nanny – מסמן ביטויים תמימים. | Context Agent (LLM) שעובר על כל התראה ומאמת לפני שליחה להורה |
| **חוסר שקיפות / Black Box** | המוצרים מתריעים אך לא מסבירים – הורים לא יודעים למה. | Explainable AI: כל התראה כוללת ציטוט, סוג סיכון ורמת ביטחון |
| **עלות גבוהה למשתמש** | $100 לשנה ב-Bark. עלויות API ניכרות במודלים מתקדמים. | ארכיטקטורה היברידית – classifier זול בשלב ראשון, LLM רק על מקרי גבול |

# **5. שאלת מחקר ושאלות משנה**
## **5.1 שאלת מחקר ראשית**
**האם ארכיטקטורת AI היברידית, המשלבת מסווג קל מבוסס DictaBERT עם סוכן הקשר (Context Agent) מבוסס LLM ושכבת Augmentation סינתטית, משפרת באופן מובהק את ערך ה-F1 בזיהוי בריונות מקוונת ושיח רגשי בעברית מודרנית, בהשוואה ל-Baseline של מסווג DictaBERT "vanilla", תוך שמירה על Latency נמוך מ-1.5 שניות ועלות טוקן ממוצעת מתחת ל-$0.005 לאינטראקציה?**
## **5.2 שאלות משנה (Sub-Questions)**
- Q1: מהי תרומת ה-Synthetic Data Augmentation (מבוסס LLM) על מאגר OffensiveHebrew לדיוק זיהוי סלנג עכשווי?
- Q2: באיזו מידה Context Agent מבוסס GPT-4o-mini / Claude Haiku מצליח לסנן False Positives שזוהו בשלב הראשון, ובאיזו עלות?
- Q3: כיצד ביצועי המערכת בעברית משתווים למערכת מקבילה באנגלית (Baseline בינלאומי – BERT על מאגר Davidson Hate Speech)?
- Q4: מהו ה-trade-off האופטימלי בין דיוק (F1), עלות ($) וזמן תגובה (ms) עבור 3 רמות סיכון (אדום/צהוב/ירוק)?
## **5.3 השערות מחקר**
- **H1: **הוספת שכבת Synthetic Data תעלה את ה-F1 ב-7-12 נקודות אחוז על דאטה של סלנג עכשווי.
- **H2: **Context Agent יפחית False Positives ב-40%+ בהשוואה ל-Baseline, תוך עליית עלות של פחות מ-50%.
- **H3: **המערכת ההיברידית תשיג F1 מעל 0.85 על מאגר Gold Set שיוכן ידנית בעברית עכשווית.

# **6. סקירת ספרות אקדמית**
הסקירה מתבססת על שלושה תחומי מחקר מרכזיים: זיהוי בריונות מקוונת (Cyberbullying Detection), מודלי שפה לעברית, ויצירת נתונים סינתטיים באמצעות LLMs.
## **6.1 מאמרי דגל (Anchor Papers)**
### **[1] DictaBERT: A State-of-the-Art BERT Suite for Modern Hebrew**
Shmidman et al. (2023). arXiv:2308.16687. מתאר מודל BERT מתקדם לעברית מודרנית, המשמש כבסיס הטכני של הפרויקט. הוא משיג ביצועים SOTA ברוב ה-benchmarks ומגיע עם גרסאות fine-tuned לסגמנטציה, תיוג מורפולוגי ו-QA.
### **[2] AlephBERT: A Hebrew Large Pre-Trained Language Model**
Seker et al. (2021). arXiv:2104.04052. מודל בסיס נוסף לעברית, גדול וטוב יותר ממודלים קודמים. משמש כ-Baseline להשוואה ולוודא שבחירת המודל מבוססת על מדידה.
### **[3] CyberBERT: BERT for Cyberbullying Identification**
Paul & Saha (2022). מציג שימוש ב-BERT לזיהוי בריונות. הראה ש-BERT עוקף שיטות מסורתיות (SVM, Naive Bayes, BiLSTM) באופן עקבי. בסיס מתודולוגי להחלטה לבחור ב-DictaBERT.
### **[4] Enhanced Arabic-language Cyberbullying Detection**
Aljohani & Yafooz (2025). arXiv:2510.02232. השיגו 97-98% דיוק על מאגר של 10,662 ציוצים בערבית עם BERT+BiLSTM. הוכחת היתכנות לשפה מורפולוגית עשירה (דומה לעברית), כולל פתרון בעיית imbalance עם kappa.
### **[5] LLM-based Semantic Augmentation for Harmful Content Detection**
Lippmann et al. (2025). arXiv:2504.15548. מראה ש-LLM-based augmentation מגיע לביצועים זהים ל-human annotation בעלות נמוכה דרמטית. בסיס מתודולוגי לשכבת ה-Synthetic Data בפרויקט.
### **[6] Cyberbullying Detection in Hinglish Text Using MURIL**
Kumar et al. (2025). arXiv:2506.16066. Benchmark על 6 datasets בקוד מעורב (Hinglish), עם דיוקים של 75-94%. רלוונטי במיוחד לאתגר העברית הישראלית המעורבת באנגלית.
### **[7] Cyber-aggression, Cyberbullying, and Cyber-grooming – Survey**
Mladenovic et al. (2021). ACM Computing Surveys 54(1). סקירה מקיפה של התחום, מגדירה טקסונומיה של סיכונים – שימושית להגדרת קטגוריות הסיכון של Shomer.AI.
### **[8] On LLMs-Driven Synthetic Data Generation – Survey**
Long et al. (2024). ACL Findings. סקירה של שיטות augmentation מבוססות LLM. מספק טקסונומיה של שיטות (Zero-Shot, Few-Shot, Iterative) ומדדים להערכת איכות הנתונים הסינתטיים.
## **6.2 ה-Gap שהפרויקט סוגר**
הספרות הקיימת חזקה בכל אחד מהתחומים בנפרד אך אינה משלבת ביניהם בהקשר העברי:
- מודלי עברית קיימים (DictaBERT, AlephBERT) אינם fine-tuned לזיהוי בריונות.
- מאגר OffensiveHebrew הוא היחיד בעברית אך מוגבל ל-15K ציוצים, ללא סלנג נוער עכשווי.
- אין בספרות מחקר עברי שמשלב BERT + Context Agent + Synthetic Augmentation לדומיין הזה.

# **7. מאגרי נתונים (Datasets) לאימון המודל**
בחירת הדאטה היא ההחלטה המתודולוגית הקריטית בפרויקט. הגישה הנבחרת היא Layered Data Strategy: שכבת ליבה בעברית, שכבת Transfer Learning ממאגרים גדולים באנגלית, ושכבת Augmentation סינתטית לסגירת פערי סלנג.
## **7.1 מאגרים בעברית**

| **מאגר** | **היקף ומקור** | **שימוש בפרויקט** | **נגישות** |
| --- | --- | --- | --- |
| **OffensiveHebrew** | 15,881 ציוצים מתויגים ידנית (פוגעני / לא-פוגעני) | מאגר אימון ליבה – Fine-tuning ראשי | GitHub + HuggingFace, חינמי |
| **HeDC4** | Common Crawl עברי נקי, מיליארדי טוקנים | Domain adaptation למודל לפני fine-tuning | HuggingFace (HeNLP/HeDC4) |
| **Knesset Corpus** | דיוני הכנסת, מאומת לשפה רשמית | ניתוח השוואתי – שפה רשמית מול דיבורית | חינמי, אקדמי |
| **Gold Set פנימי** | 500-1,000 הודעות שיתויגו ידנית במסגרת הפרויקט | Test Set בלעדי – מדידת ביצועים אמיתית | ייווצר במסגרת הפרויקט |

## **7.2 מאגרים באנגלית – Transfer Learning**

| **מאגר** | **היקף** | **שימוש** | **מקור** |
| --- | --- | --- | --- |
| **Davidson Hate Speech** | ~25K ציוצים, 3 קטגוריות | Cross-lingual transfer, Baseline אנגלי | HuggingFace |
| **HateXplain** | ~20K פוסטים עם הסברים אנושיים | אימון על rationales (Explainability) | HuggingFace: Hate-speech-CNERG |
| **Jigsaw Toxic Comments** | ~160K הערות Wikipedia, 6 קטגוריות | Pre-training להבנת רעילות | Kaggle, חינמי |
| **Formspring CB** | מאגר קלאסי לבריונות | Benchmark היסטורי | נגיש חינם |

## **7.3 מאגרי תמונה ותוכן ויזואלי**
- **Marqo/nsfw-image-detection-384: **מודל מוכן מאומן על 220K תמונות, דיוק 98.56%. שימוש כ-component מובנה ללא אימון עצמי.
- **NudeNet: **ספריית Python פתוחה, סיווג עירום עם bounding boxes.
- **RWF-2000: **2,000+ סרטוני אלימות מהעולם האמיתי. Benchmark 86.75%.
- **Hockey Fight / Movies Fight: **מאגרי וידאו קלאסיים לזיהוי אלימות פיזית.
## **7.4 הגדרת מאגרים אסור להשתמש בהם**
שורת קווים אדומים מתודולוגיים ומשפטיים שהפרויקט מקפיד עליהם:
- הודעות מטלפונים אמיתיים של ילדים – פגיעה בפרטיות וחוקי הגנת הפרטיות.
- Scraping של וואטסאפ/אינסטגרם פרטי – הפרת ToS וחוק האזנת סתר.
- מאגרי CSAM (תכן מיני בילדים) – פלילי גם להחזקה למחקר. הטיפול בקטגוריה זו ייעשה אך ורק דרך מודלים מוכנים מראש.

# **8. יצירת נתונים סינתטיים (Synthetic Data Generation)**
הפער המרכזי במאגרים הקיימים הוא בסלנג נוער ישראלי עכשווי – ביטויים, אמוג'ים, קודי דיבור, ערבוב עברית-אנגלית-ערבית. נושא זה הוא לב ה-USP של הפרויקט ויטופל באמצעות שכבת Synthetic Data Augmentation.
## **8.1 שיטות יצירת נתונים סינתטיים**
### **שיטה 1: Zero-Shot Generation**
פרומפט ישיר ל-LLM (GPT-4, Claude, Gemini) ליצירת דוגמאות סינתטיות לפי קטגוריה. דוגמה לפרומפט:
*"צור 20 הודעות בעברית של נוער בן 14, סגנון WhatsApp, המבטאות בריונות חברתית עדינה (exclusion + ridicule). כלול אמוג'ים, סלנג עכשווי וקיצורים. הימנע מקללות בוטות."*
### **שיטה 2: Few-Shot with Seeding**
הספקת 3-5 דוגמאות אמיתיות מ-OffensiveHebrew ובקשה ליצור וריאציות במאות. נוסחה מוכחת ב-Synthesis Step by Step (Wang et al., 2023).
### **שיטה 3: Adversarial Generation עם סוכן**
שימוש בסוכן AI שמייצר דוגמאות גבול (edge cases) – הודעות שצריכות לבלבל את ה-classifier. למשל: "אני אהרוג אותך" במשחק לעומת איום אמיתי. שיטה זו נקראת LLM as a Source of Targeted Synthetic Data (Lippmann et al., 2024).
### **שיטה 4: Back-Translation**
תרגום של דוגמאות מאנגלית (Davidson, HateXplain) לעברית באמצעות LLM, ואז התאמה תרבותית. זול ויעיל אך נתון לבעיות איכות.
## **8.2 שמירה על איכות הדאטה הסינתטי**
- **Diversity Filtering: **סינון דוגמאות דומות (cosine similarity > 0.85) למניעת homogenization.
- **Human Review Sample: **בדיקה ידנית של 10% מהדוגמאות הסינתטיות לאימות איכות.
- **Adversarial Validation: **אימון classifier להבחין בין דאטה אמיתי לסינתטי – אם הוא מצליח, הדאטה לא איכותי.
- **Weighted Loss: **מתן משקל נמוך יותר לדוגמאות סינתטיות במהלך האימון.
## **8.3 תיעוד בספר הפרומפטים**
כל פעולת יצירת נתונים סינתטיים תתועד ב-Prompt Book לפי דרישת הקורס: מטרה, הקשר, פרומפט מדויק, מודל, פלט בפועל, ערכת איכות, החלטה (לקבל/לדחות) והפקת לקחים.

# **9. כלים, ספריות וטכנולוגיות**
## **9.1 מודלי שפה ובסיס AI**

| **רכיב** | **טכנולוגיה נבחרת** | **נימוק הבחירה** |
| --- | --- | --- |
| **Base Model (עברית)** | DictaBERT (dicta-il/dictabert) | SOTA לעברית מודרנית, נגיש דרך HuggingFace, מתאים ל-fine-tuning |
| **Baseline להשוואה** | AlephBERT, HeRo | מאפשרים השוואה מובהקת – החלטה מבוססת מדידה ולא תחושה |
| **LLM לסוכן הקשר** | Claude 3.5 Haiku / GPT-4o-mini / Gemini Flash | מודלים מהירים וזולים יחסית, איכותיים מספיק להחלטות הקשר |
| **LLM ליצירת Synthetic Data** | Claude 3.5 Sonnet / GPT-4o | איכות גבוהה לעברית, יציבים בהבנת תרבות מקומית |
| **Image Moderation** | Marqo NSFW Detection + NudeNet | מודלים מוכנים, ללא אימון עצמי – מסיר סיכון משפטי |
| **Embeddings ל-RAG** | multilingual-e5-large | תמיכה רב-לשונית כולל עברית, פתוח וחינמי |

## **9.2 מסגרת פיתוח (Stack)**
### **Backend וליבת AI**
- **Python 3.11 **– שפת בסיס לכל הפרויקט.
- **PyTorch + Transformers (HuggingFace) **– פריימוורק לעבודה עם מודלי שפה.
- **LangChain / LangGraph **– אורקסטרציית סוכנים, ניהול state ו-tool calls.
- **FastAPI **– שכבת API חיצונית – שער כניסה יחיד לפי דרישת SDK של הקורס.
- **Pydantic **– validation של schemas, פלטי מודל.
### **שמירה ו-RAG**
- **ChromaDB / Qdrant **– וקטור-DB למאגר דפוסי בריונות, סלנג ופרוטוקולים.
- **SQLite **– ניהול אירועים, התראות ולוגים.
### **בדיקות ואיכות קוד**
- **pytest **– unit + integration tests.
- **Ruff **– linter ו-formatter.
- **MLflow **– מעקב אחר ניסויים, מטריקות ועלויות טוקנים.
### **Frontend / Demo**
- **Streamlit / Gradio **– דמו מהיר להגנה ולמצגת.
- **React + Tailwind **(אופציונלי) – לדמו הורה-ילד עשיר יותר.
### **DevOps ותיעוד**
- **GitHub + GitHub Actions **– ניהול גרסאות, CI.
- **Docker **– containerization לכל הפרויקט.
- **MkDocs **– תיעוד API ו-Prompt Book.

# **10. ארכיטקטורת סוכני AI (Agents)**
בהתאם לחוק הזהב של הקורס – סוכני AI מהווים חלק מהותי הן בתהליך הפיתוח (Path A) והן במוצר הסופי (Path B). אינם קישוט, אלא רכיב פונקציונלי עם תפקיד מוגדר, גבולות אחריות ומדדי הצלחה.
## **10.1 סוכנים כחלק מהמוצר (Path B)**
### **סוכן 1: Triage Agent (מסווג ראשוני)**
- **תפקיד: **סיווג מהיר וזול של כל הודעה ל-3 רמות סיכון – ירוק (תקין), צהוב (פוטנציאל), אדום (סיכון).
- **טכנולוגיה: **DictaBERT fine-tuned + classifier head.
- **קלט: **טקסט הודעה + מטא-דאטה (זמן, פלטפורמה, גיל הילד).
- **פלט: **{level: red/yellow/green, confidence: 0-1, categories: [bullying, sexual, violence, self-harm]}
- **מדדים: **F1 > 0.85 על Gold Set, Latency < 200ms, עלות $0 (local model).
### **סוכן 2: Context Agent (סוכן הקשר)**
- **תפקיד: **מקבל הודעות צהוב/אדום ובוחן אותן בהקשר – שיחה קודמת, פלטפורמה, יחסי הצדדים. מאמת את ההתראה ומפחית False Positives.
- **טכנולוגיה: **Claude Haiku / GPT-4o-mini עם פרומפט מובנה.
- **כלים זמינים (Tools): **search_conversation_history(), check_user_age(), lookup_slang(), is_game_context().
- **פלט: **{is_real_threat: bool, explanation: str, severity_adjustment: int, recommended_action: str}
- **מדדים: **הפחתה של 40%+ ב-False Positives, עלות < $0.005 להפעלה.
### **סוכן 3: Alert Agent (סוכן ההתראה)**
- **תפקיד: **מקבל אירוע מאומת ומחליט: מתי להתריע, איך לנסח להורה, אילו פרטים לכלול, ואיזה משאבי תמיכה לצרף.
- **טכנולוגיה: **LLM קל + RAG על מאגר פרוטוקולי טיפול במצוקה.
- **פלט: **התראה ידידותית להורה כולל הסבר, ציטוט (מצונזר), עצות לפעולה והפניה למקורות מקצועיים (105, מרכזי סיוע).
## **10.2 סוכנים בתהליך הפיתוח (Path A)**
### **Code Reviewer Agent**
סוכן שמקבל commits ובודק איכות קוד, אבטחה, מפתחות חשופים, חוסר תיעוד. מתועד ב-GitHub PR comments.
### **Test Generation Agent**
סוכן שיוצר tests חדשים על בסיס שינויי קוד, מבטיח כיסוי וזיהוי edge cases.
### **Documentation Agent**
סוכן שמתחזק את ה-README, את ספר הפרומפטים ואת ה-API docs באופן אוטומטי לאחר כל commit משמעותי.
### **Data Augmentation Agent**
סוכן ייעודי שמייצר Synthetic Data לפי הנחיות, מסנן איכות ודוחה דוגמאות חלשות – זהו לב ה-Synthetic Data Pipeline.
## **10.3 דיאגרמת זרימה (Conceptual)**
הודעה נכנסת ← Triage Agent (DictaBERT) ← אם ירוק: סוף הזרימה. אם צהוב/אדום: ← Context Agent (LLM) ← אם false alarm: סוף. אם מאומת: ← Alert Agent ← התראה להורה + לוג + RAG update.

# **11. מסמך דרישות מוצר (PRD)**
## **11.1 חזון המוצר**
Shomer.AI הוא שומר דיגיטלי שקט שמסייע להורים להיות מודעים לסיכונים שילדם נחשף אליהם – בלי לקרוא כל הודעה, בלי לפגוע באמון, ובלי להציף בהתראות שווא.
## **11.2 פיצ'רים מרכזיים (Core Features)**

| **#** | **פיצ'ר** | **תיאור** | **עדיפות** |
| --- | --- | --- | --- |
| **F1** | **זיהוי בריונות בעברית** | סריקה של הודעות (וואטסאפ/SMS/אינסטגרם) וזיהוי בריונות, איומים, השפלה | **MUST** |
| **F2** | **סוכן הקשר** | ולידציה של התראות באמצעות LLM להפחתת False Positives | **MUST** |
| **F3** | **התראות חכמות להורה** | התראה במסך הטלפון של ההורה עם הסבר, הקשר, ומקורות סיוע | **MUST** |
| **F4** | **Dashboard הורה** | דשבורד שבועי המציג מגמות (לא תכנים) – שינויים במצב רוח, דפוסי פעילות | **SHOULD** |
| **F5** | **ניתוח תמונות** | סריקת תמונות נכנסות לזיהוי תכן מיני / אלימות (NudeNet + Marqo) | **SHOULD** |
| **F6** | **מצב Co-Pilot לילד** | מתן אפשרות לילד לקבל הצעת תמיכה לפני שההורה מקבל התראה | **COULD** |
| **F7** | **Multi-language** | תמיכה בשפות נוספות (ערבית, רוסית) | **WON'T (V1)** |

## **11.3 דרישות לא-פונקציונליות**
- **Latency: **זמן תגובה ממוצע < 1.5 שניות מהודעה ועד החלטת התראה.
- **Cost: **עלות ממוצעת < $0.005 לאינטראקציה.
- **Privacy: **הצפנה End-to-End, אחסון מינימלי בלבד, ציות לחוק הגנת הפרטיות.
- **Reliability: **Uptime 99.5%, fallback בטוח כשה-LLM נכשל.
- **Explainability: **כל התראה מלווה בהסבר טקסטואלי בעברית.
## **11.4 מדדי הצלחה (KPIs)**

| **מדד** | **יעד Baseline** | **יעד מערכת מלאה** |
| --- | --- | --- |
| **F1 Score (בריונות עברית)** | 0.70-0.75 | **0.85+** |
| **False Positive Rate** | ~25% | **< 10%** |
| **Latency (ממוצע)** | < 200ms | **< 1500ms** |
| **עלות לאינטראקציה** | $0 (local) | **< $0.005** |
| **דיוק זיהוי סלנג עכשווי** | ~60% (ללא Synth) | **> 80% (עם Synth)** |

# **12. תכנית 10 מפגשים ומדדי הצלחה**

| **מפגש** | **נושא** | **תוצרים ואבני דרך** |
| --- | --- | --- |
| **1-2** | **הגדרה ומחקר** | סקר ספרות סופי, מאגרי נתונים מורדים, GitHub repo פעיל, Prompt Book התחלתי, דוח מכין |
| **3-4** | **עסק וארכיטקטורה** | תכנית עסקית, TAM/SAM/SOM, ניתוח עלות טוקנים, PRD סופי, תכנון 3 הסוכנים |
| **5** | **Baseline ו-Fine-tuning** | DictaBERT fine-tuned על OffensiveHebrew, F1 בסיסי מדוד, השוואה ל-AlephBERT |
| **6** | **Synthetic Data + Augmentation** | יצירת 2000 דוגמאות סינתטיות, סינון איכות, אימון מחדש, מדידת שיפור |
| **7** | **בניית הסוכנים** | Context Agent + Alert Agent ב-LangGraph, RAG על פרוטוקולים, integration tests |
| **8** | **בדיקות, Gold Set ומדידה** | תיוג ידני של Gold Set, מדידה סופית של F1, FPR, Latency, Cost. גרפים. |
| **9** | **הפקה ושיווק** | סרטון תדמית (Nano Banana), שיר נושא (SUNO), מצגת מסכמת, דמו מצולם backup |
| **10** | **הגנה והגשה** | Demo live, מענה לשאלות, הצגת ראיות מ-GitHub, הגשה סופית |

# **13. סיכום והצדקה אקדמית**
## **13.1 התאמה לדרישות הקורס**

| **דרישה (לפי ד"ר סגל)** | **מימוש בפרויקט** |
| --- | --- |
| **Value – ערך אמיתי** | בעיה כואבת לכ-1.5M משפחות בישראל; שוק מוכח בינלאומי |
| **AI-Core** | 3 מודלים + 3 סוכנים + RAG – AI הוא לב הפתרון |
| **Learned (חיבור לקורס)** | Fine-tuning, Agents, RAG, Prompt Engineering, Synthetic Data, Cost Analysis |
| **Innovative** | הראשון שמשלב DictaBERT + Context Agent + Synthetic Augmentation בעברית |
| **Doable** | MVP ב-10 מפגשים; כל המאגרים והכלים זמינים וחינמיים |
| **חוק הזהב: Agents** | Path A (בפיתוח) + Path B (במוצר) – כפול |

## **13.2 סיכונים ודרכי התמודדות**
- **סיכון: **ביצועי DictaBERT על סלנג עכשווי נמוכים. **תגובה: **Synthetic Data Pipeline מתוכננת בדיוק לסיכון הזה.
- **סיכון: **עלות LLM הופכת ל-blocker. **תגובה: **ארכיטקטורה היברידית – LLM רק על מקרי גבול (10-20% מהתעבורה).
- **סיכון: **סוגיות משפטיות סביב ניטור ילדים. **תגובה: **מודל מבוסס הסכמת הילד + מצב Co-Pilot שמעניק שליטה לילד.
- **סיכון: **סקופ רחב מדי. **תגובה: **MoSCoW Prioritization ברור – V1 מתמקד בטקסט בלבד; וידאו ואודיו ב-V2.
## **13.3 שאלת המחקר במשפט אחד**
***האם ארכיטקטורת AI היברידית בעברית, המשלבת מסווג קל, סוכן הקשר מבוסס LLM ושכבת Augmentation סינתטית, מצליחה לפתור את בעיית ה-False Positives של מתחרים בינלאומיים בזיהוי בריונות מקוונת – במחיר ובזמן תגובה ראויים למוצר מסחרי?***

# **14. מקורות ורפרנסים**
## **14.1 מאמרים אקדמיים**
**[1] **Shmidman, A., Shmidman, S., Koppel, M., & Bareket, D. (2023). DictaBERT: A State-of-the-Art BERT Suite for Modern Hebrew. arXiv:2308.16687.
**[2] **Seker, A., Bandel, E., Bareket, D., Brusilovsky, I., Greenfeld, R. S., & Tsarfaty, R. (2021). AlephBERT: A Hebrew Large Pre-Trained Language Model. arXiv:2104.04052.
**[3] **Goldin, G., & Wintner, S. (2024). Knesset-DictaBERT: A Hebrew Language Model for Parliamentary Proceedings. arXiv:2407.20581.
**[4] **Shalumov, V., & Haskey, H. (2023). HeRo: RoBERTa and Longformer Hebrew Language Models. arXiv:2304.11077.
**[5] **Paul, S., & Saha, S. (2022). CyberBERT: BERT for Cyberbullying Identification. Multimedia Systems.
**[6] **Aljohani, E. J., & Yafooz, W. M. S. (2025). Enhanced Arabic-language Cyberbullying Detection: Deep Embedding and Transformer (BERT) Approaches. arXiv:2510.02232.
**[7] **Kumar, A., et al. (2025). Cyberbullying Detection in Hinglish Text Using MURIL and Explainable AI. arXiv:2506.16066.
**[8] **Mladenović, M., Ošmjanski, V., & Stanković, S. V. (2021). Cyber-aggression, Cyberbullying, and Cyber-grooming. ACM Computing Surveys, 54(1).
**[9] **Davidson, T., Warmsley, D., Macy, M., & Weber, I. (2017). Automated Hate Speech Detection and the Problem of Offensive Language. ICWSM.
**[10] **Mathew, B., et al. (2021). HateXplain: A Benchmark Dataset for Explainable Hate Speech Detection. AAAI.
**[11] **Long, L., Wang, R., Xiao, R., Zhao, J., Ding, X., Chen, G., & Wang, H. (2024). On LLMs-Driven Synthetic Data Generation, Curation, and Evaluation: A Survey. ACL Findings.
**[12] **Lippmann, P., Spaan, M., & Yang, J. (2024). Exploring LLMs as a Source of Targeted Synthetic Textual Data to Minimize High Confidence Misclassifications. arXiv:2403.17860.
**[13] **Veselovsky, V., Ribeiro, M. H., et al. (2023). Generating Faithful Synthetic Data with Large Language Models. arXiv:2305.15041.
**[14] **Anaby-Tavor, A., et al. (2020). Do Not Have Enough Data? Deep Learning to the Rescue! (LAMBADA). AAAI.
**[15] **Sushil, M., et al. (2024). LLM-based Semantic Augmentation for Harmful Content Detection. arXiv:2504.15548.
**[16] **Sap, M., Card, D., Gabriel, S., Choi, Y., & Smith, N. A. (2019). The Risk of Racial Bias in Hate Speech Detection. ACL.
## **14.2 מאגרי נתונים**
**[D1] **SinaLab (2023). OffensiveHebrew Corpus. https://github.com/SinaLab/OffensiveHebrew
**[D2] **HeNLP (2023). HeDC4: Hebrew Deduplicated and Cleaned Common Crawl Corpus. https://huggingface.co/datasets/HeNLP/HeDC4
**[D3] **Jigsaw (Conversation AI). Toxic Comment Classification Challenge. Kaggle.
**[D4] **Marqo (2024). NSFW Image Detection Model. https://huggingface.co/Marqo/nsfw-image-detection-384
**[D5] **RWF-2000: Real-World Fighting Dataset. arXiv:1911.05913
## **14.3 מתחרים ושוק**
**[M1] **Bark Technologies (2026). Bark Parental Control Review. Security.org & SafeWise.
**[M2] **Qustodio Annual Family Safety Report (2025).
**[M3] **Keepers Child Safety. Interview with CEO Hanan Lipskin (ISRAEL21c, 2018).
**[M4] **Sentry Parental Control – Israeli Innovation Profile (ISRAEL21c).
**[M5] **TechRadar (2026). Best Parental Control App of 2026: Ranked and Reviewed.
**[M6] **SafeWise (2026). The Best Parental Control Apps of 2026.
**[M7] **Helmit (2026). The 5 Best Parental Control Apps in 2026.

*— סוף המסמך —*
