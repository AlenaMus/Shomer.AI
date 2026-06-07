# Meeting-6 Plan — Full Server Flow + Debug SDK

**Date:** 2026-06-06
**Sprint goal (Meeting 5 → Meeting 6):** Implement the **full server
functionality flow** — every designed module wired end-to-end and working per
the design package — **without** retraining DictaBERT or changing the frontline
text classifier / its text input. Then **test** the flow. Build the **Python
debug CLI** to exercise and debug the server.

**Non-goals this sprint:** DictaBERT training, frontline model/preprocessing
changes, real FCM/Firebase, Kotlin `:sdk-cli`, Android client work. All are
explicit backlog follow-ons.

Decisions for this sprint: `plan-docs/decisions/meeting-6-server-flow.decision.md`
(D1 LogNotifier · D2 Python tools first · D3 optional `child_id`).

---

## 1. Where we are vs. where we need to be

**Today** the pipeline runs end-to-end for the happy path but three functional
components are missing and persistence is a stop-gap:

```
[client] → CORS → AuditLoggingMiddleware → /classify
         → TextClassifier (Ollama stand-in) ──✅
         → _triage()  (INLINE in main.py)  ──⚠️ not a module
         → ContextReasoner (borderline)    ──✅ but read_history has no real data
         → InMemoryAuditStore              ──⚠️ stop-gap, lost on restart
   ALERT_DIRECT → (nothing)                ──❌ no notification is sent
   (no rate-limit / trace-id / size guard / /metrics) ──❌ Gatekeeper absent
```

**Target** — every module present, Protocol-typed, swappable from `main.py`:

```
[client] → Gatekeeper(trace-id · rate-limit · size · /metrics) → CORS → Audit MW
         → /classify {text, child_id?}
         → (image: OcrBackend → text)
         → TextClassifier (Ollama stand-in, UNCHANGED)
         → TriageEngine.decide()                         [NEW module]
              SILENT          → record → return
              ALERT_DIRECT    → NotificationChannel.send_alert() → record → return   [NEW module]
              ESCALATE_TO_CA  → ContextReasoner.evaluate(child_id) → map → (alert?) → record
              REVIEW_NEEDED   → record → return
         → persist conversation turn (child_id)          [NEW behavior]
         → SqliteAuditStore.record_*()                   [NEW adapter, real persistence]
         → RetentionSweeper (hourly, 7-day)              [NEW background task]
```

---

## 2. Work breakdown

### Phase 0 — Shared schema seam (do first, single-writer, ~30 min)
Avoids 4 parallel agents colliding on `schemas.py`.
- `ClassifyRequest`: add optional `child_id: str | None = None` (+ optional
  `message_id`). `text` unchanged.
- Add `AlertRequest` / `AlertResult` Pydantic models (alerts LLD §2).
- Add `severity` typing/helpers if needed. No behavior change yet.

### Phase A — four modules in parallel (agents)
Each: Protocol + ≥2 adapters + settings + structlog + Prometheus + contract test
+ unit tests, per its LLD. **No `main.py` edits** (composition is Phase B).

| # | Module | Agent | Deliverable | LLD |
|---|--------|-------|-------------|-----|
| A1 | **triage/** | backend-developer | Extract `_triage` → `TriageEngine` Protocol + `ThresholdTriageEngine` (the G-03 confidence-normalization is the contract) + `StubTriageEngine`. 6-row polarity matrix test. | `docs/design/triage/design.md` |
| A2 | **alerts/** | backend-developer | `NotificationChannel` Protocol + **`LogNotifier` (default)** + `StubNotifier` + `AlertRateLimiter`(InMemory) + `LocalRetryQueue` + severity mapping from label/confidence. `FcmNotifier` = stub class raising `NotImplementedError` + backlog task. | `docs/design/alerts/design.md` |
| A3 | **gatekeeper/** | backend-developer | `gateway.py`: TraceId / RequestSize / RequestTimeout middleware + slowapi limiter + prometheus instrumentator + `/metrics` + `register_gateway()` + `GatekeeperSettings`. Fail-open. | `docs/design/gatekeeper/design.md` |
| A4 | **audit_log/SqliteAuditStore** | ai-researcher-developer | `sqlite_adapter.py` implementing the full `AuditStore` Protocol against the 5-table schema (classifications, agent_traces, alerts, conversations, gold_set_metadata), WAL, `RetentionSweeper`, conversation history for `read_history`, gold-label methods. Must satisfy the existing contract that `InMemoryAuditStore` passes. | `docs/design/audit_log/design.md` |

### Phase B — composition root wiring (sequential, after A; me or backend-developer)
- Construct `TriageEngine`, `NotificationChannel`(+rate limiter+queue),
  `SqliteAuditStore` in `lifespan()`; `register_gateway(app, ...)`.
- Replace inline `_triage` call with `app.state.triage.decide(...)`.
- On `ALERT_DIRECT` (frontline-direct **and** CA-confirmed) build an
  `AlertRequest` and call `notifier.send_alert()`; record via `record_alert`.
- Thread `req.child_id` into `evaluate()` and persist each turn via
  `record_conversation_turn`.
- Swap `InMemoryAuditStore` → `SqliteAuditStore`. Keep in-memory as the test/
  degraded adapter.
- `/health` rollup: add ocr + context_agent + alerts queue + audit states.
- End-to-end smoke test via `TestClient` for all four triage branches.

### Phase C — Python debug SDK (parallel with B where possible; agents)
| # | Tool | Agent | Deliverable |
|---|------|-------|-------------|
| C1 | `scripts/dev_client.py` | backend-developer | Add `replay <trace_id>` (re-run a recorded input), keep classify/image/health/info/demo. |
| C2 | `scripts/inspect_audit.py` | backend-developer | Read-only SQLite inspector: list/inspect by `trace_id` / `child_id`, show triage + CA trace + alert disposition. |
| C3 | `scripts/load_test.py` | backend-developer | N-concurrent driver over `golden_inputs.jsonl` → Markdown report with p50/p95/p99, error rate, triage-branch histogram. |

### Phase D — test the flow & report
- `pytest server/tests` (target: all green; new modules add suites).
- Launch server (Ollama stand-in) + run `dev_client.py demo` and `load_test.py`.
- Write `docs/meeting6_flow_test_report.md`: per-branch evidence (SILENT /
  ALERT_DIRECT→LogNotifier / ESCALATE→CA / REVIEW), latency table, audit.db
  row dump, `/metrics` excerpt.

---

## 3. Dependency / ordering graph

```
Phase0(schemas) ──▶ A1 triage ─┐
                ──▶ A2 alerts ─┤
                ──▶ A3 gatekeeper ─┼─▶ Phase B (wire main.py) ─▶ Phase D (test+report)
A4 sqlite (needs only audit Protocol, parallel w/ Phase0) ─┘        ▲
                                       Phase C (debug tools) ───────┘
```
A1–A4 run concurrently. C1–C3 can be written against the stable wire
protocol in parallel, but are *run* in Phase D after B lands.

## 4. Risks & mitigations
- **Parallel edits to `schemas.py`** → Phase 0 single-writer seam before fan-out.
- **SQLite async + WAL on Windows** → aiosqlite already pinned; adapter owns its
  connection lifecycle; tests use a temp-file DB, not `:memory:` (WAL needs a file).
- **Gatekeeper middleware order** → follow LLD §3.2 exactly (timeout→size→trace
  →ratelimit→prometheus→CORS→audit); contract test asserts `X-Trace-ID` on every
  response.
- **LogNotifier must never raise** → same NEVER-raises contract as FcmNotifier;
  failures captured in `AlertResult`.
- **Context Agent needs LLM keys** → with no keys it uses `MockLlmClient`
  (deterministic); the flow still exercises ESCALATE→CA→map end-to-end.

## 5. Definition of done
- All four modules implemented with passing contract + unit tests.
- `main.py` constructs every adapter via Protocols; one-line swap preserved.
- Full flow demonstrated for all four triage branches (real SQLite persistence).
- Python debug tools run against a live server; `inspect_audit.py` reads back
  the persisted rows; `load_test.py` emits a p99 report.
- `docs/meeting6_flow_test_report.md` written.
- Backlog tasks filed: `M6-ALERTS-FCM`, `M6-SDK-KOTLIN`, `/health` deep rollup
  follow-ups, and the deferred G-04…G-14 reconciliation items as relevant.
