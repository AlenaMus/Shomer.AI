<div dir="rtl">

# Shomer.AI — דיאגרמות ארכיטקטורה

**מסמך:** דיאגרמות עבור Architecture B (טקסט + Chat-OCR + Context Agent יחיד)
**מקורות:** [`plan-docs/decisions/architecture.decision.md`](../plan-docs/decisions/architecture.decision.md)
**סטטוס:** טיוטה למפגש 4 · 2026-05-31
**שימוש:** המסמך משובץ ב-[`PRD.md`](PRD.md) בסעיף הארכיטקטורה. ניתן גם לעיון עצמאי לצורך הגנת הארכיטקטורה.

---

## למה חמש דיאגרמות?

כל דיאגרמה עונה על שאלה אחרת — לא כל מי שיקרא צריך את כולן:

| דיאגרמה | מה היא עונה | קהל מטרה |
|---|---|---|
| 1 — C4 Container | "מה הרכיבים ואיפה הם רצים?" | ארכיטקטים, DevOps, ד"ר סגל במפגש 4 |
| 2 — Data Flow | "מה הזרימה הלוגית של הנתונים?" | מפתחים — וודאות שיש pipeline אחד ולא שניים |
| 3 — Sequence (מקרה גבול) | "איך זה רץ בפועל בזמן אמת?" | מודיע על ה-RQ; מראה איפה ה-FP-reduction קורה |
| 4 — Onboarding (הרשמה → OTP במייל → צימוד) | "איך הורה וילד מתחברים למערכת בפעם הראשונה?" | מפתחים, מציגי הדמו |
| 5 — אימות והפרדת נתונים לפי ילד | "איך נאכפת ההפרדה בין הורים ובין ילדים?" | אבטחה/פרטיות, הגנת הפרויקט |

---

## דיאגרמה 1 — תצוגת מערכת ברמת C4 Container

מציגה את כל המכלים (containers) של המערכת, את גבולות האמון (trust boundaries), ואת תזרים המידע הראשי בין הילד, השרת הביתי, השירות החיצוני (LLM בתשלום), וההורה.

```mermaid
flowchart TB
    subgraph ChildPhone["📱 טלפון ילד (Android)"]
        ChildApp["Shomer.AI Client<br/>(Kotlin/Compose, UI)"]
        ChildSDK["Shomer.AI SDK<br/>(Kotlin lib)"]
        ChildApp --> ChildSDK
    end

    subgraph HomeNet["🏠 רשת ביתית מקומית (פרטיות מלאה)"]
        Gateway["🚦 Gatekeeper / API Gateway<br/>(rate-limit · logging · metrics)"]
        Server["FastAPI Server :8000<br/>(classification core)"]
        OCR["Tesseract OCR<br/>(heb+eng)"]
        DictaBERT["DictaBERT-base<br/>frontline classifier"]
        Agent["Context Agent<br/>(in-process)"]
        SlangDB["Slang Lexicon<br/>(local DB)"]
        AuditLog["Audit Log<br/>(7-day retention)"]
        Metrics[("📊 Metrics<br/>/metrics endpoint")]
    end

    subgraph External["☁️ שירות חיצוני (paid, רק 15% מהתעבורה)"]
        GPTMini["GPT-4o-mini<br/>(primary)"]
        Haiku["Claude Haiku 4.5<br/>(fallback)"]
    end

    subgraph ParentSide["💻 הורה (דפדפן + מייל)"]
        ParentWeb["Web Dashboard<br/>(/dashboard/ — login אימייל+סיסמה)"]
        ParentMail["📧 תיבת המייל של ההורה<br/>(OTP + התראות)"]
    end

    Mailer["📧 Mailer port<br/>(Log / SMTP / Gmail API)"]

    ChildSDK -- "message / screenshot<br/>HTTPS" --> Gateway
    ParentWeb -- "login · alerts · digests · react<br/>HTTPS (Bearer)" --> Gateway
    Gateway -- "validated, rate-limit OK" --> Server
    Gateway -- "emit metrics + structured log" --> Metrics
    Server -- "if image" --> OCR
    OCR -- "extracted text" --> Server
    Server -- "classify" --> DictaBERT
    DictaBERT -- "{label, confidence}" --> Server
    Server -- "if borderline (0.3-0.7)" --> Agent
    Agent -- "tool: read history / slang" --> SlangDB
    Agent -- "reason about context" --> GPTMini
    GPTMini -- "{is_threat, explanation}" --> Agent
    Agent -. "if API unreachable" .-> Haiku
    Server -- "log full trace" --> AuditLog
    Server -- "OTP בהרשמה · התראות אימייל" --> Mailer
    Mailer -- "email" --> ParentMail

    classDef local fill:#d4edda,stroke:#155724,color:#000
    classDef external fill:#fff3cd,stroke:#856404,color:#000
    classDef client fill:#d1ecf1,stroke:#0c5460,color:#000
    classDef sdk fill:#e2d5f0,stroke:#5a3e8c,color:#000
    classDef gateway fill:#ffe5b4,stroke:#b8731c,color:#000
    class ChildApp,ParentWeb,ParentMail client
    class ChildSDK sdk
    class Gateway gateway
    class Server,OCR,DictaBERT,Agent,SlangDB,AuditLog,Metrics,Mailer local
    class GPTMini,Haiku external
```

> **עדכון 2026-06-12 (D-CO-1/D-CO-2 + dashboard login):** צד ההורה עבר מאפליקציית אנדרואיד ל-**Web Dashboard**
> הנגיש בכתובת `http://<server>:8000/dashboard/` (מוגש ע"י FastAPI עצמו), עם התחברות **אימייל+סיסמה**.
> אפליקציית האנדרואיד היא **child-only**. ערוץ ההתראות להורה הוא **אימייל** (Gmail API / SMTP / Log),
> דרך אותו port של שליחת מייל שמשמש גם את ה-OTP בתהליך ה-Onboarding (דיאגרמה 4).

**מקרא:**
- 🟢 ירוק = רץ מקומית (פרטיות מלאה, אפס עלות שולית)
- 🔵 כחול = לקוח (אפליקציית Android בצד הילד; דפדפן + תיבת מייל בצד ההורה)
- 🟣 סגול = SDK — ספרייה משותפת ב-Kotlin שיושבת **בתוך** קליינט האנדרואיד; עוטפת את חוזה ה-API (ה-Web Dashboard ניגש ל-API ישירות, ללא build)
- 🟠 כתום = Gatekeeper / API Gateway — שכבת Edge של ה-FastAPI; שולטת בעומסים ומספקת observability
- 🟡 צהוב = שירות חיצוני בתשלום (פעיל רק על 15% מקרי גבול)

**נקודות מפתח:**
1. כל הנתונים הרגישים (תוכן השיחות, תמונות) **נשארים ברשת הביתית**. לשירות החיצוני נשלח רק קונטקסט מצומצם (הודעה + עד 5 תורים קודמים, ללא PII).
2. ה-LLM החיצוני **לא חסום-פעולה** — אם נופל, חוזרים על סיווג החזית עם דגל "needs human review".
3. כל החלטה של ה-Context Agent מתועדת ב-Audit Log עם reasoning trace מלא (חובה לניתוח per-slice במפגש 8).
4. **SDK** (סגול) הוא חוזה ה-API שקליינט האנדרואיד (child-only) ניגש דרכו; ה-Web Dashboard של ההורה צורך את אותו חוזה REST ישירות מהדפדפן. מונע שכפול קוד HTTP בין הקליינטים.
5. **Gatekeeper / API Gateway** (כתום) הוא שכבת Edge: כל בקשה עוברת דרכה לרייט-לימיט, validation, ולוגינג מובנה לפני שמגיעה לסיווג. מימוש MVP = FastAPI middleware (`slowapi` + `structlog` + `prometheus-fastapi-instrumentator`). מטרתו תפעולית — שליטה בעומסים + observability — ולא חלק מהסיווג עצמו.

---

## דיאגרמה 2 — Data Flow: שני מסלולי הקלט מתאחדים

מראה איך הודעת טקסט וצילום מסך חולקים את אותו pipeline מהמסווג הקדמי ואילך. **זוהי בדיוק ההצדקה לדחיית Architecture A** — אין צורך ב-Vision LLM כי הטקסט שבתוך התמונות חולץ דרך OCR ונכנס לאותו צינור.

```mermaid
flowchart LR
    subgraph Inputs["🟦 קלטים"]
        TxtMsg["טקסט<br/>(הודעה ישירה)"]
        ScrShot["צילום מסך<br/>(וואטסאפ, אינסטגרם וכו')"]
    end

    subgraph Processing["🟩 עיבוד מקומי"]
        OCRBlock["Tesseract OCR<br/>(heb+eng)"]
        Class["DictaBERT-base<br/>frontline classifier"]
        Decision{"confidence<br/>borderline?<br/>(0.3-0.7)"}
        CtxAgent["Context Agent<br/>+ GPT-4o-mini"]
        Combine["combine final decision"]
    end

    subgraph Outputs["🟥 פלטים"]
        Alert["🔔 alert להורה<br/>(push + explanation + quote)"]
        Silent["🤫 silent<br/>(no alert)"]
        Manual["⚠️ needs human review<br/>(LLM fallback)"]
    end

    TxtMsg --> Class
    ScrShot --> OCRBlock
    OCRBlock --> Class
    Class --> Decision
    Decision -- "confident<br/>(≥ 0.7 or ≤ 0.3)" --> Combine
    Decision -- "borderline<br/>(0.3-0.7)" --> CtxAgent
    CtxAgent --> Combine
    Combine -- "is_threat = true" --> Alert
    Combine -- "is_threat = false" --> Silent
    CtxAgent -. "if LLM unreachable" .-> Manual

    classDef input fill:#d1ecf1,stroke:#0c5460
    classDef process fill:#d4edda,stroke:#155724
    classDef external fill:#fff3cd,stroke:#856404
    classDef output fill:#f8d7da,stroke:#721c24
    class TxtMsg,ScrShot input
    class OCRBlock,Class,Decision,Combine process
    class CtxAgent external
    class Alert,Silent,Manual output
```

**המסר העיקרי:** OCR קורא טקסט מתוך תמונות → הטקסט נכנס לאותו pipeline. אין שני pipelines נפרדים. החיסכון הזה הוא ההצדקה ההנדסית לוויתור על Vision LLM (Architecture A).

**שלוש האפשרויות הסופיות:**
- **Alert** — התראת push להורה עם הסבר וציטוט (לא קופסה שחורה)
- **Silent** — הסיווג קבע שהמקרה תמים, אין הפרעה להורה (Alert Fatigue מינימלי)
- **Manual review** — מסומן רק כשה-LLM החיצוני אינו זמין (graceful degradation)

---

## דיאגרמה 3 — Sequence: זרימת מקרה גבול עם reasoning של Context Agent

מציגה את הסדר הכרונולוגי המלא — מהילד שולח הודעה ועד להתראה (או לא) אצל ההורה — במקרה גבול שדורש את ה-Context Agent. דיאגרמה זו היא הליבה של ה-RQ: היא מראה **איפה ולמה** ה-FP-reduction קורה.

```mermaid
sequenceDiagram
    autonumber
    participant Child as 👶 ילד<br/>(Client)
    participant API as 🖥️ FastAPI
    participant Class as 🧠 DictaBERT
    participant Agent as 🤖 Context Agent
    participant Tools as 🛠️ Tools (DB+Lex)
    participant LLM as ☁️ GPT-4o-mini
    participant Log as 📝 Audit Log
    participant Parent as 👨‍👩‍👧 הורה

    Child->>API: POST /classify<br/>{text: "תפסיק להיות כזה לוזר"}
    API->>Class: classify(text)
    Class-->>API: {label: "abusive", confidence: 0.55}
    Note over API: ⚠️ borderline! escalate to Context Agent

    API->>Agent: handle_borderline(text, conversation_id)
    Agent->>Tools: read_conversation_history(id, n=5)
    Tools-->>Agent: [prev_turns: 5 messages of friendly banter]
    Agent->>Tools: lookup_slang("לוזר")
    Tools-->>Agent: {meaning: "loser", common_use: "playful_among_friends"}
    Agent->>Tools: check_age_appropriateness(child_age=13)
    Tools-->>Agent: {sensitivity_level: "moderate"}

    Agent->>LLM: reason({message, prev_turns, slang_meta, age})
    LLM-->>Agent: {is_real_threat: false,<br/>explanation: "playful banter, not bullying"}

    Agent->>Log: log full reasoning trace + decision
    Agent-->>API: {is_real_threat: false, source: "context_aware"}
    API-->>Parent: 🤫 silent (no notification)

    Note over LLM,Parent: ⚠️ alternative flow: LLM unreachable
    rect rgb(255, 230, 230)
    Agent-xLLM: timeout / network failure
    Agent->>Log: log fallback event
    Agent-->>API: {is_real_threat: true,<br/>source: "frontline_only",<br/>review_flag: true}
    API->>Parent: 🔔 alert<br/>("⚠️ אנא בדוק ידנית — נימוק הקשר לא זמין")
    end
```

**מה הדיאגרמה מראה (נקודות לציון בהגנה):**

1. **השלבים 1–3 (סיווג ראשוני):** רץ במאות מיליאניות — DictaBERT מקומי, ללא קריאות חיצוניות.

2. **השלב 4 (החלטת הסלמה):** רק כשה-confidence ב-borderline zone (0.3–0.7). זה ה-15% מהתעבורה שמגיע ל-Context Agent ומגלם את עיקר ה-cost.

3. **השלבים 5–10 (ה-Context Agent):** הסוכן קורא היסטוריה + מילון סלנג + פרופיל גיל **לפני** הקריאה ל-LLM. הכלים חוסכים טוקנים ע"י הזרמת רק המידע הרלוונטי.

4. **השלב 11 (reasoning):** ה-LLM החיצוני (GPT-4o-mini) מקבל קונטקסט תמציתי ומחזיר החלטה + הסבר. **זה המנגנון שעונה על ה-RQ** — סיווג ההודעה ה"גבולית" משתפר ע"י reasoning על ההקשר.

5. **השלב 14 (תוצאה):** במקרה הזה ה-Context Agent קבע שהמסר תמים (סלנג ידידותי בהקשר של שיחה צוחקת) → **אין התראה** → **הפחתת FP**.

6. **המסלול האדום (fallback):** אם ה-LLM אינו זמין, המערכת לא חוסמת את ההתראה — שולחת אותה עם דגל "needs human review". עיקרון: **לעולם לא לאבד התראה בשקט במערכת בטיחות ילדים**.

---

## דיאגרמה 4 — Onboarding: הרשמת הורה → OTP במייל → צימוד מכשיר הילד

**נוסף 2026-06-12.** מציגה את חיבור המערכת בפעם הראשונה: ההורה נרשם ב-Web Dashboard עם
**אימייל + סיסמה + שם הילד/ה**, מקבל **קוד התאמה (OTP) למייל**, מזין אותו באפליקציית הילד —
והמכשיר מצומד. מאותו רגע ההורה מתחבר לדשבורד עם אימייל+סיסמה ורואה רק את הילדים שלו.

```mermaid
sequenceDiagram
    autonumber
    participant Parent as 👨‍👩‍👧 הורה (דפדפן)
    participant Dash as 💻 Web Dashboard<br/>(/dashboard/)
    participant API as 🖥️ FastAPI
    participant ID as 🗄️ Identity Store<br/>(SQLite)
    participant Mail as 📧 EmailSender port<br/>(Log / SMTP / Gmail)
    participant ChildApp as 📱 אפליקציית הילד<br/>(child-only)

    Parent->>Dash: פתיחת http://server:8000/dashboard/
    Dash-->>Parent: מסך הרשמה ממורכז (שם, אימייל, סיסמה, שם הילד/ה)
    Parent->>API: POST /v1/parent/register<br/>{display_name, email, password, child_name}
    API->>ID: יצירת הורה (סיסמה: PBKDF2-SHA256, 600k)<br/>+ ילד + קוד התאמה (תוקף 10 דק', חד-פעמי)
    API->>Mail: send(parent_email, "Shomer.AI — קוד התאמה", OTP)
    Mail-->>Parent: 📧 מייל עם קוד ההתאמה
    API-->>Dash: 201 {parent_token, child_id, pairing_code, expires_in}
    Dash-->>Parent: מסך Onboarding: הקוד + מדריך 3 שלבים + ספירה לאחור
    Parent->>ChildApp: הזנת ה-OTP באפליקציית Shomer במכשיר הילד
    ChildApp->>API: POST /v1/pair {code}
    API->>ID: אימות OTP → הנפקת device_token (role=child)
    API-->>ChildApp: 200 {device_token, child_id}
    Note over ChildApp: הניטור מתחיל (consent → AccessibilityService<br/>→ /v1/monitor/events עם ה-device_token)
    Parent->>API: POST /v1/parent/login {email, password}
    API-->>Parent: 200 {parent_token}
    Parent->>API: GET /v1/parent/alerts?child_id=… (Bearer)
    API-->>Parent: התראות של הילד הנבחר בלבד
```

**נקודות מפתח:**

1. **ערוץ ה-OTP הוא אימייל** (שלבים 5–6): הקוד נשלח לכתובת שההורה נרשם איתה, דרך port אחיד
   `EmailSender` (`server/app/mailer/`). באותו port: `LogEmailSender` (ברירת-מחדל לפיתוח — הקוד מודפס
   ללוג), `SmtpEmailSender` (‏`MAILER_BACKEND=smtp`, למשל Gmail app-password), ומקביל לו בערוץ ההתראות —
   `GmailApiNotifier` ‏(OAuth2, ‏`ALERTS_CHANNEL=email`; ראו `child-only-and-email-alerts.decision.md`).
   ב-MVP הקוד גם מוצג על המסך בדשבורד (פרגמטיות לדמו) — האימייל הוא הערוץ הראשי.
2. **ה-OTP קושר את מכשיר הילד להורה הנכון**: הקוד מונפק עבור `child_id` ספציפי תחת `parent_id`
   ספציפי; פדיון הקוד (`/v1/pair`) מנפיק `device_token` שכל העלאות הניטור שלו משויכות לאותו ילד.
3. **שני סוגי credentials, תפקידים שונים:** להורה — אימייל+סיסמה שממירים ל-`parent_token` אטום;
   לילד — `device_token` אטום שנולד מה-OTP. אין סיסמה במכשיר הילד.
4. **צימוד ילדים נוספים** נעשה מתוך הדשבורד ("הוסף ילד/ה" / "קוד התאמה") — אותו מנגנון OTP+מייל,
   ללא הרשמה חוזרת.

---

## דיאגרמה 5 — אימות והפרדת נתונים מלאה לפי ילד

**נוסף 2026-06-12.** מראה איך כל בקשת נתונים של הורה נחתכת לילדים שבבעלותו בלבד, ואיך ה-UI
כופה בחירת ילד לפי **שם** — כך שהדשבורד מציג בכל רגע נתונים של ילד אחד בלבד.

```mermaid
flowchart TB
    Login["POST /v1/parent/login<br/>{email, password}"] --> Verify{"אימות סיסמה<br/>PBKDF2 + compare_digest"}
    Verify -- "כשל (אימייל לא קיים / סיסמה שגויה)" --> R401["401 — תשובה זהה לשני המקרים<br/>(אין user enumeration)"]
    Verify -- "הצלחה" --> Token["parent_token אטום<br/>(נשמר בדפדפן)"]

    Token --> MW["DeviceAuthMiddleware<br/>(Gatekeeper — content-blind)"]
    MW --> Ctx["DeviceContext{parent_id, role=parent}"]
    Ctx --> Owned["identity.list_children(parent_id)<br/>→ owned_child_ids"]

    UI["Dashboard UI:<br/>בחירת ילד לפי שם (חובה)<br/>כל בקשה נושאת child_id"] --> Q{"child_id ∈ owned?"}
    Owned --> Q
    Q -- "כן" --> Data["alerts / digests / react<br/>של הילד הנבחר בלבד"]
    Q -- "לא (ילד של הורה אחר)" --> R403["403 / 404<br/>(ownership-blind)"]

    classDef ok fill:#d4edda,stroke:#155724,color:#000
    classDef bad fill:#f8d7da,stroke:#721c24,color:#000
    classDef neutral fill:#d1ecf1,stroke:#0c5460,color:#000
    class Login,Token,MW,Ctx,Owned,UI neutral
    class Data ok
    class R401,R403 bad
```

**איפה ההפרדה נאכפת (שכבתיים — גם שרת וגם UI):**

| שכבה | מנגנון | קובץ |
|---|---|---|
| שרת — זהות | כל endpoint הורי טוען `list_children(parent_id)` ומסנן אליהם בלבד; `child_id` זר ⇒ 403/404 | `server/app/flagged/router.py`, `server/app/digest/router.py` |
| שרת — אימות | טוקנים אטומים; סיסמאות PBKDF2-SHA256 עם salt פר-משתמש; 401 אחיד | `server/app/identity/` |
| UI — הפרדה לפי שם | אין מצב "כל הילדים" ואין קלט חופשי של מזהה ילד: ההורה בוחר ילד **לפי שם** (צ'יפים), וכל בקשה נשלחת עם ה-`child_id` הנבחר; אינדיקציה "מציג נתונים עבור: ⟨שם⟩" | `dashboard/index.html` |

ההפרדה בין **הורים** מאומתת בבדיקות (`server/tests/parent/test_cross_parent_isolation.py`,
`server/tests/identity/test_parent_login.py`); ההפרדה בין **ילדים** של אותו הורה נאכפת ב-UI (בחירה
מפורשת) וב-API (פרמטר `child_id` מסונן מול הבעלות).

---

## איך הדיאגרמות מעידות על ה-RQ

שאלת המחקר: *"עד כמה הוספת הקשר שיחתי לסיווג בריונות בעברית מפחיתה את שיעור ה-false positives לעומת סיווג מבודד — מבלי לפגוע ב-recall?"*

הניסוי המוטמע בארכיטקטורה:
- **תנאי control (context-blind):** המסווג בלבד מחליט. בדיאגרמה 3, זה השלבים 1–3 בלבד; ההחלטה תהיה לפי `confidence ≥ 0.5` → "is_threat = true" → **התראת FP**.
- **תנאי treatment (context-aware):** המסווג + Context Agent. בדיאגרמה 3, זה הזרימה המלאה; ההחלטה לאחר reasoning → "is_real_threat = false" → **התראה נמנעה**.
- **המדידה:** הפרש ה-FPR בין שני התנאים על gold set מתויג ידנית (מפגש 8).

הארכיטקטורה לא רק תומכת ב-RQ — היא **מממשת את הניסוי כפיצ'ר מובנה** של המוצר.

</div>
