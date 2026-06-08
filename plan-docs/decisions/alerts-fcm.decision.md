# Alerts — Real FCM Notifier (M6-ALERTS-FCM) — Decision

Locked 2026-06-07 after a plan-mode review of which server modules were still
mocks/stand-ins. The review found only **one** genuine server-code gap (the
classifier closes via training, the Context Agent via config); the user approved
implementing it now. Plan file:
`~/.claude/plans/implementation-of-server-modules-snappy-bird.md`.

## D1 — Implement `FcmNotifier` now (close the last server stand-in)

**Question:** `LogNotifier` (logs only, no phone delivery) is the default and
`FcmNotifier` was a skeleton returning "not enabled". Build the real FCM path now,
or keep deferring?

**Choice:** **Build it now.** Real `send_alert()` per LLD §3: idempotency key →
rate-limit → build Hebrew FCM message (9-field `data` payload) → exponential-backoff
retry → `LocalRetryQueue` fallback → best-effort audit callback. `LogNotifier` stays
the default channel.

**Why:** Everything needed already existed (skeleton, scaffolded pseudocode, LLD,
`LogNotifier` template, contract tests) — it was fill-in-the-blanks, not greenfield.
It is the only remaining server stand-in whose closure needs code rather than
training or config.

**Alternatives considered:** *Keep deferring to the Android track* — but the server
side and Android receiver are independent; the server adapter can land and be
unit-tested now, ahead of the device wiring.

**Revisit:** When the Android `ShomerFcmService` receiver + a real Firebase
service-account land, run the live end-to-end (device push) test.

## D2 — Injectable `send_fn` seam + lazy `firebase-admin` import

**Question:** `firebase-admin` is heavy and not installed; how to make the
retry/queue/rate-limit logic testable and keep the module importable everywhere?

**Choice:** Lazy-import `firebase-admin` inside the send path (idempotent
`initialize_app` via `get_app()` guard), and expose a `send_fn` constructor seam.
Tests inject a fake `send_fn`; production resolves the real `messaging.send`.

**Why:** The full delivery logic gets real unit coverage with **no** firebase-admin
installed; the package still imports on any machine; absent library/creds degrade to
`AlertResult(sent=False, error="FCM not configured: …")` — never a crash.

**Alternatives considered:** *Hard dependency + skip tests when absent* — loses
coverage of the exact retry/queue logic that matters; *fully mock firebase_admin
module in tests* — more brittle than a one-callable seam.

**Revisit:** If a second push provider (APNs/web push) is added, generalise the seam
to a provider strategy.

## D3 — Channel selection via `ALERTS_CHANNEL` in the composition root

**Question:** `AlertSettings.channel` existed but was never read — `LogNotifier` was
hardcoded. How to select the channel?

**Choice:** `main.py` `lifespan()` reads `ALERTS_CHANNEL` → `fcm` | `stub` | `log`
(default `log`). One place, one flip — consistent with the ports-and-adapters rule.

**Why:** Matches the composition-root principle (`CLASSIFIER_MODEL_VERSION` etc.); the
default is unchanged so existing behaviour and tests are untouched.

**Revisit:** —

## D4 — `firebase-admin` opt-in; creds via bare `FCM_SERVICE_ACCOUNT_PATH`

**Question:** Where to declare the dependency and how to read the credential?

**Choice:** Add `firebase-admin` to `requirements.txt` marked opt-in (only needed for
`ALERTS_CHANNEL=fcm`); read the service-account path from the bare
`FCM_SERVICE_ACCOUNT_PATH` env var (not an `ALERTS_`-prefixed setting), per LLD §6 —
it is a Firebase credential, not an alerts-behaviour knob. `.env.example` Alerts
section corrected (`ALERTS_CHANNEL`, `FCM_SERVICE_ACCOUNT_PATH`, real `ALERTS_` knobs;
removed the stale `FCM_SERVICE_ACCOUNT_JSON`/`ALERTS_MAX_PER_MINUTE` names).

**Why:** Keeps the heavy dep out of the hot path for the default deployment while
making it a one-command install when FCM is wanted; preserves the LLD's credential/
behaviour separation and the existing env-var contract the tests rely on.

**Revisit:** If `firebase-admin`'s `grpcio` build proves painful on Windows CI, split
it into a `requirements-fcm.txt` extra.
