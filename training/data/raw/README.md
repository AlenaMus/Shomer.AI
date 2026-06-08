# Stage-0 Data Inventory — SinaLab Offensive-Hebrew (real, verified 2026-06-07)

Reconnaissance results from `training/scripts/fetch_inspect_sinalab.py` +
`fetch_inspect` of `AllData_OffensiveHebrew.csv`. **These numbers override the
assumed counts in `docs/concepts/dictabert_classifier_architecture.md` §9**, which
were aspirational, not measured.

## Where the data actually lives

- **NOT** an HF dataset repo — `load_dataset("SinaLab/Offensive-Hebrew")` 404s
  (that HF repo is a *model*, not a dataset).
- Real source: GitHub **`SinaLab/OffensiveHebrew`**, branch `main`, `data/`:
  | File | Rows | What it is |
  |---|---|---|
  | `AllData_OffensiveHebrew.csv` | 15,996 | **canonical full corpus** with fine-grained `Label` |
  | `train.csv` / `test.csv` / `val.csv` | 1750 / 500 / 250 | a **binary** (`Positive`/`Negative`) split — NOT 5-class |
  | `none-offiensive.csv` *(sic — repo typo)* | 15,996 | non-offensive tweets, `Tweet`/`Label` cols |
- Downloaded to `training/data/raw/sinalab/`.

## The real label encoding (AllData)

Columns: `TweetNo, Label, Target, Topic, Phrase, TweetText`.
The 5-class signal is a **single free-text `Label` column** — messy, not 4 binary columns:
- Mixed case: `Hate`/`hate`, `Violence`/`violence`
- Typos: `Porographic` (→ pornographic)
- Extra class: `racism`/`racist` (mapped → `hate`)
- Comma multi-label: `Hate, violence`, `Hate, Abusive` → apply §9 severity `violence > hate > pornographic > abusive`
- `NOT` → `non_offensive`; blank/`nan` (113 rows) → dropped

## Real per-class counts (deduped on TweetText, §9 mapping)

| Class | Real examples | Note |
|---|---|---|
| `non_offensive` | 14,298 | large surplus → will down-sample |
| `hate` | 624 | incl. `racism` merged; enough to baseline |
| `violence` | 453 | enough to baseline |
| `abusive` | **119** | too thin for a real-only val/test |
| `pornographic` | **4** | effectively absent — must be translated/synthesized |
| **offensive total** | **1,200** | matches the docs' aggregate, but brutally skewed |

## Impact on the plan (vs. approved plan + §9)

1. **`pornographic` (4) cannot have a "baseline"** — the D2 "baseline first, expand
   where weak" strategy doesn't apply to it; it needs translation+synthesis from the start.
2. **`abusive` (119) is borderline** — 2× EDA → ~238, still thin for a stable real-only test.
3. **§9 "val/test = SinaLab-real only" is impossible for `pornographic`** (4 total) and
   shaky for `abusive`. The honest options: down-scope the gate to the 3 well-populated
   classes for the *baseline*, or allow synthetic/translated examples into val/test for the
   two rare classes (with a clear caveat in the thesis). ← user decision pending.
4. The new `prepare_data_dictabert.py` must parse the **`Label` text field**, not 4 binary
   columns — the legacy `prepare_data.py` `row_to_label()` does NOT apply here.
