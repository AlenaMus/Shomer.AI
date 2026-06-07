# Meeting 6 — Tasks

Status of every task in the Meeting-6 sprint. Detailed plan:
`meeting6_server_flow_plan.md`.

## Build the full server flow (Phases 0–D)

| # | Task | Owner | Status |
|---|------|-------|--------|
| P0 | Shared schema seam — optional `child_id`/`message_id`, `AlertRequest`/`AlertResult` | main thread | ✅ |
| A1 | `triage/` module — `TriageEngine` Protocol + `ThresholdTriageEngine` (G-03 normalization + label overrides) + `StubTriageEngine` | backend-developer | ✅ 45 tests |
| A2 | `alerts/` module — `NotificationChannel` + **`LogNotifier` (default)** + `StubNotifier` + `FcmNotifier` stub + rate limiter + retry queue + severity | backend-developer | ✅ 105 tests |
| A3 | `gateway.py` — trace-id / rate-limit / size / timeout middleware + Prometheus `/metrics` + `register_gateway()` | backend-developer | ✅ 37 tests |
| A4 | `audit_log/SqliteAuditStore` — real persistence (5 tables, WAL) + `RetentionSweeper` + conversation history | ai-researcher-developer | ✅ 23 tests |
| B | Wire `main.py` composition root (v0.6.0-fullflow): SQLite store + sweeper, triage engine, LogNotifier alert dispatch, gateway, `child_id` persistence, shared `_run_pipeline()` | main thread | ✅ |
| C | Python debug SDK — `dev_client.py` (+`replay`), `inspect_audit.py`, `load_test.py` + `tests/integration/test_full_flow.py` (all 4 triage branches) | backend-developer | ✅ 7 integration |
| D | Test + report — full suite green + live run; `docs/meeting6_flow_test_report.md` | main thread | ✅ |

## Gemini-backed Context Agent

| # | Task | Status |
|---|------|--------|
| G1 | `GeminiClient` (OpenAI-compat endpoint, reuses `openai` SDK) + `gemini_api_key`/`gemini_model` settings + `_build_llm_clients` rewrite (priority Gemini→OpenAI→Anthropic; fixed key-string bug) + `.env.example` | ✅ |
| G2 | Live verification + fixes: model `gemini-2.5-flash` (2.0 retired/404); output parser strips ```json``` fences (Anthropic fallback); disable Gemini "thinking" (reasoning_effort=none) so JSON isn't truncated; corrected `.env` key typos | ✅ |

## Accuracy baseline

| # | Task | Status |
|---|------|--------|
| E1 | `scripts/eval_accuracy.py` — run 200 text + 300 image (stratified) through the live server, compute accuracy + per-class P/R/F1 + confusion (sklearn), produce `docs/meeting6_accuracy_report.pdf` + `accuracy_eval/results.json` + summary | ✅ |

## Test console (UI) + usability

| # | Task | Status |
|---|------|--------|
| U1 | `scripts/test_console.py` — self-starting interactive menu: spawns own server, health check, per-session `audit.db` + `server.log`, result + triage + CA verdict + alert per request, self-documenting menu + `?` help | ✅ |
| U2 | Hebrew RTL display fix (`python-bidi`) + numbered **sample picker** (typing Hebrew echoes reversed in Windows terminals — picking samples avoids it) | ✅ |
| U3 | `dev_client.py classify` gains `--child-id`/`--message-id`/`--trace-id`; manual testing guide (`docs/meeting6_manual_testing_guide.md` + PDF) | ✅ |

## Backlog (filed, not this sprint)

| ID | Task |
|----|------|
| M6-ALERTS-FCM | Real Firebase `FcmNotifier` behind the `NotificationChannel` Protocol |
| M6-SDK-KOTLIN | Gradle `:sdk-cli` wrapping `ShomerClient`, parity-tested vs the Python tools |
| — | `/health` deep rollup (ocr + context_agent + alerts queue + audit); production JSON log renderer |
| — | DictaBERT training track — flip `CLASSIFIER_MODEL_VERSION=v1.1-dictabert` when the checkpoint lands |
