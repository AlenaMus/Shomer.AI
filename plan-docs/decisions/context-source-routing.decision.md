# Decision — Context-source routing: screenshot conversation vs. per-child DB history

**Date:** 2026-06-11 · **Status:** Implemented (590 tests pass)

## Question

Where should the Context Agent get its conversation history from when the message under
evaluation came from an OCR'd screenshot, vs. a single captured text message?

Before this change, every pipeline event with a `child_id` (including each OCR line segment
of a screenshot) was persisted to the per-child `conversations` table, and the CA always
read its history from that table (`read_history` tool, last 5 turns). Three problems:
(1) screenshot lines polluted the per-child history with OCR noise (contact names, UI
chrome); (2) a dense screenshot (10 segments) flushed real prior messages out of the 5-turn
window; (3) the CA only saw the screenshot's own conversation "by accident" of sequential
processing order, with every line mislabeled `role="child_outbound"`.

## Choice

**Route the context source by input type:**

- **OCR screenshot** (`POST /v1/monitor/image`): the screenshot *is* the conversation. The
  full ordered list of selected OCR line segments is passed explicitly through
  `ingest_batch(conversation_turns=...)` → `_run_pipeline(conversation_turns=...)` →
  `ContextReasoner.evaluate(provided_history=...)`. The CA skips the `read_history` DB
  tool (audit trace records `"provided_history"` instead) and judges each line against the
  whole visible screen. Screenshot lines are **no longer persisted** to the
  `conversations` table (`_persist_turn` skipped when `conversation_turns` is provided).
- **Single text message** (`/classify`, `/v1/monitor/events` text path): unchanged — the
  message is persisted as a turn and the CA reads the last-5-turns per-child history from
  the audit store, as before.

Turn dicts for the screenshot path use `role="screenshot_line"`; `_format_history` in
`prompt.py` renders any role literally, so no prompt change was needed.

## Why

- The screenshot already contains the complete conversational context the CA needs — using
  it directly is both more accurate (full visible thread, reading order) and deterministic
  (no dependence on processing order or window size).
- Keeping OCR noise out of the `conversations` table protects the *text-message* path: the
  5-turn history for a single captured message now contains only real captured messages.
- Plausible contributor to the F1 recall failure (CA over-downgrading in Category C,
  84.6%→53.8%): noisy/cross-source history. This change is a targeted, testable fix to try
  before gold set v2 rerun.

## Alternatives considered

- **Per-event `conversation_turns`** (each segment gets only *preceding* lines): rejected —
  all segments share one screen; the CA should see the whole visible thread, and batch-level
  threading is simpler.
- **Keep persisting screenshot lines but with a distinct role**: rejected — still floods the
  5-turn window and mixes sources; filtering at read time adds complexity for no benefit.
- **Make DictaBERT itself context-aware (train on conversations)**: out of scope — that is
  experiment E6 (naive-concat vs. selective-agent) per the research plan; the trained D10
  model stays context-blind by design (it is the context-blind baseline of the RQ).

## Revisit

- If a future Android capture path supplies real message direction, replace the hardcoded
  `role="child_outbound"` in `_persist_turn` (and `screenshot_line`) with true
  inbound/outbound roles — known limitation, matters for bullying judgment.
- Rerun the context-FP eval (F1 product-level) after this change — the screenshot-context
  and history-pollution fixes may move the Category-C recall numbers.
