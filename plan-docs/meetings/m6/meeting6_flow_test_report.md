# Meeting-6 — Full Server Flow: Test Report

**Date:** 2026-06-06
**Scope:** Every designed server module wired end-to-end and working, **without**
DictaBERT training or any change to the frontline text classifier / its input.
Classifier = the Ollama `v1.0-standin`. Plan: `plan-docs/meeting6_server_flow_plan.md`.
Decisions: `plan-docs/decisions/meeting-6-server-flow.decision.md`.

---

## 1. Result at a glance

| Item | Result |
|---|---|
| **Full automated suite** (`server/tests`, fast) | **384 passed, 5 skipped** (was 167 before this sprint) |
| **Integration suite** (`tests/integration/test_full_flow.py`) | **7 passed** — all 4 triage branches + alert path + conversation persistence + 2 label overrides |
| New modules | `triage/` (45) · `alerts/` (105) · `gatekeeper/` (37) · `audit_log/SqliteAuditStore` (23) — all green |
| Live end-to-end (Ollama stand-in) | `/health` ok · `/model/info` 5 labels · `/metrics` live · demo 10/10 200 |
| Persistence | real SQLite; classification ids monotonic across process restarts |
| Alerts | LogNotifier dispatching; **6 sent + 2 rate_limited** recorded in one run |
| Bugs found during testing | 4 found, **4 fixed** (see §4) |

The pipeline now is:

```
client → Gatekeeper(trace-id · rate-limit · size · /metrics) → CORS → Audit-MW
       → /classify {text, child_id?}  |  /classify-image (OCR → text)
       → TextClassifier (Ollama v1.0-standin, UNCHANGED)
       → TriageEngine.decide()
            SILENT          → record → return
            ALERT_DIRECT    → NotificationChannel.send_alert() (LogNotifier) → record → return
            ESCALATE_TO_CA  → ContextReasoner.evaluate(child_id, trace_id) → map → (alert?) → record
            REVIEW_NEEDED   → record → return
       → persist conversation turn (child_id) → SqliteAuditStore (+ agent_trace, + alert row)
       → RetentionSweeper (hourly, 7-day) owned by lifespan()
```

Every concrete adapter is constructed only in `server/app/main.py` `lifespan()`;
everything else depends on Protocols (`TextClassifier`, `OcrBackend`,
`TriageEngine`, `ContextReasoner`, `NotificationChannel`, `AuditStore`). Swapping
any one is a one-line change.

---

## 2. The four triage branches (deterministic, `test_full_flow.py`)

| Branch | How triggered (stub classifier) | Asserted |
|---|---|---|
| **SILENT** | `non_offensive`, conf 0.95 | `triage_decision=silent`; 0 alerts |
| **ALERT_DIRECT** | CA off; `abusive`, off=True, conf 0.97 → prob 0.97 ≥ 0.7 | StubNotifier got 1 `send_alert` (right label); `alerts` row written |
| **ESCALATE_TO_CA** | borderline `is_offensive=True`, conf 0.5 (prob 0.5) + mock CA | `frontline_only_decision=escalate_to_ca`; **`agent_traces` row written** |
| **REVIEW_NEEDED** | classifier `error=True` | `triage_decision=review_needed`; 0 alerts |
| label override | `pornographic` → always ALERT_DIRECT; `violence` → always ESCALATE | both asserted |
| conversation | 2 `/classify` with same `child_id` | 2 `conversations` rows, correct turn order; `read_conversation_history` returns them |

---

## 3. Live run evidence (Ollama `v1.0-standin`)

**Golden-set demo** (`scripts/dev_client.py demo`) — the stand-in classified all
10 curated Hebrew samples to their expected category (10/10 transport, 10/10
agreement, mean ≈ 986 ms). It emits the full label set: `abusive`, `hate`,
`violence`, `pornographic`, `non_offensive`.

**Audit stats** (`scripts/inspect_audit.py stats`) after a mixed run:

```
  classifications : 15  (unique traces: 15)
  agent_traces    : 1
  alerts          : 8
  conversation    : 5 turns
  Triage distribution   alert_direct 8 (53.3%) · silent 7 (46.7%)
  Alert FCM status      sent 6 · rate_limited 2
```

**Alerts** (`inspect_audit alerts`) — LogNotifier dispatched and persisted both
dispositions, with severity derived from label/confidence:

```
abusive       sev=medium  fcm=sent          child=child_a
pornographic  sev=high    fcm=sent          child=child_b
hate          sev=high    fcm=sent          child=child_c
... (anonymous burst) ...  fcm=rate_limited  child=unknown   ← anti-storm guard
```

**Agent trace** (`inspect_audit trace <id>`) — the Context Agent's reasoning is
now persisted (tools all firing):

```
  model_used     : mock
  tools_called   : read_history, lookup_slang, check_age
  is_real_threat : False
  explanation    : שיחה ידידותית ללא סיכון אמיתי
  tokens         : in=50  out=30  total=80
```

**Gateway** (`GET /metrics`) — Prometheus exposes the `shomer_gateway_*` series
(overhead histogram, rate-limit + payload counters), confirming the edge layer
is installed and measuring.

**Load test** (`scripts/load_test.py`) — 10–20 concurrent `/classify` over the
golden set, 0 % error rate; report at `docs/loadtest_report.md`. (Latency
reflects the Ollama stand-in, not the future DictaBERT path.)

---

## 4. Bugs found during testing — and fixed

| # | Bug | Root cause | Fix |
|---|---|---|---|
| 1 | `agent_traces` table always empty | `_run_pipeline` never called `record_agent_trace` after the CA ran | capture `classification_id` from `record_classification`, then `record_agent_trace(...)` when a `ContextDecision` exists (`main.py`) |
| 2 | CA logs showed `trace_id=no-trace` | `evaluate()` was called without `trace_id` | pass `trace_id=trace_id` into `evaluate()` |
| 3 | **Sent alerts not persisted** (only `rate_limited` rows appeared) | Windows cp1252 console can't encode the Hebrew `quote`/`explanation` in the `alerts.sent` structlog line → `UnicodeEncodeError` aborted the send path (the `rate_limited` line has no Hebrew fields, so it survived) | force UTF-8 stdio at server startup in `main.py` (`sys.stdout/err.reconfigure(encoding="utf-8")`); verified 6 sent + 2 rate_limited persist with **0 charmap errors** and no env var needed |
| 4 | `inspect_audit trace` crashed in the agent-trace section | `tools_called` items are `{"name": ...}` dicts, but the tool `join`ed them as strings | normalize dict→name before join |

Bugs 1, 2, 4 were surfaced by the integration test + debug tools; bug 3 was
surfaced by the live alert run and is the most important operational finding.

---

## 5. Behavior notes (intended, but worth recording)

- **Triage label overrides** (design-aligned, configurable via env):
  `always_escalate_labels={"violence"}` (get context before alerting on
  violence), `always_alert_labels={"pornographic"}` (always alert). This is why
  high-confidence `violence` escalates to the CA rather than alerting directly.
- **Mock Context Agent**: with no `OPENAI_API_KEY`/`ANTHROPIC_API_KEY`, the CA
  uses a deterministic mock that resolves borderline/escalated cases to "not a
  threat" → final `silent`. Real escalation alerts will require LLM keys (or a
  CA that confirms). The wiring path is fully exercised regardless.
- **Anonymous rate-limit bucket**: requests without `child_id` share the
  `"unknown"` rate-limit key, so an anonymous offensive burst is suppressed
  after 3/min — the anti-storm guard working as designed. Per-child traffic gets
  its own bucket (demonstrated: 3 distinct children each got a `sent` alert).

---

## 6. Deferred / backlog (filed, not done this sprint)

- **`M6-ALERTS-FCM`** — implement `FcmNotifier` (firebase-admin) behind the same
  `NotificationChannel`; add `firebase-admin` dep + Firebase project + a parent
  device token. One-line swap in `lifespan()`.
- **`M6-SDK-KOTLIN`** — the Gradle `:sdk-cli` wrapping `ShomerClient`, parity-tested
  against the Python tools (shared `golden_inputs.jsonl`).
- **Logging hardening** — beyond the stdio fix, consider a JSON renderer in
  production so Hebrew log fields never depend on console codepage.
- **`/health` deep rollup** — surface ocr + context_agent + alerts-queue +
  audit states (currently the classifier gates the status field).
- **DictaBERT** — unchanged; still the separate training track. Flip
  `CLASSIFIER_MODEL_VERSION=v1.1-dictabert` once the checkpoint lands and the
  same demo becomes the accuracy demo.

---

## 7. How to reproduce

```powershell
# 1. Full automated suite (run FROM THE REPO ROOT — fixtures use root-relative paths)
server/.venv/Scripts/python.exe -m pytest server/tests/ -q -m "not slow"

# 2. Live server (Ollama must be running)
$env:AUDIT_DB_PATH="server/data/audit_demo.db"; $env:CONTEXT_AGENT_ENABLED="true"
server/.venv/Scripts/python.exe -m uvicorn app.main:app --app-dir server --port 8000

# 3. Drive + inspect it
server/.venv/Scripts/python.exe scripts/dev_client.py demo
server/.venv/Scripts/python.exe scripts/load_test.py --out docs/loadtest_report.md
server/.venv/Scripts/python.exe scripts/inspect_audit.py --db server/data/audit_demo.db stats
```
