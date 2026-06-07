# Meeting-6 — Full Server Flow Implementation — Decisions

Decisions taken at the start of the Meeting-6 sprint (2026-06-06). Goal of the
sprint: implement the **full server functionality flow** — every module wired
end-to-end and working per the design package — **without** retraining DictaBERT
or changing the frontline text classifier / its text input. Then test the flow.
SDK debug tooling follows the server flow.

---

## D1 — Alerts default delivery channel

**Question:** `ALERT_DIRECT` decisions currently go nowhere — no notification is
sent. The `alerts` LLD specifies a `NotificationChannel` Protocol with FCM
(Firebase Cloud Messaging) as one adapter. What should the default delivery
channel be for this sprint?

**Choice:** Ship a **`LogNotifier`** as the default `NotificationChannel`
adapter. It records the alert to a structured `structlog` line **and** to the
audit store (`record_alert`), so the full pipeline `ALERT_DIRECT →
send_alert() → recorded` is demonstrable and testable **without** any Firebase
project, service-account JSON, or parent device. `FcmNotifier` is built as a
swap-in adapter behind the **same** Protocol as the **next-step backlog task**.

**Why:** Real FCM requires a Firebase project + a service-account credential on
the server + a registered parent device token to demonstrate end-to-end. That
is real setup work and a physical/emulated receiving device — out of proportion
to a "make all components work and test the flow" sprint goal. The ports-and-
adapters design means the swap to `FcmNotifier` is a one-line change in
`main.py` `lifespan()` later, with zero caller changes.

**Alternatives considered:**
- *Real FCM now* — passed over: needs Firebase project + creds + a receiving
  device before anything is demonstrable; blocks the sprint on external setup.
- *No alerts module (leave ALERT_DIRECT inert)* — passed over: the flow would
  be visibly incomplete; the whole point of the sprint is that every component
  works.

**Revisit:** When a Firebase project + parent device are available (task
`M6-ALERTS-FCM` in the backlog). Flip `ALERTS_CHANNEL=fcm` /
`FCM_SERVICE_ACCOUNT_PATH` and construct `FcmNotifier` in `lifespan()`.

---

## D2 — SDK / debug tooling scope & order

**Question:** "SDK for debugging the server" — Python terminal tooling, the
Kotlin client SDK + `:sdk-cli`, or both?

**Choice:** **Python debug CLI tools first** (this sprint): finish
`scripts/dev_client.py` (add `replay <trace_id>`), build `scripts/inspect_audit.py`
(read-only SQLite inspector) and `scripts/load_test.py` (concurrency + p99
report). The **Kotlin `:sdk-cli`** is the **next step** — a backlog task
(`M6-SDK-KOTLIN`), deferred until the Python tools have exercised the flow.

**Why:** The fastest way to exercise and debug the freshly-wired server flow is
a dependency-light Python client that speaks the same wire protocol — no Gradle
build, no Kotlin toolchain. `dev_client.py` already exists; finishing it +
adding the two inspector/load tools gives full debug coverage now. The Kotlin
SDK is primarily for the Android clients and adds build overhead better spent
after the server flow is proven.

**Alternatives considered:**
- *Python + Kotlin `:sdk-cli` together* — passed over for this sprint: Gradle/
  Kotlin build setup overhead competes with finishing the server flow; better
  as an immediate follow-on once the Python tools confirm the wire protocol.

**Revisit:** Immediately after this sprint — `M6-SDK-KOTLIN` builds the Gradle
`:sdk-cli` wrapping `ShomerClient`, validated against the Python tools for
cross-language wire-protocol parity (shared `golden_inputs.jsonl`).

---

## D3 — Conversation context (`child_id`) on `/classify`

**Question:** "Without modifying the text input" — does that rule out adding an
optional `child_id` to `/classify`? The Context Agent's `read_history` tool
needs per-child context to return real history across requests.

**Choice:** Add an **optional `child_id`** field to the `/classify` (and
`/classify-image`) request. The `text` field and the frontline classifier /
its preprocessing are **untouched**. Every message is persisted to the
`conversations` table keyed by `child_id`, so `read_conversation_history()`
returns a real sliding window and the Context Agent's `read_history` tool
becomes genuinely functional.

**Why:** "Without modifying the text input" scopes to the ML side — don't
retrain DictaBERT, don't change the frontline text/preprocessing. Adding an
**optional, additive** request field does not modify the text input or the
classifier; it is what makes the Context Agent's designed `read_history`
capability actually work end-to-end, which is the point of the sprint. The
field is optional, so existing single-message callers are unaffected.

**Alternatives considered:**
- *Keep stateless* — passed over: `read_history` would always return empty, so
  the Context Agent would reason on the current message only and one of its
  three designed tools would be inert — the flow would not be fully exercised.

**Revisit:** If a privacy review later objects to per-child correlation, or if
a richer conversation-ingestion path (the child app streaming inbound+outbound
turns) supersedes the per-request field.
