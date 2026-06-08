# Parent Surface — Decisions (Monitoring App)

Decisions taken at the start of the real-monitoring-app sprint (2026-06-07).
Covers how the **parent** receives, reviews, and reacts to flagged content.
Companion: `monitor-architecture.decision.md`, `privacy.decision.md`. Approved plan:
`C:\Users\Dima\.claude\plans\linked-yawning-sifakis.md`.

---

## D1 — One Android codebase, two runtime roles; parent surface = web dashboard + Android parent-mode

**Question:** Is the parent a separate app, the same app in a different mode, or a
non-Android surface (web)? The user asked for the parent to "receive and review the
alerts and react."

**Choice:** **One Android Gradle codebase with two roles chosen at pairing**
(`role=child` runs the `AccessibilityService` capture; `role=parent` runs the
review/react UI), separate installs — **and** the parent review surface is delivered
on **BOTH a web dashboard and the Android parent-mode app, built in parallel**
(the user's choice). Both surfaces read the exact same parent API
(`GET /v1/parent/alerts`, `/{id}`, `POST /{id}/react`, `GET /v1/parent/digests/{date}`).

**Why:** One codebase + a runtime role flag reuses the entire networking/auth/SDK
stack instead of forking the existing `android_client`. Keeping the sensitive
`AccessibilityService` on the child install only isolates the store-policy-fraught
component. The shared parent API means the web dashboard and Android parent-mode are
two thin clients over the same contract — the user wanted both, so build them against
one API in parallel.

**Alternatives considered:**
- *Two fully separate apps (child app + parent app)* — passed over: 2× build/maintenance,
  forks the existing client; over-scoped for a grad project.
- *Web dashboard only (defer Android parent-mode)* — was the fastest single path, but
  the user explicitly chose **both in parallel**.
- *One app, both roles on the same device* — rejected: parent and child are different
  people/devices.

**Revisit:** If parallel build of both surfaces strains the timeline, the web
dashboard is the lower-effort path to a working end-to-end demo and can land first;
Android parent-mode follows. (Documented so the fallback is pre-approved.)

---

## D2 — Alert delivery: once-a-day aggregated digest (not per-event push)

**Question:** How often does the parent get notified?

**Choice:** **One aggregated digest per child per day** (configurable hour),
delivered by FCM via the `DigestScheduler`. Flagged + borderline events accumulate
server-side through the day and are summarized into a single push. The dashboard/app
still shows the **live list any time** — the cadence governs *push*, not data
availability. *Open item (S3):* a confirmed **critical** event (`violence`) may
bypass the digest for an immediate push — recommended yes, to confirm.

**Why:** The user specified "alerts received once a day." Anti-spam by design;
prevents alert fatigue that trains parents to ignore notifications; decouples device
throughput from notification cadence.

**Alternatives considered:**
- *Real-time push per flagged event* — rejected by the user's once-a-day requirement;
  also spammy at monitor volume.

**Revisit:** S3 — confirm the critical-severity immediate-push exception and the
default digest hour; make the hour parent-configurable.

---

## D3 — Parent react actions: Acknowledge · Label offensive/not · Severity (label feeds training)

**Question:** For "unknown but may be offensive" (borderline) content — the cases the
classifier is uncertain about and routes to `review_needed` — what can the parent
*do*?

**Choice:** Three react actions on a flagged event (`POST /v1/parent/alerts/{id}/react`):
1. **Acknowledge / dismiss** — mark seen/handled; leaves the active queue.
2. **Label offensive / not-offensive** — the parent's human verdict on a borderline
   case. **This label is stored and becomes a labeled training example** for the
   future DictaBERT fine-tune, directly attacking the classifier's weakest slice
   (`hate` recall ≈0.10).
3. **Severity / escalate flag** — parent marks how serious (low/med/high), driving
   notification urgency.

Free-text notes are **out of scope for the MVP** (the user did not select them).

**Why:** The user selected these three. The borderline/`review_needed` path is
exactly where human judgment is the safety net (`monitor-architecture.decision.md`
D3); turning the parent's verdict into training data closes the loop between the
product and the classifier's known weak spots — a genuine research contribution.

**Alternatives considered:**
- *Acknowledge-only (minimum loop)* — passed over: wastes the human label that the
  borderline queue uniquely produces.
- *Add free-text notes* — deferred: not selected for MVP; revisit if parents need to
  capture context ("known friend, sarcasm") the classifier can't see.

**Revisit:** Post-MVP — free-text notes; and the pipeline that exports parent labels
into the DictaBERT training set (owner: `ai-researcher-developer`).
