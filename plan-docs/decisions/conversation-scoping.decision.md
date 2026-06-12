<!-- Decision record — conversation-scoping.decision.md -->

# Decision: Conversation-Scoped History + OCR Gate + Multi-Tenant Isolation

**D-id:** D-ConvScope-2026-06-12
**Date:** 2026-06-12
**Status:** Accepted

---

## Question

The monitor pipeline stored conversation turns keyed by `child_id` only.
This caused the Context Agent to see a child's **entire message stream** — across
all chats, apps, contacts, and time — as "history" for every new message,
producing confirmed false alarms:

1. A benign WhatsApp message from Daria was flagged as a threat because earlier
   **unrelated test messages** ("אני אהרוג אותך") from the same child's stream
   polluted the context.
2. A garbled OCR screenshot segment ("09/06/2026 תדושות.ארגוו ה.- ו8.-.קרן | 4%")
   was flagged "alerted" with a hallucinated explanation claiming an "explicit threat".

How should we scope conversation history and prevent OCR garbage from reaching
the classifier?

---

## Choice

### 1. Conversation-ID wire contract (agreed with Android client team)

- New field `conversation_id: str | None` on `MonitorEvent` (optional, max 128).
- Semantics: stable id for the chat **thread** (same contact/group in same app = same id over time).
- TEXT events: the client sets `conversation_id`. SCREENSHOT events: client omits it; the server mints `"screenshot:{client_msg_id}"`.
- Server falls back: `event.conversation_id → event.app_package → "default"`.

### 2. Audit store scoped by `(child_id, conversation_id)`

- `ConversationTurn` gains a `conversation_id: str = "default"` field.
- `record_conversation_turn` and `read_conversation_history` both accept a `conversation_id: str = "default"` param (keyword, default = backward compat).
- `InMemoryAuditStore`: keyed by `(child_id, conversation_id)` tuple instead of `child_id`.
- `SqliteAuditStore`: idempotent migration adds `conversation_id TEXT NOT NULL DEFAULT 'default'` to the `conversations` table (guarded by `PRAGMA table_info` check; existing `server/data/audit.db` upgrades cleanly). SELECT and INSERT both include `conversation_id`.

### 3. Pipeline threading in `main.py`

- `_run_pipeline` accepts `conversation_id: str = "default"`.
- For TEXT monitor events (`input_type="monitor"`, `conversation_turns is None`, `child_id` set), the pipeline **pre-fetches** the scoped history from the audit store and passes it as `provided_history` to the Context Agent — the CA never calls its unscoped `read_history` tool for monitor events.
- `_persist_turn` is updated to persist under the correct `conversation_id`.
- For `/classify` (public API, no `child_id`, no `input_type="monitor"`), behaviour is unchanged — the CA may call `read_history` as before (it has no `conversation_id` to scope on anyway).

### 4. `MonitorIngest` resolution

- `ingest_batch` accepts an optional `conversation_id` batch-level override (used by the screenshot path so all segments share one id).
- Per-event resolution: caller override → `event.conversation_id` → `event.app_package` → `"default"`.

### 5. Screenshot path

- `/v1/monitor/image` mints `conversation_id = f"screenshot:{client_msg_id}"`.
- This id is passed as the batch-level override to `ingest_batch`, so all segments of one screenshot share one thread and screenshots **never bleed into text history**.

### 6. OCR gibberish gate

- New `_looks_like_text(seg)` function in `monitor/router.py`, applied inside `_select_text_segments`.
- Three conditions (ALL must hold): ≥2 Hebrew/Latin alpha chars total; longest consecutive alpha run ≥ 3; alpha / non-whitespace ratio ≥ 0.45 (env-tunable via `MONITOR_OCR_MIN_ALPHA_RATIO`).
- Verified to DROP "09/06/2026 תדושות.ארגוו ה.- ו8.-.קרן | 4%" and KEEP "שלום עולם", "Daria: אנחנו לא יכולים", threatening Hebrew messages.

### 7. Multi-tenant isolation

- Confirmed that the parent-facing read path (`/v1/parent/alerts`, `/{flag_id}`, `react`) already enforces ownership via `_owned_child_ids(request, ctx.parent_id)` before returning any event.
- `get_alert` returns 404 (not 403) for flags belonging to other parents — ownership-blind to prevent enumeration.
- The `(child_id, conversation_id)` scoping at the audit store level adds defence-in-depth: even if ownership checks were bypassed, history from other children is structurally unreachable.

---

## Why

- **Root cause was architectural, not a bug**: history was stored and retrieved by
  `child_id` only, so ANY conversation the child ever had polluted every future CA evaluation.
- **The fix is minimal and reversible**: a single new column + default parameter means
  zero breaking changes; old adapters, tests, and `/classify` callers are unaffected.
- **The OCR gate targets the specific failure mode**: the garbled segment had high punctuation/digit density and no meaningful consecutive alpha run — exactly what the ratio + run-length checks catch.
- **Multi-tenant isolation was already enforced by the parent router**; the test suite proves it and adds a regression guard.

---

## Alternatives Considered

1. **Per-contact sub-key only (no `conversation_id` field)**: using `app_package` as the fallback is already implemented; the explicit `conversation_id` field is necessary for clients that know the contact/group id and need finer granularity.
2. **Sliding-time-window scoping**: discard history older than N hours. Simpler but doesn't address messages from different contacts within the same time window.
3. **Vision-LLM image analysis instead of OCR gate**: deferred to Phase 4 (secondary axis); the heuristic gate is a sound short-term fix for confirmed false positives.
4. **Regex-based OCR filter**: brittle to Hebrew orthography variation; the alpha-ratio + run-length approach is language-agnostic and stateless.

---

## Revisit

- When real `conversation_id` values flow from the Android client (after client-side implementation), validate that the fallback chain (`app_package`) is still needed or can be retired.
- The OCR threshold (`MONITOR_OCR_MIN_ALPHA_RATIO=0.45`) should be tuned empirically once a real screenshot corpus is available.
- Consider a SQLite index on `(child_id, conversation_id, created_at)` if per-thread queries become a performance hot spot at scale.
