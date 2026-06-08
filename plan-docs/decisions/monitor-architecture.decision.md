# Monitor Architecture — Decisions

Decisions taken at the start of the real-monitoring-app sprint (2026-06-07). Goal:
turn Shomer.AI from a single-shot "type text → classify" demo into a **passive,
always-on monitor** — a child-device app that reads Hebrew text displayed inside
*other* apps (WhatsApp, Instagram, Telegram, Messenger, social posts/comments),
streams it to the server for classification, and lets a parent receive, review,
and react to flagged content. Approved plan:
`C:\Users\Dima\.claude\plans\linked-yawning-sifakis.md`.

The privacy/consent fork is in `privacy.decision.md`; the parent-surface choice is
in `parent-surface.decision.md`. This file covers the system/server architecture.

---

## D1 — Reuse the existing pipeline; add an ingestion orchestrator (no new pipeline)

**Question:** A streaming monitor produces dozens of messages/minute/child versus
the single-shot `/classify` model (one message, one HTTP round-trip, client-paced).
Do we build a new classification pipeline for the monitor, or reuse the existing
`_run_pipeline()` (classifier → triage → CA → alert → audit)?

**Choice:** **Reuse `_run_pipeline()` verbatim.** Add a new ingestion endpoint
`POST /v1/monitor/events` that takes a *batch* of captured messages and fans each
event into the existing per-message pipeline via a thin orchestrator service
(`MonitorIngest`). The monitor needs *new surrounding infrastructure* (batch
ingest, dedup, a flagged-event store, identity/auth, a daily digest), not a new
classification path.

**Why:** The pipeline (classifier → triage → CA → alert → audit, with the G-03
triage normalization) is the project's tested core; forking it would duplicate the
exact logic the design package signed off on. An orchestrator-in-front keeps the
monitor's request volume concerns (batching, dedup, async) separate from
classification, and means the not-yet-trained DictaBERT flip
(`CLASSIFIER_MODEL_VERSION=v1.1-dictabert`) still benefits the monitor for free.

**Alternatives considered:**
- *New monitor-specific pipeline* — passed over: duplicates classifier/triage/CA
  logic; two code paths to keep correct; no upside.
- *Client calls `/classify` per message* — passed over: dozens of round-trips per
  child per minute; no batching/dedup; hammers the classifier bottleneck.

**Revisit:** If the monitor's needs diverge so far from single-shot that a shared
pipeline becomes a constraint (not foreseen) — or at S6 when batched GPU inference
changes the per-event call shape.

---

## D2 — New capabilities are Protocol ports with ≥2 adapters, built only in `lifespan()`

**Question:** The monitor needs dedup, a parent-readable flagged-event history,
child/parent identity, and a daily digest. How do these fit the codebase's
ports-and-adapters rule?

**Choice:** Each is a **`@runtime_checkable` Protocol port with ≥2 adapters**,
constructed **only** in `server/app/main.py` `lifespan()`, exactly like
`AuditStore`/`NotificationChannel`:
- `DedupStore` — `InMemoryTtlDedupStore` (default) ↔ `RedisDedupStore` (S6 scale-up)
  + `NullDedupStore` (load tests). Suppresses re-scroll/redraw capture storms keyed
  on `(child_id, text_hash)` with a TTL window.
- `FlaggedEventStore` — `SqliteFlaggedEventStore` (durable) ↔ `InMemoryFlaggedEventStore`
  (tests); parent-readable curated history, **kept separate from `AuditStore`** so
  retention/minimization policies diverge from the evaluation schema.
- `IdentityStore` (S2) — `SqliteIdentityStore` ↔ `InMemoryIdentityStore`; child_id
  minting, parent↔child pairing, device-token auth.
- `DigestScheduler` (S3) — `AsyncioCronDigestScheduler` (in-process) ↔
  `ExternalCronDigestRunner` (OS cron hitting an internal endpoint).
- `NotificationChannel` (exists) — promote `FcmNotifier` skeleton → live for the
  daily digest push; no new port.

`MonitorIngest` itself is a plain application service (not swappable infra), built
in `lifespan()` from the ports above + the existing pipeline.

**Why:** Preserves the one-line env-flip swap rule and the composition-root
discipline that the whole server is built on; keeps the Gatekeeper content-blind
(auth is metadata, it imports the `IdentityStore` *Protocol*, not the adapter);
keeps the parent surface decoupled from the eval schema.

**Alternatives considered:**
- *Fold flagged events into `AuditStore`* — passed over: the audit log records
  *everything* for evaluation/retention; the parent history is a curated,
  longer-retention, ack-stateful subset. A separate port lets the two evolve and
  lets minimization (`MONITOR_STORE_RAW=false`) apply to monitor traffic without
  touching audit.
- *Ad-hoc helpers instead of ports* — passed over: violates the project's core
  design principle; blocks the Redis/Postgres scale-up swaps.

**Revisit:** Per-port, as each phase (S2 identity, S3 digest, S6 scale) lands.

---

## D3 — Batch ingest returns fast; the daily-digest cadence governs delivery, not data

**Question:** At monitor volume, should ingestion block on per-event classifier
latency, and how do parents receive alerts without being spammed?

**Choice:** `POST /v1/monitor/events` **acks the batch fast** (counts of
accepted/deduped/flagged + per-event acks); the device never blocks on per-event
verdicts. Flagged + borderline events are *recorded immediately* but **delivered as
ONE aggregated digest per child per day** (configurable hour) via FCM — see
`DigestScheduler` (S3). The parent dashboard/app still shows the **live list on
demand**; the cadence governs push only, not data availability. *Open item flagged
for S3:* whether a **critical-severity** event (confirmed `violence`) bypasses the
digest for an immediate push — recommended yes.

**Why:** The user specified "alerts received once a day." A daily digest is
anti-spam by design and decouples device throughput from notification cadence. Fast
ack keeps the child device responsive and battery-friendly; the device doesn't need
final verdicts (the parent gets them via the digest + on-demand list).

**Alternatives considered:**
- *Push per flagged event* — rejected by the user's once-a-day requirement; also
  spammy at monitor volume, training parents to ignore alerts.
- *Block ingest on verdicts* — passed over: couples device latency/battery to
  classifier + CA latency; defeats batching.

**Revisit:** S3, for the critical-severity immediate-push exception and the
configurable digest hour.

---

## D4 — Volume reduction stack: on-device pre-filter first, server dedup as safety net

**Question:** `AccessibilityService` re-reads the same on-screen text constantly
(scroll, redraw, re-focus). How do we keep classification volume sane and the
classifier (the known bottleneck, baseline 69.5% text) from being swamped?

**Choice:** A layered reduction stack, applied in order:
1. **On-device pre-filter** (biggest lever): drop the child's own-typed text when in
   inbound-only mode, drop non-Hebrew (script check), drop UI chrome / very short
   text, local rolling-hash dedup + debounce. Most content never leaves the device.
2. **Server-side `DedupStore`** — catches what the device missed; near-free.
3. **Batching** — one HTTP/TLS/auth round-trip per 5–20 events.
4. **(S6) Classifier micro-batching** — batch a request's texts into one GPU forward
   pass once DictaBERT is live.
5. **Triage/CA gating preserved** — only borderline/violence reach the (paid, latent)
   Context Agent; keep CA escalation rare.

**Why:** The on-device pre-filter is simultaneously the privacy control (§
`privacy.decision.md`) and the scaling lever — expect 10×–50× reduction before
anything is sent. Server dedup is the safety net, not the primary mechanism.

**Alternatives considered:**
- *Send everything, dedup only server-side* — passed over: ships the entire screen
  stream off-device (privacy) and wastes bandwidth/battery.

**Revisit:** S6, tuning pre-filter aggressiveness against measured server load.

---

## D5 — Monitor raises the classifier quality bar; gate the v1.1 flip on a realistic slice

**Question:** Single-shot tolerates 69.5% text accuracy / hate-recall ≈0.10. Does an
always-on monitor?

**Choice:** **No.** The monitor demands materially higher precision on the alert
path (every false positive = a false parent alarm at volume) and higher recall on
`hate`/`violence` (every miss = the exact harm the product exists to catch). Before
flipping `CLASSIFIER_MODEL_VERSION=v1.1-dictabert` *for the monitor*, build a
**monitor-realistic eval slice** (short, slangy, multi-app social Hebrew, both
directions) and require the F1≥0.78 gate **plus** per-class `hate`/`violence` recall
and calibration (ECE) to clear the bar on that slice. Until then, run the monitor in
**shadow / high-threshold mode** (flag-and-store for parent review, suppress
proactive push on low-confidence) so a weak classifier doesn't spam parents.

**Why:** Curated single-shot test numbers measure the wrong distribution for a
monitor; calibration drives the triage thresholds that decide alert-vs-escalate; a
weak classifier behind always-on monitoring erodes parent trust fast.

**Alternatives considered:**
- *Flip v1.1 on the existing test set* — passed over: wrong distribution; says
  nothing about monitor-grade precision/recall.

**Revisit:** S6, when DictaBERT is trained and the realistic slice exists. Owner:
`ai-researcher-developer`.
