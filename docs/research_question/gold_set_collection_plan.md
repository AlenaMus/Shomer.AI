# Gold-Set Collection Plan — the real-data experiment

**Purpose:** a concrete, executable checklist for building the **real Hebrew conversational gold
set** that turns the MVP result into a publishable number. Read this, decide if the data is
reachable, and if yes → run the existing harness (`scripts/eval_context_fp.py`).

**Status:** plan only (2026-06-12). The apparatus, runner, statistics, and pre-registered
thresholds already exist — **this data set is the only remaining blocker.**
**Companion:** `context_fp_test_plan.md` (full design) · `plan-docs/decisions/context-fp-experiment.decision.md`.

---

## 0. What "done" looks like

A single file `data/gold/context_gold_v2.jsonl` with **~150–200 real Hebrew conversation items**,
each double-annotated, composed by the group plan in §2. Feed it to the harness → it prints the
paired FPR/recall tables + McNemar p-value + the per-category breakdown. **No new code.**

> **Honesty rule that drives everything:** *train on synthetic, evaluate on real.* Synthetic /
> Gemini-generated items may **seed** the categories but **must not enter the gold set** — that is
> the one rule a reviewer will attack, so it is non-negotiable (decision D-CFP-4 / D-CFP-7).

---

## 1. Reality check — can you actually get this data? (decide first)

Before committing, sanity-check each source. **You do NOT need all of them — you need ~150–200
items total from whichever are reachable.**

| Source | What it gives | Reachable? (you decide) | Effort |
|---|---|---|---|
| **Your own / consenting friends' WhatsApp** (scrubbed) | benign banter + sarcasm (Category A & C-benign) | likely ✅ | Low |
| **Public Hebrew teen forums / Telegram groups** | real flip-cases, pile-ons (A & B) | maybe | Medium |
| **Screenshots you already have** (`offensive.png`, `cc.png`, `xx.png`, humor examples) | the v1 core (34 items, already done) | ✅ done | — |
| **Reddit r/Israel, news comment threads** | escalation / coded threats (B) | maybe | Medium |
| **Gemini-synthesized conversations** | scaffolding only — **NOT for the gold set** | ✅ but train-only | Low |

**Decision gate:** if you can realistically reach **~100+ real items** (v1's 34 + ~70 more),
the experiment is worth running. If you can only get ~50, run it but **report confidence
intervals, not a hard pass/fail** (D-CFP-3 revisit clause already allows this).

---

## 2. The group composition (what to collect, in %)

Target ~180 items. Each group proves a *specific* clause of the research question.

| Group | % | n (~180) | Gold label | Proves |
|---|---|---|---|---|
| **A — context repairs a false alarm** | **45%** | ~80 | benign | the false-alarm drop (the headline) |
| **B — context reveals hidden harm** | **25%** | ~45 | offensive | recall is not hurt / harm is caught |
| **C — controls (call is the same either way)** | **30%** | ~55 | half/half | we didn't just desensitize everything |

This gives **~60% benign / 40% offensive** → a thick-enough false-alarm denominator (the
historically thinnest slice).

### Sub-breakdown (collect across these so you can slice results)

**A (45%) — looks offensive ALONE, benign IN CONTEXT:**
- Friendly teasing / banter (~12%) · Sarcasm / irony (~10%) · Gaming trash-talk (~8%) ·
  Reclaimed in-group slang (~7%) · Quoting someone else's words (~8%)

**B (25%) — looks benign ALONE, harmful IN CONTEXT:**
- Veiled / coded threat (~8%) ← *highest value (Exp 2: 0%→100%)* · Escalating pile-on (~7%) ·
  Conditional resolved by history (~5%) · Victim disclosure — child reporting being bullied (~5%)

**C (30%) — invariant controls:**
- C-benign: ordinary chat + self-deprecation (~15%) · C-offensive: unambiguous abuse (~10%) ·
  C-always-alert: explicit porn/violence (~5%)

### The one element that matters most: contrastive pairs
Build **~10–15 matched pairs** — the *same surface sentence* once in group A (benign context) and
once in group B (harmful context). A context-blind model literally cannot tell them apart → this is
the single strongest proof that **context, not vocabulary, carries the signal.**

---

## 3. Item schema (one JSON line per item)

```json
{
  "id": "GV2-001",
  "category": "A",
  "subtype": "sarcasm",
  "history": ["prev turn 1", "prev turn 2", "..."],
  "message": "the message being classified",
  "gold_label": "non_offensive",
  "gold_is_offensive": false,
  "isolated_appearance": "offensive",
  "rationale_he": "למה זה תמים בהקשר",
  "rationale_en": "why it's benign in context",
  "source": "whatsapp_scrubbed",
  "annotator_a": "non_offensive",
  "annotator_b": "non_offensive",
  "tags": ["#banter"]
}
```
**Rule:** an item only counts as Category A if a human (and ideally the blind model) reads it as
offensive **in isolation** but benign **in context** — `isolated_appearance` records that.

---

## 4. Procedure (step by step)

1. **Collect raw snippets** from the reachable sources in §1, sorted into A/B/C buckets toward the §2 %s.
2. **Scrub PII** — names → `[שם]`, phone/handles removed, no identifying detail. Minors: extra care,
   public sources only (ethics, §6).
3. **Write each item** in the §3 schema (history + message + the two rationale lines).
4. **Double-annotate** — two people independently label `gold_is_offensive` AND `isolated_appearance`.
   - Compute **Cohen's κ** (target ≥ 0.6). κ itself is a reportable thesis result.
   - Resolve disagreements by discussion; drop items that can't reach agreement.
5. **Save** to `data/gold/context_gold_v2.jsonl`.
6. **Run the harness** (no code to write):
   ```powershell
   python scripts/eval_context_fp.py --gold data/gold/context_gold_v2.jsonl --k 5
   python scripts/viz_context_fp.py            # regenerates all result graphs
   ```
7. **Read the output** — it prints FPR/recall per arm, McNemar p, and the per-category breakdown,
   and fills the headline thesis sentence automatically.

---

## 5. Pre-registered thresholds (locked — do NOT change after the run starts)

| Symbol | Meaning | Value |
|---|---|---|
| **X** | min false-alarm drop to claim success | ≥ 10 pp absolute (or ≥ 30% relative) |
| **Y** | max tolerated recall loss | ≤ 3 pp |
| **k** | prior turns shown | 5 |
| **α** | significance level | 0.05, two-sided |
| **test** | significance test | McNemar (exact if discordant pairs < 25) |
| **κ** | min annotator agreement | ≥ 0.6 |

If the set lands < ~120 items → switch to **confidence intervals** instead of pass/fail (allowed).

---

## 6. Ethics (must be addressed in the thesis)

- **Public sources only** for anything not your own/consented chats.
- **Minors:** do not collect identifiable data; scrub aggressively; use only public material.
- **PII scrub** every item before it enters the file.
- State the data provenance + scrubbing method in the thesis methods section.

---

## 7. Effort estimate & go/no-go

| Phase | Effort | Note |
|---|---|---|
| Collect + scrub ~150 items | 2–4 days | the real work; depends on source reach |
| Double-annotate + κ | 1–2 days | needs a second annotator |
| Run + visualize | ~1 hour | harness already built |

**Go/no-go:** if §1 says you can reach ~100+ real items → **GO** (run it, report CIs if small).
If not → keep the MVP result as the headline, clearly labeled *feasibility*, and frame the real
gold set as immediate future work. Either way the project's claim stands; only the *magnitude's
precision* changes.

---

> **Trigger:** when `data/gold/context_gold_v2.jsonl` exists, run §4.6 — that is the entire
> "real experiment." Everything upstream of the data already works.
</content>
