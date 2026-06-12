# Context → False-Positive experiment — results

**Run:** 2026-06-11 12:43:09 · **gold:** `data/gold/context_mvp_combined.jsonl` (61 items) · **k:** 5 turns
**Classifier:** `v1.1-dictabert` · **LLM judge:** `gemini-2.5-flash` (fallback `haiku-4.5`)

Pre-registered (decision D-CFP-3): X≥10pp FPR drop, Y≤3pp recall loss, α=0.05, McNemar exact.

---

### F2 — prompt-level (history empty vs. populated) (SCIENTIFIC PRIMARY)

- Benign items: 34 · Offensive items: 27

| Metric | context-blind | context-aware | Δ | McNemar p |
|---|---|---|---|---|
| **FPR** | 0.0% | 2.9% | **−-2.9 pp** | 1.0000 |
| **Recall** | 33.3% | 48.1% | +14.8 pp | 0.1250 |

- FPR discordant pairs: blind-wrong/aware-right (the win) **c=0**, blind-right/aware-wrong (the cost) **b=1**
- Recall discordant pairs: c=4 (aware recovers), b=0 (aware misses)

- **H1 (ΔFPR ≥ 10pp & p<0.05):** ❌ not met
- **Recall non-inferiority (loss ≤ 3pp):** ✅ PASS

**ΔFPR by category** (proves H2 — the drop should concentrate in A):

| Cat | n (benign) | FPR blind | FPR aware | Δ |
|---|---|---|---|---|
| A repairs-FP | 23 | 0.0% | 4.3% | −-4.3 pp |
| C control | 11 | 0.0% | 0.0% | −0.0 pp |

**Recall by category** (proves the recall guard — B must stay high):

| Cat | n (offensive) | Recall blind | Recall aware | Δ |
|---|---|---|---|---|
| B reveals-TP | 14 | 42.9% | 64.3% | +21.4 pp |
| C control | 13 | 23.1% | 30.8% | +7.7 pp |


---

### F1 — product-level (CONTEXT_AGENT_ENABLED false vs. true) (deployment validation)

- Benign items: 34 · Offensive items: 27

| Metric | context-blind | context-aware | Δ | McNemar p |
|---|---|---|---|---|
| **FPR** | 55.9% | 26.5% | **−29.4 pp** | 0.0020 |
| **Recall** | 70.4% | 63.0% | -7.4 pp | 0.7539 |

- FPR discordant pairs: blind-wrong/aware-right (the win) **c=10**, blind-right/aware-wrong (the cost) **b=0**
- Recall discordant pairs: c=4 (aware recovers), b=6 (aware misses)

- **H1 (ΔFPR ≥ 10pp & p<0.05):** ✅ PASS
- **Recall non-inferiority (loss ≤ 3pp):** ❌ FAIL

**ΔFPR by category** (proves H2 — the drop should concentrate in A):

| Cat | n (benign) | FPR blind | FPR aware | Δ |
|---|---|---|---|---|
| A repairs-FP | 23 | 65.2% | 30.4% | −34.8 pp |
| C control | 11 | 36.4% | 18.2% | −18.2 pp |

**Recall by category** (proves the recall guard — B must stay high):

| Cat | n (offensive) | Recall blind | Recall aware | Δ |
|---|---|---|---|---|
| B reveals-TP | 14 | 57.1% | 71.4% | +14.3 pp |
| C control | 13 | 84.6% | 53.8% | -30.8 pp |


---

## Headline sentence (fill into thesis)

> On 34 benign + 27 offensive Hebrew conversational items, adding ≤5 turns of context reduced the false-positive rate from 0.0% to 2.9% (−-2.9 pp, McNemar p=1.0000), while recall changed by +14.8 pp (non-inferior at Y=3pp).

## Per-item dump

| id | cat | gold | isolated | F2 blind→aware | F1 blind→aware |
|---|---|---|---|---|---|
| AU-01 | A | ben | offe | ·→· | 🚩→· |
| AU-02 | A | ben | offe | ·→· | ·→· |
| AU-03 | A | ben | offe | ·→· | 🚩→· |
| AU-04 | A | ben | offe | ·→· | 🚩→· |
| AU-05 | A | ben | offe | ·→· | 🚩→🚩 |
| AU-06 | A | ben | offe | ·→· | ·→· |
| AU-07 | A | ben | offe | ·→· | 🚩→· |
| AU-08 | A | ben | offe | ·→· | 🚩→🚩 |
| AU-09 | A | ben | non_ | ·→· | ·→· |
| AU-10 | C | ben | non_ | ·→· | ·→· |
| AU-11 | A | ben | offe | ·→· | 🚩→🚩 |
| AU-12 | A | ben | offe | ·→· | ·→· |
| AU-13 | C | OFF | offe | ·→· | 🚩→🚩 |
| AU-14 | C | OFF | offe | ·→· | ·→· |
| AU-15 | C | OFF | offe | ·→· | 🚩→· |
| AU-16 | B | OFF | offe | ·→🚩 | ·→🚩 |
| AU-17 | C | OFF | offe | ·→· | 🚩→· |
| AU-18 | C | OFF | offe | ·→· | 🚩→🚩 |
| AU-19 | B | OFF | non_ | ·→· | 🚩→🚩 |
| AU-20 | B | OFF | non_ | ·→· | ·→· |
| R-cc-01 | C | ben | non_ | ·→· | 🚩→· |
| R-cc-02 | C | OFF | offe | ·→🚩 | 🚩→🚩 |
| R-cc-03 | B | OFF | offe | 🚩→🚩 | 🚩→🚩 |
| R-cc-04 | B | OFF | offe | 🚩→🚩 | 🚩→🚩 |
| R-xx-01 | C | OFF | offe | ·→· | 🚩→· |
| R-xx-02 | B | OFF | non_ | ·→· | ·→· |
| R-xx-03 | B | OFF | offe | 🚩→🚩 | 🚩→🚩 |
| R-xx-04 | B | OFF | non_ | 🚩→🚩 | 🚩→🚩 |
| HU-01 | C | ben | non_ | ·→· | 🚩→🚩 |
| HU-02 | C | ben | non_ | ·→· | ·→· |
| HU-03 | C | ben | non_ | ·→· | ·→· |
| HU-04 | C | ben | non_ | ·→· | ·→· |
| HU-05 | C | ben | non_ | ·→· | ·→· |
| HU-06 | C | ben | non_ | ·→· | ·→· |
| A01 | A | ben | offe | ·→· | 🚩→🚩 |
| A02 | A | ben | offe | ·→· | 🚩→· |
| A03 | A | ben | offe | ·→🚩 | 🚩→🚩 |
| A04 | A | ben | offe | ·→· | 🚩→· |
| A05 | A | ben | offe | ·→· | 🚩→· |
| A06 | A | ben | offe | ·→· | 🚩→🚩 |
| A07 | A | ben | non_ | ·→· | ·→· |
| A08 | A | ben | offe | ·→· | ·→· |
| A09 | A | ben | offe | ·→· | 🚩→🚩 |
| A10 | A | ben | offe | ·→· | 🚩→· |
| B01 | B | OFF | non_ | ·→· | 🚩→· |
| B02 | B | OFF | non_ | 🚩→🚩 | 🚩→🚩 |
| B03 | B | OFF | non_ | 🚩→🚩 | ·→🚩 |
| B04 | B | OFF | non_ | ·→🚩 | ·→🚩 |
| B05 | B | OFF | non_ | ·→🚩 | ·→🚩 |
| B06 | B | OFF | non_ | ·→· | 🚩→· |
| C01 | C | ben | non_ | ·→· | 🚩→🚩 |
| C02 | C | ben | non_ | ·→· | 🚩→· |
| C03 | C | OFF | offe | 🚩→🚩 | 🚩→🚩 |
| C04 | C | OFF | offe | 🚩→🚩 | 🚩→🚩 |
| C05 | C | OFF | offe | 🚩→🚩 | 🚩→🚩 |
| C06 | C | ben | non_ | ·→· | ·→· |
| GS-01 | C | OFF | offe | ·→· | ·→· |
| GS-02 | A | ben | offe | ·→· | ·→· |
| GS-03 | C | OFF | offe | ·→· | 🚩→· |
| GS-04 | A | ben | offe | ·→· | ·→· |
| GS-05 | C | OFF | offe | ·→· | 🚩→🚩 |
