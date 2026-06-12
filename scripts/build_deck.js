// Build the Shomer.AI bilingual (English headers + Hebrew RTL body) presentation deck.
// Run: node scripts/build_deck.js
const path = require("path");
const PPTX = require(path.join(process.env.APPDATA, "npm", "node_modules", "pptxgenjs"));
const ROOT = path.resolve(__dirname, "..");
const A = (p) => path.join(ROOT, p);

const pres = new PPTX();
pres.layout = "LAYOUT_WIDE"; // 13.3 x 7.5
pres.author = "Alona Musiyko";
pres.title = "Shomer.AI";

// ---- palette ----
const NAVY = "1B2A4A", TEAL = "028090", MINT = "02C39A", ICE = "CADCFC",
      LIGHT = "F5F7FA", WHITE = "FFFFFF", CORAL = "E45756", GOLD = "F2B705",
      INK = "23303F", MUTE = "6B7A8D", SLATE = "33475B",
      RESULT = "0E9F6E",      // result highlight on light bg (bold + this color)
      RESULT_D = "27E0A8",    // result highlight on dark bg
      OCRC = "1C7293", TRIC = "0B7285", ALRT = "C44E00";
const HEB = "Arial";     // Hebrew body
const HEAD = "Georgia";  // English headers (premium serif, pairs with Arial)

// ---- text helpers ----
const heb = (extra = {}) => ({ fontFace: HEB, rtlMode: true, align: "right", ...extra });
const mkShadow = () => ({ type: "outer", color: "000000", blur: 7, offset: 3, angle: 135, opacity: 0.15 });

// markup: **concept** -> bold concept color ; [[result]] -> bold result color
function parseRuns(md) {
  const out = []; const re = /(\*\*[^*]+\*\*|\[\[[^\]]+\]\])/g; let last = 0, m;
  while ((m = re.exec(md)) !== null) {
    if (m.index > last) out.push({ t: md.slice(last, m.index), k: "n" });
    const tok = m[0];
    out.push(tok[0] === "*" ? { t: tok.slice(2, -2), k: "c" } : { t: tok.slice(2, -2), k: "r" });
    last = re.lastIndex;
  }
  if (last < md.length) out.push({ t: md.slice(last), k: "n" });
  return out;
}

// Manual bullet/number markers (reliable RTL: marker is the logical-first run -> renders on the right).
function bulletsRich(slide, items, opts = {}) {
  const dark = !!opts.dark;
  const base = opts.color || (dark ? ICE : SLATE);
  const cColor = dark ? WHITE : NAVY;          // concept bold color
  const rColor = dark ? RESULT_D : RESULT;     // result bold color
  const mColor = opts.marker || (dark ? MINT : TEAL);
  const fs = opts.fontSize || 17, gap = opts.gap ?? 12;
  const runs = [];
  items.forEach((it, ii) => {
    const o = typeof it === "string" ? { md: it } : it;
    const parts = parseRuns(o.md), itemFs = o.s || fs;
    const marker = opts.numbered ? `${ii + 1}.  ` : "•  ";
    runs.push({ text: marker, options: heb({ color: o.mc || mColor, bold: true, fontSize: itemFs, breakLine: false }) });
    parts.forEach((p, idx) => {
      const isLast = idx === parts.length - 1;
      let color = o.c || base, bold = !!o.b;
      if (p.k === "c") { bold = true; color = o.cc || cColor; }
      if (p.k === "r") { bold = true; color = rColor; }
      runs.push({ text: p.t, options: heb({ breakLine: isLast, color, bold, fontSize: itemFs, paraSpaceAfter: isLast ? gap : 0 }) });
    });
  });
  slide.addText(runs, { x: opts.x ?? 0.85, y: opts.y ?? 1.85, w: opts.w ?? 8.3, h: opts.h ?? 4.9, valign: "top" });
}

function header(slide, en, desc, opts = {}) {
  const color = opts.color || NAVY, accent = opts.accent || TEAL;
  slide.addShape(pres.shapes.RECTANGLE, { x: 0.6, y: 0.48, w: 0.14, h: 0.86, fill: { color: accent } });
  slide.addText(en, { x: 0.88, y: 0.38, w: 11.9, h: 0.68, fontFace: HEAD, bold: true, fontSize: 29, color, align: "left" });
  // descriptive sentence under the header (full sentence, right-aligned RTL)
  if (desc) slide.addText(desc, heb({ x: 0.7, y: 1.12, w: 12.0, h: 0.5, fontSize: 14, color: opts.gloss || SLATE, align: "right", valign: "top" }));
}

function footer(slide, n, dark = false) {
  const c = dark ? "8198B5" : "AAB6C4";
  slide.addText("Shomer.AI", { x: 0.6, y: 7.06, w: 3, h: 0.3, fontFace: HEAD, italic: true, fontSize: 10, color: c, align: "left" });
  slide.addText(String(n), { x: 12.2, y: 7.06, w: 0.5, h: 0.3, fontFace: HEAD, fontSize: 10, color: c, align: "right" });
}

function statCard(slide, x, y, w, big, label, accent = RESULT, bigFs = 28) {
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h: 1.5, fill: { color: WHITE }, line: { color: "E2E8F0", width: 1 }, rectRadius: 0.08, shadow: mkShadow() });
  slide.addShape(pres.shapes.RECTANGLE, { x, y, w, h: 0.1, fill: { color: accent } });
  slide.addText(big, { x: x + 0.08, y: y + 0.16, w: w - 0.16, h: 0.66, fontFace: HEAD, align: "center", bold: true, fontSize: bigFs, color: accent });
  slide.addText(label, heb({ x: x + 0.12, y: y + 0.82, w: w - 0.24, h: 0.6, align: "center", valign: "top", fontSize: 12.5, color: MUTE }));
}

const arrowR = (s, x, y, w, color, width = 2, dash) => s.addShape(pres.shapes.LINE, { x, y, w, h: 0, line: { color, width, endArrowType: "triangle", ...(dash ? { dashType: "dash" } : {}) } });

// ============================================================ 1. TITLE
{
  const s = pres.addSlide();
  s.background = { color: NAVY };
  s.addShape(pres.shapes.OVAL, { x: -2.2, y: 4.6, w: 6, h: 6, fill: { color: TEAL, transparency: 86 } });
  s.addShape(pres.shapes.OVAL, { x: 9.6, y: -2.4, w: 6.6, h: 6.6, fill: { color: TEAL, transparency: 88 } });
  s.addImage({ path: A("assets/hero_shield.png"), x: 8.7, y: 1.5, w: 4.4, h: 4.4 });
  s.addText("Shomer.AI", { x: 0.8, y: 1.5, w: 7.6, h: 1.2, fontFace: HEAD, bold: true, fontSize: 60, color: WHITE, align: "left" });
  s.addText("שומר.AI", heb({ x: 0.8, y: 2.72, w: 7.6, h: 0.8, fontSize: 30, color: MINT, align: "left" }));
  s.addText("Context-Aware Bullying Detection for Hebrew Children's Chats",
    { x: 0.8, y: 3.55, w: 7.7, h: 0.6, fontFace: HEAD, italic: true, fontSize: 17, color: ICE, align: "left" });
  s.addText("מערכת בינה מלאכותית לזיהוי תוכן פוגעני בשיחות ילדים — בעברית, בהקשר, בזמן אמת",
    heb({ x: 0.8, y: 4.2, w: 7.7, h: 0.8, fontSize: 14, color: "9FB3C8", align: "left" }));
  s.addShape(pres.shapes.LINE, { x: 0.8, y: 5.45, w: 7.4, h: 0, line: { color: TEAL, width: 1.5 } });
  s.addText([
    { text: "Alona Musiyko", options: { fontFace: HEAD, bold: true, fontSize: 16, color: WHITE, align: "left", breakLine: true } },
    { text: "Final Project  ·  Supervisor: Dr. Yoram Segal", options: { fontFace: HEAD, italic: true, fontSize: 12.5, color: "9FB3C8", align: "left" } },
  ], { x: 0.8, y: 5.6, w: 7.6, h: 1.0, valign: "top" });
}

// ============================================================ 2. ACKNOWLEDGEMENTS
{
  const s = pres.addSlide();
  s.background = { color: NAVY };
  s.addShape(pres.shapes.OVAL, { x: 10.4, y: 4.8, w: 5.2, h: 5.2, fill: { color: TEAL, transparency: 88 } });
  s.addText("Acknowledgements", { x: 0.88, y: 0.55, w: 10.5, h: 0.9, fontFace: HEAD, bold: true, fontSize: 38, color: WHITE, align: "left" });
  s.addText("תודות", heb({ x: 0.88, y: 1.35, w: 10.5, h: 0.4, fontSize: 15, color: "9FB3C8", align: "left" }));
  s.addText("❤", { x: 11.7, y: 0.62, w: 0.9, h: 0.85, fontFace: HEB, fontSize: 38, color: CORAL, align: "center", valign: "middle" });
  const card = (y, name, body, accent) => {
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 1.3, y, w: 10.7, h: 1.9, fill: { color: "24375C" }, line: { color: accent, width: 1.5 }, rectRadius: 0.1, shadow: mkShadow() });
    s.addShape(pres.shapes.RECTANGLE, { x: 11.86, y: y + 0.18, w: 0.12, h: 1.54, fill: { color: accent } });
    s.addText(name, heb({ x: 1.6, y: y + 0.22, w: 10.0, h: 0.55, fontSize: 21, bold: true, color: WHITE }));
    s.addText(body, heb({ x: 1.6, y: y + 0.82, w: 10.0, h: 0.95, fontSize: 16, color: ICE, valign: "top" }));
  };
  card(2.1, "ד\"ר יורם סגל — המרצה והמנחה",
    "על השיעורים והמטלות המעניינים והמאתגרים, ועל ההכוונה והליווי לאורך כל הדרך.", MINT);
  card(4.35, "דימה שלייב — בעלי",
    "על שנתן לי את הזמן וההזדמנות ללמוד, להעמיק ולהשתפר בתחום ה-AI.", GOLD);
  footer(s, 2, true);
}

// ============================================================ 3. PROBLEM
{
  const s = pres.addSlide();
  s.background = { color: LIGHT };
  header(s, "The Problem", "הורים אינם מודעים בזמן אמת לבריונות בשיחות ילדיהם, והכלים הקיימים שופטים כל הודעה במנותק — ומפספסים את ההקשר.");
  bulletsRich(s, [
    { md: "בריונות מקוונת בקרב ילדים היא תופעה נפוצה ומסכנת — אך מרבית ההורים אינם מודעים לה בזמן אמת", b: true, c: INK },
    "שיחות הילדים מתנהלות ב**עברית** — שפה שכלי הבטיחות הקיימים כמעט אינם תומכים בה",
    "הכלים הקיימים בוחנים כל הודעה בנפרד (**context-blind**), ומחמיצים איומים נסתרים, הסלמה ותבניות פגיעה הנבנות לאורך שיחה שלמה",
    "מעקב מלא אחר ההתכתבויות פוגע ב**פרטיות** הילד ובאמון בין ההורה לילד",
    "עומס של **false alarms** גורם להורים להפסיק להתייחס לאזהרות — ומאיין את ערך הכלי",
  ], { x: 4.7, y: 1.85, w: 8.05, gap: 14, fontSize: 18 });
  const bub = (x, y, w, col, txtcol, label) => {
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h: 0.95, fill: { color: col }, rectRadius: 0.14, shadow: mkShadow() });
    s.addText(label, heb({ x: x + 0.18, y, w: w - 0.36, h: 0.95, fontSize: 14, color: txtcol, valign: "middle" }));
  };
  bub(0.7, 2.0, 3.4, WHITE, INK, "סתם צוחקים יחד 😄");
  bub(1.2, 3.15, 3.0, CORAL, WHITE, "כולם נגדך, תיעלם כבר");
  bub(0.7, 4.3, 3.5, WHITE, INK, "אתה יודע מה מחכה לך מחר…");
  bub(1.3, 5.45, 2.9, GOLD, NAVY, "❓ פוגעני או תמים?");
  footer(s, 3);
}

// ============================================================ 4. SOLUTION
{
  const s = pres.addSlide();
  s.background = { color: LIGHT };
  header(s, "The Solution & Value", "Shomer.AI מזהה תוכן פוגעני בעברית תוך התחשבות בהקשר השיחה, ומתריעה להורה רק כשמדובר באירוע אמיתי.");
  bulletsRich(s, [
    { md: "**Real-time** — ניטור שיחות בזמן אמת וזיהוי תוכן פוגעני בעברית" },
    { md: "**Context-aware** — ניתוח עד 5 הודעות אחורה לזיהוי הסלמות, התקפות קבוצתיות ואיומים נסתרים" },
    { md: "**Privacy-by-design** — ריצה ברקע בלבד, ללא גישה לתמונות, אנשי קשר או תוכן לא-רלוונטי" },
    { md: "**Hebrew-native** — בנויה לשפה שהכלים הקיימים מתעלמים ממנה" },
    { md: "**Low false-alarms** — מתריעה רק על מצב פוגעני אמיתי, ללא הצפת התרעות" },
  ], { x: 4.6, y: 2.0, w: 8.15, gap: 16, fontSize: 18 });
  statCard(s, 0.7, 2.05, 3.5, "55.9 → 26.5%", "התרעות-שווא: context-aware מול context-blind", RESULT, 23);
  statCard(s, 0.7, 3.75, 3.5, "0 → 100%", "זיהוי איומים נסתרים: עם הקשר מול בלי", TEAL, 26);
  statCard(s, 0.7, 5.45, 3.5, "Hebrew", "סיווג נֵייטיב + הקשר שיחתי", GOLD, 26);
  footer(s, 4);
}

// ============================================================ 5. ARCHITECTURE
{
  const s = pres.addSlide();
  s.background = { color: LIGHT };
  header(s, "System Architecture", "הילד מעלה הודעות לשרת; השרת מחלץ טקסט, מסווג, מנתב ושופט הקשר; וההורה מקבל התרעה ב-Web App וב-Gmail.");

  const chip = (x, y, w, t, col, tc) => { s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w, h: 0.58, fill: { color: col }, rectRadius: 0.06 }); s.addText(t, { x, y, w, h: 0.58, fontFace: "Arial", fontSize: 11.5, color: tc, align: "center", valign: "middle", bold: true }); };

  // Child client (LEFT)
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.4, y: 2.35, w: 2.2, h: 2.7, fill: { color: NAVY }, rectRadius: 0.1, shadow: mkShadow() });
  s.addText("Child Client", { x: 0.4, y: 2.46, w: 2.2, h: 0.4, fontFace: HEAD, bold: true, fontSize: 14.5, color: WHITE, align: "center" });
  s.addText("Android · אפליקציית הילד", heb({ x: 0.45, y: 2.83, w: 2.1, h: 0.35, fontSize: 10, color: ICE, align: "center" }));
  chip(0.55, 3.3, 1.9, "Text capture", WHITE, NAVY);
  chip(0.55, 4.05, 1.9, "Screenshots", WHITE, NAVY);

  // Server panel (CENTER)
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 3.3, y: 2.0, w: 6.7, h: 3.45, fill: { color: WHITE }, line: { color: TEAL, width: 2 }, rectRadius: 0.06, shadow: mkShadow() });
  s.addText("Server — FastAPI", { x: 3.5, y: 2.08, w: 6.3, h: 0.45, fontFace: HEAD, bold: true, fontSize: 15, color: TEAL, align: "left" });
  const mods = [
    { en: "OCR", he: "תמונה→טקסט", c: OCRC }, { en: "DictaBERT", he: "סיווג 5 מחלקות", c: NAVY },
    { en: "Triage", he: "ניתוב", c: TRIC }, { en: "Context\nAgent", he: "שיפוט הקשר", c: TEAL },
    { en: "Alert\nManager", he: "התרעה", c: ALRT },
  ];
  const bx0 = 3.5, bw = 1.12, bgap = 0.185, by = 2.95, bh = 1.5;
  mods.forEach((m, i) => {
    const x = bx0 + i * (bw + bgap);
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y: by, w: bw, h: bh, fill: { color: m.c }, rectRadius: 0.07, shadow: mkShadow() });
    s.addText(m.en, { x: x - 0.02, y: by + 0.2, w: bw + 0.04, h: 0.85, fontFace: "Arial", bold: true, fontSize: 12.5, color: WHITE, align: "center", valign: "middle" });
    s.addText(m.he, heb({ x: x - 0.05, y: by + bh - 0.42, w: bw + 0.1, h: 0.36, fontSize: 9.5, color: "EAF6F4", align: "center" }));
    if (i < mods.length - 1) arrowR(s, x + bw + 0.01, by + bh / 2, bgap - 0.02, MUTE, 2);
  });
  s.addText("Data flow:  capture → OCR → DictaBERT → Triage → Context Agent → Alert", { x: 3.5, y: 4.6, w: 6.3, h: 0.4, fontFace: HEAD, italic: true, fontSize: 10.5, color: MUTE, align: "center" });

  // Parent client (RIGHT)
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 10.7, y: 2.35, w: 2.2, h: 2.7, fill: { color: TEAL }, rectRadius: 0.1, shadow: mkShadow() });
  s.addText("Parent Client", { x: 10.7, y: 2.46, w: 2.2, h: 0.4, fontFace: HEAD, bold: true, fontSize: 14.5, color: WHITE, align: "center" });
  s.addText("צד ההורה", heb({ x: 10.75, y: 2.83, w: 2.1, h: 0.35, fontSize: 10, color: "E6F4F1", align: "center" }));
  chip(10.85, 3.3, 1.9, "Web App", WHITE, TEAL);
  chip(10.85, 4.05, 1.9, "Gmail (Email)", WHITE, TEAL);

  // big flow arrows (wider gaps now -> labels fit)
  arrowR(s, 2.64, 3.55, 0.62, NAVY, 3.5);
  s.addText("HTTPS", { x: 2.55, y: 3.14, w: 0.8, h: 0.3, fontFace: "Arial", fontSize: 9, color: MUTE, align: "center" });
  arrowR(s, 10.04, 3.55, 0.62, ALRT, 3.5);
  s.addText("alerts", { x: 9.98, y: 3.14, w: 0.75, h: 0.3, fontFace: "Arial", fontSize: 9, color: MUTE, align: "center" });

  s.addText("הפירוט המלא של מתי מופעל ה-Context Agent ומתי נשלחת התרעה — בשקופית הבאה (Decision Logic).",
    heb({ x: 0.6, y: 5.8, w: 12.1, h: 0.5, fontSize: 13, color: MUTE, align: "center" }));
  footer(s, 5);
}

// ============================================================ 6. CHILD & PARENT FLOWS
{
  const s = pres.addSlide();
  s.background = { color: LIGHT };
  header(s, "How It Works — Child & Parent Flows", "שתי הזרימות מקצה לקצה: צד הילד (לכידה ועיבוד) וצד ההורה (התאמה, קבלת התרעות ותגובה).");
  // Child flow (RIGHT card)
  const flowCard = (x, en, he, accent) => {
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y: 1.75, w: 5.95, h: 5.0, fill: { color: WHITE }, line: { color: "E2E8F0", width: 1 }, rectRadius: 0.07, shadow: mkShadow() });
    s.addShape(pres.shapes.RECTANGLE, { x, y: 1.75, w: 5.95, h: 0.62, fill: { color: accent } });
    s.addText(en, { x: x + 0.25, y: 1.77, w: 5.45, h: 0.58, fontFace: HEAD, bold: true, fontSize: 17, color: WHITE, align: "left", valign: "middle" });
    s.addText(he, heb({ x: x + 0.25, y: 1.77, w: 5.45, h: 0.58, fontSize: 12, color: "EAF6F4", align: "right", valign: "middle" }));
  };
  flowCard(6.85, "Child Flow", "זרימת הילד", NAVY);
  bulletsRich(s, [
    { md: "ה-**Child App** לוכד טקסט (**Accessibility**) וצילומי מסך" },
    { md: "**Pre-Filter** מקומי שומר רק עברית (פרטיות + דדופ)" },
    { md: "העלאה מוצפנת לשרת ב-**HTTPS**" },
    { md: "**OCR** (**Tesseract**) מחלץ טקסט מתמונות" },
    { md: "**DictaBERT** מסווג ל-5 מחלקות (**context-blind**)" },
    { md: "**Triage** מנתב; גבול/אלימות → **Context Agent**" },
    { md: "**Context Agent** (**LLM**) קורא 5 תורים ושופט הקשר" },
    { md: "**Alert Manager** מסמן מצב פוגעני" },
  ], { x: 7.05, y: 2.55, w: 5.55, gap: 7, fontSize: 14, numbered: true, marker: NAVY });
  flowCard(0.5, "Parent Flow", "זרימת ההורה", TEAL);
  bulletsRich(s, [
    { md: "ההורה נרשם ב-**Web App** (**Dashboard**)" },
    { md: "קוד התאמה (**OTP**) נשלח ב-**Gmail**" },
    { md: "ההורה מזין את הקוד באפליקציית הילד → **paired**" },
    { md: "**Alert Manager** שולח התרעות ב-**Gmail** + ל-**Web App**" },
    { md: "ההורה סוקר ב-**Web App** ומגיב (**ack / label / severity**)" },
    { md: "התיוגים חוזרים כנתוני אימון (**human-in-the-loop**)" },
  ], { x: 0.7, y: 2.6, w: 5.55, gap: 11, fontSize: 14, numbered: true, marker: TEAL });
  footer(s, 6);
}

// ============================================================ 7. DECISION LOGIC (triage / CA / alert)
{
  const s = pres.addSlide();
  s.background = { color: LIGHT };
  header(s, "Decision Logic — 5 Classes → Triage → Context Agent → Alert",
    "ה-DictaBERT מפיק אחת מ-5 מחלקות עם רמת ודאות; ה-Triage מחליט אם להשתיק, להתריע ישירות, או להעביר ל-Context Agent.");
  const TH = (t) => ({ text: t, options: { fill: { color: NAVY }, color: WHITE, bold: true, fontFace: HEAD, fontSize: 13, align: "center", valign: "middle" } });
  const tc = (t, col = INK, fill = WHITE, bold = false) => ({ text: t, options: { color: col, fill: { color: fill }, bold, fontFace: "Arial", fontSize: 12, align: "center", valign: "middle" } });
  const rows = [
    [TH("Classifier output"), TH("Triage decision"), TH("Context Agent?"), TH("Outcome")],
    [tc("prob_offensive ≤ 0.3", INK, "EEF3F8", true), tc("Silent", "5B6B7B"), tc("No", MUTE), tc("No alert", "5B6B7B")],
    [tc("abusive / hate · prob ≥ 0.7", INK, "EEF3F8", true), tc("Direct alert", "B23A2E", "FBEAE7"), tc("No", MUTE), tc("Alert sent", "B23A2E", "FBEAE7", true)],
    [tc("pornographic (any prob)", INK, "EEF3F8", true), tc("Direct alert", "B23A2E", "FBEAE7"), tc("No", MUTE), tc("Alert sent — always", "B23A2E", "FBEAE7", true)],
    [tc("violence (any prob)", INK, "EEF3F8", true), tc("Escalate", "8A4B00", "FFF3E6"), tc("Yes — always", "0E7A52", "E6F7EF", true), tc("Alert if CA confirms threat", "8A4B00", "FFF3E6")],
    [tc("borderline · prob 0.3–0.7", INK, "EEF3F8", true), tc("Escalate", "8A4B00", "FFF3E6"), tc("Yes", "0E7A52", "E6F7EF", true), tc("CA decides → alert / silent", "8A4B00", "FFF3E6")],
  ];
  s.addTable(rows, { x: 0.7, y: 1.95, w: 12.0, colW: [3.5, 2.6, 2.4, 3.5], rowH: 0.5, border: { pt: 0.75, color: "D6DEE7" }, valign: "middle" });
  bulletsRich(s, [
    { md: "**5 classes** — ה-DictaBERT מפיק אחת מ-5 מחלקות עם **prob_offensive** (רמת ודאות פוגענית)" },
    { md: "**Triage** — ודאות נמוכה → שקט · ודאות גבוהה → התרעה ישירה · ביניים → **Context Agent**" },
    { md: "**Context Agent triggers** — במקרי גבול (**0.3–0.7**) ותמיד ב-**violence**" },
    { md: "**Alert sent** — בהתרעה ישירה (**abusive/hate** ודאי או **pornographic**), או כש-**Context Agent** מאשר פגיעה בהקשר", b: true, c: INK },
  ], { x: 0.85, y: 5.2, w: 11.95, gap: 8, fontSize: 14.5 });
  footer(s, 7);
}

// ============================================================ 8. RESEARCH QUESTION -> ARCHITECTURE
{
  const s = pres.addSlide();
  s.background = { color: LIGHT };
  header(s, "Research Question → Maps to the Architecture", "אותה מערכת בדיוק נבחנת בשני תנאים — עם הקשר ובלעדיו — כדי לבודד את תרומת ההקשר השיחתי.");
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.7, y: 1.6, w: 12.0, h: 1.65, fill: { color: NAVY }, rectRadius: 0.1, shadow: mkShadow() });
  s.addText([
    { text: "האם הוספת ", options: heb({ fontSize: 19, color: WHITE }) },
    { text: "conversational context", options: heb({ fontSize: 19, color: RESULT_D, bold: true }) },
    { text: " מפחיתה את שיעור ה-", options: heb({ fontSize: 19, color: WHITE }) },
    { text: "false-positives", options: heb({ fontSize: 19, color: RESULT_D, bold: true }) },
    { text: " בסיווג בריונות בעברית — מבלי לפגוע ב-", options: heb({ fontSize: 19, color: WHITE }) },
    { text: "recall", options: heb({ fontSize: 19, color: RESULT_D, bold: true, breakLine: true }) },
    { text: "(אותה מערכת בדיוק, מתג אחד מתהפך)", options: heb({ fontSize: 13, color: "9FB3C8" }) },
  ], { x: 1.0, y: 1.78, w: 11.4, h: 1.3, valign: "middle" });

  const arm = (x, title, col, modules, note) => {
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y: 3.6, w: 5.85, h: 2.55, fill: { color: WHITE }, line: { color: col, width: 2 }, rectRadius: 0.08, shadow: mkShadow() });
    s.addShape(pres.shapes.RECTANGLE, { x, y: 3.6, w: 5.85, h: 0.62, fill: { color: col } });
    s.addText(title, { x: x + 0.2, y: 3.62, w: 5.45, h: 0.58, fontFace: HEAD, bold: true, fontSize: 16, color: WHITE, align: "left", valign: "middle" });
    let mx = x + 0.35;
    modules.forEach((m, i) => {
      s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: mx, y: 4.45, w: 1.7, h: 0.7, fill: { color: m.c }, rectRadius: 0.06 });
      s.addText(m.t, { x: mx, y: 4.45, w: 1.7, h: 0.7, fontFace: "Arial", bold: true, fontSize: 11.5, color: WHITE, align: "center", valign: "middle" });
      mx += 1.7;
      if (i < modules.length - 1) { arrowR(s, mx, 4.8, 0.35, MUTE, 2); mx += 0.35; }
    });
    s.addText(note, heb({ x: x + 0.25, y: 5.4, w: 5.4, h: 0.65, fontSize: 13, color: SLATE, valign: "top" }));
  };
  arm(0.7, "context-aware  (treatment)", TEAL,
    [{ t: "DictaBERT", c: NAVY }, { t: "Context Agent", c: TEAL }],
    "קורא את 5 התורים הקודמים ושופט אם ההודעה פוגענית לאור השיחה.");
  arm(6.85, "context-blind  (baseline)", MUTE,
    [{ t: "DictaBERT", c: NAVY }],
    "קורא הודעה בודדת בלבד, ללא זיכרון של השיחה.");
  s.addText([
    { text: "החיבור לארכיטקטורה: ", options: heb({ fontSize: 14, color: NAVY, bold: true }) },
    { text: "Context Agent", options: heb({ fontSize: 14, color: RESULT, bold: true }) },
    { text: " הוא בדיוק זרוע ה-treatment. מתג ", options: heb({ fontSize: 14, color: SLATE }) },
    { text: "CONTEXT_AGENT_ENABLED", options: heb({ fontSize: 14, color: NAVY, bold: true }) },
    { text: " = false/true מחליף בין שתי הזרועות.", options: heb({ fontSize: 14, color: SLATE }) },
  ], { x: 0.7, y: 6.35, w: 12.0, h: 0.5, align: "center", valign: "middle" });
  footer(s, 8);
}

// ============================================================ 9. WHY DICTABERT
{
  const s = pres.addSlide();
  s.background = { color: LIGHT };
  header(s, "Why DictaBERT? (Model Choice)", "בחרנו במודל עברי ייעודי, מהיר ומקומי — ולא ב-LLM כללי או במודל מדף — מהסיבות הבאות.");
  const H = (t) => ({ text: t, options: { fill: { color: NAVY }, color: WHITE, bold: true, fontFace: HEAD, fontSize: 13, align: "center", valign: "middle" } });
  const cell = (t, c = INK, fill = WHITE, bold = false) => ({ text: t, options: { color: c, fill: { color: fill }, bold, fontFace: "Arial", fontSize: 12, align: "center", valign: "middle" } });
  const rows = [
    [H("Criterion"), H("DictaBERT  (chosen)"), H("General LLM"), H("Ollama (off-the-shelf)")],
    [cell("Hebrew-native", INK, "EEF3F8", true), cell("✓ Yes", "0E7A52", "E6F7EF", true), cell("Partial", "8A6D00", "FFF7DC"), cell("✗ No", "B23A2E", "FBEAE7")],
    [cell("Accuracy (macro-F1)", INK, "EEF3F8", true), cell("0.836", "0E7A52", "E6F7EF", true), cell("—", MUTE), cell("0.373", "B23A2E", "FBEAE7")],
    [cell("Speed / latency", INK, "EEF3F8", true), cell("Very fast", "0E7A52", "E6F7EF", true), cell("Slow", "8A6D00", "FFF7DC"), cell("Slow", "8A6D00", "FFF7DC")],
    [cell("Cost", INK, "EEF3F8", true), cell("Free · local", "0E7A52", "E6F7EF", true), cell("$$ per call", "B23A2E", "FBEAE7"), cell("Free · local", "0E7A52", "E6F7EF")],
    [cell("Privacy (on-prem)", INK, "EEF3F8", true), cell("✓", "0E7A52", "E6F7EF", true), cell("✗ cloud", "B23A2E", "FBEAE7"), cell("✓", "0E7A52", "E6F7EF")],
    [cell("Fits 'always-on' use", INK, "EEF3F8", true), cell("✓", "0E7A52", "E6F7EF", true), cell("✗ too costly", "B23A2E", "FBEAE7"), cell("✗ low quality", "B23A2E", "FBEAE7")],
  ];
  s.addTable(rows, { x: 0.7, y: 1.75, w: 8.0, colW: [2.3, 2.0, 1.85, 1.85], rowH: 0.46, border: { pt: 0.75, color: "D6DEE7" }, valign: "middle" });
  bulletsRich(s, [
    { md: "**Hebrew-native** — **BERT** עברי שעבר אימון-קדם על עברית; מבין מורפולוגיה שמודלים אנגליים מפספסים" },
    { md: "**Accuracy** — macro-F1 [[0.836]] מול [[0.373]] של **Ollama** על אותו מבחן" },
    { md: "**Speed** — פי [[424]] מהיר; מתאים לסריקה שוטפת בזמן אמת" },
    { md: "**Privacy** — ריצה מקומית, ללא ענן; נתוני הילדים אינם יוצאים החוצה" },
    { md: "**Low cost** — אינפרנס מקומי חינמי, מול תשלום לכל קריאת **LLM**" },
    { md: "**Right tool per job** — **DictaBERT** = גלאי מהיר; **LLM Context Agent** = רק למקרי גבול", b: true, c: INK },
  ], { x: 9.0, y: 1.95, w: 3.85, gap: 10, fontSize: 14 });
  footer(s, 9);
}

// ============================================================ 10. DATASET
{
  const s = pres.addSlide();
  s.background = { color: LIGHT };
  header(s, "Training Data", "המודל אומן על תערובת של עברית אמיתית ונתונים סינתטיים, והוערך על נתונים אמיתיים בלבד.");
  s.addImage({ path: A("assets/dataset_classes.png"), x: 0.45, y: 1.7, sizing: { type: "contain", w: 4.6, h: 2.5 } });
  s.addImage({ path: A("assets/dataset_sources.png"), x: 0.35, y: 4.35, sizing: { type: "contain", w: 5.0, h: 2.65 } });
  bulletsRich(s, [
    { md: "היקף: **train** [[7,974]] · **validation** [[888]] · **test** [[445]]", b: true, c: INK },
    "5 מחלקות: **non-offensive · abusive · hate · violence · pornographic**",
    "מקורות: [[~57%]] עברית אמיתית (**SinaLab + textDetox**), [[~36%]] סינתטי (**Gemini**), [[~7%]] תרגום (**Jigsaw**)",
    "התפלגות מודעת-שכיחות: [[~48%]] non-offensive ב-train, [[~70%]] בהערכה — כמו בעולם האמיתי",
    "עיקרון מנחה: **train-on-synthetic / eval-on-real**",
    { md: "הערה כנה: חלק ממחלקות המיעוט בהערכה סינתטיות (**pornographic** — 100%) → מספרי המיעוט אופטימיים", s: 13, c: MUTE },
  ], { x: 5.3, y: 1.8, w: 7.4, gap: 12, fontSize: 16 });
  footer(s, 10);
}

// ============================================================ 11. RESULTS — MODEL QUALITY
{
  const s = pres.addSlide();
  s.background = { color: LIGHT };
  header(s, "Results — Model Quality (DictaBERT)", "המסווג שאימנו עובר את כל ספי הסף, מכויל היטב, ומנצח מודל מדף בפער גדול.");
  s.addImage({ path: A("assets/model_quality.png"), x: 0.4, y: 1.7, sizing: { type: "contain", w: 8.6, h: 4.0 } });
  statCard(s, 9.3, 1.85, 1.7, "0.836", "macro-F1", RESULT);
  statCard(s, 11.1, 1.85, 1.7, "0.034", "ECE (calibration)", TEAL);
  bulletsRich(s, [
    { md: "**DictaBERT** עברי שאומן על-ידינו ל-5 מחלקות", b: true, c: INK },
    "פי [[2.4]] מדויק ופי [[424]] מהיר מ-**Ollama**: [[0.836]] מול [[0.373]]",
    "**Calibration** טוב (**ECE** [[0.034]]): הביטחון של המודל כן — לא מגזים ולא ממעיט",
    { md: "זוהי זרוע ה-**context-blind** של הניסוי — וגם המסווג בייצור", s: 13, c: MUTE },
  ], { x: 9.15, y: 3.55, w: 3.75, gap: 11, fontSize: 14.5 });
  // mini glossary strip
  s.addText([
    { text: "macro-F1", options: { fontFace: "Arial", bold: true, color: NAVY, fontSize: 11 } },
    { text: " = average accuracy across all 5 classes (higher = better).   ", options: { fontFace: "Arial", color: SLATE, fontSize: 11 } },
    { text: "ECE", options: { fontFace: "Arial", bold: true, color: NAVY, fontSize: 11 } },
    { text: " = how honest the model's confidence is (lower = better).", options: { fontFace: "Arial", color: SLATE, fontSize: 11 } },
  ], { x: 0.5, y: 6.25, w: 8.6, h: 0.4, align: "center" });
  footer(s, 11);
}

// ============================================================ 12. RESULTS — CONTEXT
{
  const s = pres.addSlide();
  s.background = { color: LIGHT };
  header(s, "Results — Conversational Context", "בשני ניסויים, הוספת הקשר שיחתי מפחיתה התרעות-שווא ותופסת פגיעה נסתרת — לעומת סיווג ההודעה במנותק.");
  s.addImage({ path: A("docs/research_question/plots/contribution_two_axes.png"), x: 0.4, y: 1.65, sizing: { type: "contain", w: 8.4, h: 4.2 } });
  bulletsRich(s, [
    { md: "**Experiment 1** (61 שיחות): **false-alarm rate** [[55.9%]] → [[26.5%]]", b: true, c: INK },
    { md: "ירידה של [[29.4]] נקודות · **p = 0.002** (**McNemar**) — מובהק", s: 14 },
    { md: "**Experiment 2** (143 שיחות): **harm recall** [[58.9%]] → [[82.1%]]", b: true, c: INK },
    { md: "**veiled threats** [[0% → 100%]] עם הקשר", s: 14 },
    "ההתרעה על המצב הפוגעני — לא על כל מילה גסה",
    { md: "סטטוס: **MVP / feasibility** — נתונים סינתטיים/מתויגים-עצמית", s: 12, c: MUTE },
  ], { x: 8.95, y: 1.75, w: 3.9, gap: 10, fontSize: 14.5 });
  s.addText([
    { text: "FPR", options: { fontFace: "Arial", bold: true, color: NAVY, fontSize: 11 } },
    { text: " = false-alarm rate (lower better).   ", options: { fontFace: "Arial", color: SLATE, fontSize: 11 } },
    { text: "recall", options: { fontFace: "Arial", bold: true, color: NAVY, fontSize: 11 } },
    { text: " = % of real harm caught.   ", options: { fontFace: "Arial", color: SLATE, fontSize: 11 } },
    { text: "p-value", options: { fontFace: "Arial", bold: true, color: NAVY, fontSize: 11 } },
    { text: " < 0.05 = the result is not luck.", options: { fontFace: "Arial", color: SLATE, fontSize: 11 } },
  ], { x: 0.4, y: 6.15, w: 8.4, h: 0.4, align: "center" });
  footer(s, 12);
}

// ============================================================ 13. CONCLUSIONS
{
  const s = pres.addSlide();
  s.background = { color: NAVY };
  s.addShape(pres.shapes.OVAL, { x: -2.0, y: 4.4, w: 6, h: 6, fill: { color: TEAL, transparency: 88 } });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.6, y: 0.62, w: 0.14, h: 0.9, fill: { color: MINT } });
  s.addText("Conclusions", { x: 0.88, y: 0.5, w: 11.7, h: 0.8, fontFace: HEAD, bold: true, fontSize: 38, color: WHITE, align: "left" });
  s.addText("מסקנות", heb({ x: 0.88, y: 1.32, w: 11.7, h: 0.4, fontSize: 14, color: "9FB3C8", align: "left" }));
  bulletsRich(s, [
    { md: "ניתוח **conversational context** משפר מהותית את דיוק הסיווג בעברית", b: true, c: WHITE },
    { md: "ההקשר עוזר בשני הצירים: מפחית **false alarms** וגם תופס פגיעה נסתרת", c: ICE },
    { md: "הגדרת היעד הנכונה היא המצב הפוגעני — לא המילה הבודדת", c: ICE },
    { md: "מערכת מודולרית עובדת מקצה-לקצה ומשמשת גם כמעבדת ניסוי הניתנת לשחזור", c: ICE },
    { md: "סטטוס כן: **MVP** — הכיוון והמובהקות חזקים; הגודל המדויק דורש **gold-set** אמיתי", c: GOLD, b: true },
  ], { x: 0.9, y: 2.0, w: 11.6, gap: 15, fontSize: 19, dark: true });
  footer(s, 13, true);
}

// ============================================================ 14. FUTURE WORK
{
  const s = pres.addSlide();
  s.background = { color: LIGHT };
  header(s, "Future Work", "הכיוונים שיהפכו את הוכחת ההיתכנות למחקר בר-פרסום ולמוצר בר-פריסה.");
  bulletsRich(s, [
    { md: "בניית **gold-set** אמיתי, מאונוטט ידנית (**Cohen's κ**) → מספר תוצאה אמין לפרסום", b: true, c: INK },
    "פריסת **pilot** מחקרי בשיתוף מוסדות חינוך ורשויות מקומיות",
    "תמיכה בפלטפורמות נוספות (**Telegram, TikTok**) ו-**on-device** לפרטיות מוגברת",
    "סיווג **multilingual** — אנגלית ורוסית בהקשר הישראלי",
    "**E6**: השוואת **selective context-agent** מול **naive concatenation** — תרומה לספרות (**Pavlopoulos 2020**)",
  ], { x: 4.7, y: 1.9, w: 8.05, gap: 16, fontSize: 18 });
  const rchip = (y, n, label, col) => {
    s.addShape(pres.shapes.OVAL, { x: 0.85, y, w: 0.72, h: 0.72, fill: { color: col }, shadow: mkShadow() });
    s.addText(n, { x: 0.85, y, w: 0.72, h: 0.72, fontFace: HEAD, bold: true, fontSize: 18, color: WHITE, align: "center", valign: "middle" });
    s.addText(label, heb({ x: 1.75, y, w: 2.7, h: 0.72, fontSize: 14, bold: true, color: SLATE, valign: "middle" }));
  };
  rchip(2.0, "1", "gold-set אמיתי", MINT);
  rchip(3.0, "2", "פיילוט בבתי-ספר", TEAL);
  rchip(4.0, "3", "פלטפורמות נוספות", OCRC);
  rchip(5.0, "4", "multilingual", GOLD);
  rchip(6.0, "5", "תרומה לספרות", CORAL);
  footer(s, 14);
}

const OUT = A("docs/presentation/Shomer_AI_presentation.pptx");
pres.writeFile({ fileName: OUT }).then(() => console.log("WROTE " + OUT));
