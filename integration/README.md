# Integration test plans

One file per **integration milestone**. Each milestone corresponds to a phase in `../plan-docs/POC_Plan.md` and defines:

- **prerequisites** — what must already be true (previous phases done, environment ready)
- **test procedure** — exact commands to run, observable expected outputs
- **pass criteria** — the "done-when" conditions that close the milestone
- **known limitations** — behaviour that's by-design at this phase and shouldn't be treated as a failure

## Naming

`integration-N.md` where `N` matches the POC phase number.

| File | Maps to | What it proves |
|---|---|---|
| `integration-1.md` | POC Phase 1 | Wire works end-to-end for text + image (image processor is a stub) |
| `integration-2.md` *(future)* | POC Phase 2 | Pluggable OCR + Vision backends + strategy router |
| `integration-3.md` *(future)* | POC Phase 3 | Real fine-tuned Hebrew text classifier swapped in |
| `integration-4.md` *(future)* | POC Phase 4 | Architecture study: A/B all strategies on labelled image set |
| `integration-5.md` *(future)* | POC Phase 5 | Shared client SDK at `server/sdk/` adopted by `android_client/` |
| `integration-6.md` *(future)* | POC Phase 6 | Full evaluation + academic write-up |

Don't create future files until the corresponding phase actually starts — write them with real numbers, not speculation.

## How to use

Pick the latest integration-N for the phase you're currently in. Run the procedure top to bottom. Tick the pass criteria. If something fails, fix the underlying problem — don't bypass the test.

## Results / audit

Every execution of a plan is recorded under `results/integration-N/run-YYYY-MM-DD.md`. See `results/README.md` for the convention. Old results are never edited or deleted — they're the historical record of whether the phase ever passed cleanly. Re-runs create new dated files.
