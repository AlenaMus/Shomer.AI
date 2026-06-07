# Meeting 6 — Goal & Scope

**Meeting:** 6 · **Prepared:** 2026-06-06 → 2026-06-07 · **Status:** ✅ delivered

## Goal

Implement the **full server functionality flow** — every designed module wired
end-to-end and working per the design package — **without** retraining DictaBERT
or changing the frontline text classifier / its text input. Then **test** the
flow, and build a **debug SDK** to exercise and debug the server.

During the sprint two follow-ups were added by request:
- Enable **Google Gemini** as the Context-Agent LLM (with Anthropic as fallback).
- Measure the **baseline accuracy** of the current pipeline on the generated
  validation data (200 text + 300 image), as a summary + histogram PDF — to
  quantify the pre-training starting point.

## In scope

- Stand up the missing modules: **Gatekeeper, Alerts, standalone Triage, real
  SQLite persistence** (the pipeline previously had classifier → inline-triage →
  context-agent → in-memory audit, with `ALERT_DIRECT` going nowhere).
- Wire everything through the composition root (`server/app/main.py` `lifespan()`),
  Protocol-typed, one-line adapter swaps preserved.
- Conversation memory via an optional `child_id` so the Context Agent's
  `read_history` tool returns real context.
- A Python debug SDK + an interactive test console.
- Gemini-backed Context Agent (live) + an accuracy baseline report.

## Out of scope (deliberately deferred → backlog)

- **DictaBERT training** — unchanged; the frontline stays the Ollama
  `v1.0-standin`. The accuracy baseline is exactly the number the fine-tune must
  beat.
- **Real FCM/Firebase** push (`M6-ALERTS-FCM`) — a `LogNotifier` is the default;
  `FcmNotifier` is a built stub.
- **Kotlin `:sdk-cli`** (`M6-SDK-KOTLIN`) — Python debug tools first.
- `/health` deep rollup; production JSON log renderer; G-04…G-14 reconciliation.

## Decisions

- `plan-docs/decisions/meeting-6-server-flow.decision.md` — D1 LogNotifier
  default (+ FCM next), D2 Python debug tools first (+ Kotlin next), D3 optional
  `child_id` for conversation history.
- `plan-docs/decisions/gemini-context-agent.decision.md` — Gemini via the
  OpenAI-compatible endpoint (no new dependency); priority Gemini → OpenAI →
  Anthropic; live-verification fixes.

## Artifacts (this folder + references)

- `00-goal-and-scope.md` (this file) · `01-tasks.md` · `02-results-summary.md`
- `meeting6_server_flow_plan.md` — the detailed implementation plan (Phases 0–D).
- Detailed reports live under `docs/`: `meeting6_flow_test_report.md`,
  `meeting6_accuracy_report.pdf` + `meeting6_accuracy_summary.md`,
  `meeting6_manual_testing_guide.md` (+ `.pdf`).
