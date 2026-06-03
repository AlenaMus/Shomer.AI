<div dir="rtl">

# Shomer.AI — דיאגרמות ארכיטקטורה

**מסמך:** דיאגרמות עבור Architecture B (טקסט + Chat-OCR + Context Agent יחיד)
**מקורות:** [`plan-docs/decisions/architecture.decision.md`](../plan-docs/decisions/architecture.decision.md)
**סטטוס:** טיוטה למפגש 4 · 2026-05-31
**שימוש:** המסמך משובץ ב-[`PRD.md`](PRD.md) בסעיף הארכיטקטורה. ניתן גם לעיון עצמאי לצורך הגנת הארכיטקטורה.

---

## למה שלוש דיאגרמות?

כל דיאגרמה עונה על שאלה אחרת — לא כל מי שיקרא צריך את כולן:

| דיאגרמה | מה היא עונה | קהל מטרה |
|---|---|---|
| 1 — C4 Container | "מה הרכיבים ואיפה הם רצים?" | ארכיטקטים, DevOps, ד"ר סגל במפגש 4 |
| 2 — Data Flow | "מה הזרימה הלוגית של הנתונים?" | מפתחים — וודאות שיש pipeline אחד ולא שניים |
| 3 — Sequence (מקרה גבול) | "איך זה רץ בפועל בזמן אמת?" | מודיע על ה-RQ; מראה איפה ה-FP-reduction קורה |

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

    subgraph ParentPhone["📱 טלפון הורה (Android)"]
        ParentApp["Shomer.AI Dashboard<br/>+ Push notifications"]
        ParentSDK["Shomer.AI SDK<br/>(Kotlin lib)"]
        ParentApp --> ParentSDK
    end

    ChildSDK -- "message / screenshot<br/>HTTPS" --> Gateway
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
    Server -- "push notification<br/>HTTPS" --> ParentSDK

    classDef local fill:#d4edda,stroke:#155724,color:#000
    classDef external fill:#fff3cd,stroke:#856404,color:#000
    classDef client fill:#d1ecf1,stroke:#0c5460,color:#000
    classDef sdk fill:#e2d5f0,stroke:#5a3e8c,color:#000
    classDef gateway fill:#ffe5b4,stroke:#b8731c,color:#000
    class ChildApp,ParentApp client
    class ChildSDK,ParentSDK sdk
    class Gateway gateway
    class Server,OCR,DictaBERT,Agent,SlangDB,AuditLog,Metrics local
    class GPTMini,Haiku external
```

**מקרא:**
- 🟢 ירוק = רץ מקומית (פרטיות מלאה, אפס עלות שולית)
- 🔵 כחול = לקוח (Android, צד הילד וצד ההורה)
- 🟣 סגול = SDK — ספרייה משותפת ב-Kotlin שיושבת **בתוך** כל קליינט; עוטפת את חוזה ה-API
- 🟠 כתום = Gatekeeper / API Gateway — שכבת Edge של ה-FastAPI; שולטת בעומסים ומספקת observability
- 🟡 צהוב = שירות חיצוני בתשלום (פעיל רק על 15% מקרי גבול)

**נקודות מפתח:**
1. כל הנתונים הרגישים (תוכן השיחות, תמונות) **נשארים ברשת הביתית**. לשירות החיצוני נשלח רק קונטקסט מצומצם (הודעה + עד 5 תורים קודמים, ללא PII).
2. ה-LLM החיצוני **לא חסום-פעולה** — אם נופל, חוזרים על סיווג החזית עם דגל "needs human review".
3. כל החלטה של ה-Context Agent מתועדת ב-Audit Log עם reasoning trace מלא (חובה לניתוח per-slice במפגש 8).
4. **SDK** (סגול) הוא חוזה ה-API היחיד שכל קליינט (אנדרואיד-ילד, אנדרואיד-הורה, web עתידי, 3rd-party integrations) ניגש דרכו. מונע שכפול קוד HTTP בין הקליינטים.
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

## איך הדיאגרמות מעידות על ה-RQ

שאלת המחקר: *"עד כמה הוספת הקשר שיחתי לסיווג בריונות בעברית מפחיתה את שיעור ה-false positives לעומת סיווג מבודד — מבלי לפגוע ב-recall?"*

הניסוי המוטמע בארכיטקטורה:
- **תנאי control (context-blind):** המסווג בלבד מחליט. בדיאגרמה 3, זה השלבים 1–3 בלבד; ההחלטה תהיה לפי `confidence ≥ 0.5` → "is_threat = true" → **התראת FP**.
- **תנאי treatment (context-aware):** המסווג + Context Agent. בדיאגרמה 3, זה הזרימה המלאה; ההחלטה לאחר reasoning → "is_real_threat = false" → **התראה נמנעה**.
- **המדידה:** הפרש ה-FPR בין שני התנאים על gold set מתויג ידנית (מפגש 8).

הארכיטקטורה לא רק תומכת ב-RQ — היא **מממשת את הניסוי כפיצ'ר מובנה** של המוצר.

</div>
