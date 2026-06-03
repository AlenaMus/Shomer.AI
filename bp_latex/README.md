# Shomer.AI — Business Plan (LaTeX)

A 6-section Hebrew/RTL business plan for the Meeting-3 (2026-05-28) mentor review.

## How to compile (Overleaf — recommended)

1. Create a new Overleaf project and **upload `business_plan.tex`** (it is self-contained — no images, no `.bib`).
2. In Overleaf: **Menu → Settings → Compiler → set to `XeLaTeX`** (NOT pdfLaTeX).
3. Click **Recompile**. Nothing else to install — the Hebrew font ships with Overleaf's TeX Live.

> Local compile (if you ever install TeX Live): `xelatex business_plan.tex`. Requires the Culmus Hebrew fonts (`tlmgr install culmus`, or `apt-get install culmus` on Debian/Ubuntu).

## Preamble / font notes

- **Engine:** XeLaTeX with `polyglossia` (`\setdefaultlanguage{hebrew}` + `\setotherlanguage{english}`), `bidi` (pulled in automatically by polyglossia for Hebrew), and `fontspec`.
- **Hebrew main font:** `David CLM` (Culmus family) — bundled with Overleaf's TeX Live, so it compiles with zero setup.
- **Fallbacks** if `David CLM` is missing on some distribution (edit the `\setmainfont` line near the top of the `.tex`):
  - `Frank Ruehl CLM` (Culmus serif)
  - `Nachlieli CLM` (Culmus sans)
  - `Miriam CLM`
- Latin/English terms, numbers and `$`-prices inside RTL text are wrapped with a `\en{...}` helper (`\textenglish`) so they render LTR correctly.

### LaTeX risk to flag
- **Font availability — now auto-handled.** The `\setmainfont` line uses a `\IfFontExistsTF` fallback chain, so it picks the first available of: `David CLM` (Overleaf/TeX Live Culmus) → `David` (built-in Windows Hebrew font) → `Frank Ruehl CLM` → `Arial`. This means the `.tex` compiles **both** on Overleaf **and** on a stock Windows + MiKTeX setup with no manual edits. No other package in the preamble is exotic (`longtable`, `booktabs`, `xcolor`, `colortbl`, `enumitem`, `hyperref`, `geometry` are all standard).
- **MiKTeX (local Windows) note:** set the compiler/engine to **XeLaTeX**, and allow MiKTeX to install missing packages on first compile (`polyglossia`, `bidi` pull in automatically). If a prompt blocks the build, pre-enable it: `initexmf --set-config-value "[MPM]AutoInstall=1"`.

## Numbers: verified vs. still needing a source

### Verified via web (early/May 2026)
- **Global parental-control market:** ~$1.55B (2025) → ~$1.74B (2026), CAGR ~9.8%–12.25%. (Global Growth Insights; Future Market Insights.) — corroborates the Proposal's ~$1.6B / 9.4%.
- **Israel families:** ~2.25M families, ~half are two-parent households with at least one child under 17 (CBS 2022, via JNS). Supports the Proposal's ~1.5M households as a reasonable order of magnitude.
- **Bark price:** $29/yr (1 device), $95.90/yr (3 devices).
- **Qustodio price:** free tier / $54.95/yr (5 devices) / $99.95/yr.
- **Canopy price:** $7.99/mo (3 devices, billed annually) up to $9.99/mo (10 devices).
- **Claude Haiku 4.5 API:** $1 input / $5 output per 1M tokens.
- **GPT-4o-mini API:** $0.15 input / $0.60 output per 1M tokens.
- **Gemini 2.5 Flash API:** $0.30 input / $2.50 output per 1M tokens (note: multiple Flash variants exist — confirm the exact one chosen).

### Still tagged `[למקור]` / "טעון אימות" — fix before the final version
1. **SAM precise cohort** — exact count of Israeli households with children **aged 6–16 who own a smartphone** (the ~1.5M figure is the broader "children under 17" proxy, not the precise 6–16 cohort). Needs a CBS/Statista pull.
2. **SOM (5,000 users, ARPU ₪40/mo)** — internal business target, **not** a sourced market forecast. Needs justification against Israeli market penetration data, or keep labelled as an illustrative scenario.
3. **Keepers price** — only the 14-day free trial is confirmed; the exact monthly/annual subscription price is unverified.
4. **Bosco price** — no public pricing found; tagged `[למקור]`.
5. **Token-economics usage assumptions** — 30 messages/user/day, 15% edge-case rate, ~1,000 tokens/call, agent_multiplier ≈ 2. These drive the worked example and are **illustrative assumptions needing empirical calibration**, not measured values. (The token *prices* themselves are verified; the *volumes* are not.)
6. **Gemini Flash variant** — pricing is for Gemini 2.5 Flash; confirm which Flash version is actually intended.

## Content map (6 mandatory sections, Dr. Segal's structure)
1. Executive Summary — problem / solution / user / value.
2. Market — TAM / SAM / SOM, every number footnoted or `[למקור]`.
3. Competitors — Bark, Qustodio, Canopy, Keepers, Bosco + Shomer.AI; Price-vs-Value table.
4. USP — one-sentence statement + four pillars (Hebrew-first, on-device, multimodal, context+explainability).
5. Revenue Model — freemium + SOM illustrative scenario (₪2.4M/yr gross).
6. Cost Structure — token-economics formula, hybrid cost advantage, worked example, model-selection matrix.
