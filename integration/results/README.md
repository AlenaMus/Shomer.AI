# Integration test results — audit trail

Every execution of an `integration-N.md` plan produces a results file under `integration-N/`. These are the source of truth for "did this phase actually pass?" — never delete or rewrite old results; create a new one for a re-run.

## Layout

```
integration/
├── integration-N.md             ← the test plan (procedure + pass criteria)
└── results/
    ├── README.md                ← this file
    └── integration-N/
        ├── run-YYYY-MM-DD.md           ← first attempt that day
        ├── run-YYYY-MM-DD-2.md         ← second attempt same day (only if needed)
        └── run-YYYY-MM-DD.md           ← next day...
```

## What each `run-*.md` contains

1. **Header** — date, who ran it (machine + person), git commit (`git rev-parse HEAD`), overall status (PASS / PARTIAL / FAIL).
2. **Environment snapshot** — Python version, Ollama version, Android Studio + AGP version, JDK, Gradle, the model registered with Ollama.
3. **Step-by-step log** — for each step in the test plan: command run, exit code, key output, observations. Long stdout/stderr can be inlined or referenced.
4. **Pass criteria checklist** — every box from the test plan, ticked or explicitly failed with a reason.
5. **Defects / follow-ups** — anything observed that's not blocking but should be filed.
6. **Sign-off** — final PASS / FAIL with one-sentence rationale.

## Why a fresh file per attempt

So that a future you can see whether "Phase 1 passed cleanly on first try" or "Phase 1 took three attempts and these three things had to be fixed in the venv setup." That history is the audit trail a graduate-project examiner may ask for.

## What to do when a run fails

1. **Don't edit the failed run file.** It's a historical record.
2. **Open or update an issue** (or a TODO in the repo) describing the failure.
3. **Fix the root cause in the code or the test plan.** If the test plan is wrong, edit `integration-N.md`. If the code is wrong, fix it and commit.
4. **Re-run.** Create a new `run-YYYY-MM-DD-2.md` (or next-day file) and start over.
