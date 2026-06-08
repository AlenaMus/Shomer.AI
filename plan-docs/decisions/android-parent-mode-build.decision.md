# Android Parent-Mode Build — Decisions

**Sprint:** A4 (milestone implemented 2026-06-07, pass 2 of 2)
**Agent:** android-developer
**Status:** DONE — both poc and client debug APKs build successfully with no Firebase project required.
**Server contract:** 550 tests frozen (server/app/flagged/router.py, digest/router.py, identity/router.py).

---

## D1 — FCM opt-in strategy: no hard build dependency on google-services.json

**Question:** How do we ship a working ShomerFcmService without breaking `assembleClientDebug` on a
machine that has no Firebase project configured?

**Choice:** **FCM is fully written but commented out and not manifest-registered.** The file
`parent/ShomerFcmService.kt` contains the complete implementation inside a block comment, with a
`ShomerFcmServicePlaceholder` object as the active code so the file is not empty. The Manifest
has no `<service>` entry for it. The `firebase-messaging-ktx` dependency and the
`com.google.gms.google-services` plugin are NOT in `app/build.gradle.kts`.

**Why:** The `com.google.gms.google-services` plugin fails the build hard when `google-services.json`
is absent — there is no "skip if file missing" mode. Since we have no Firebase project yet (it's an
ops carry-over), the only build-safe option is to keep the dependency and plugin out entirely.

**The polling UI (AlertListScreen + DigestScreen) is fully functional with zero Firebase setup.**
FCM is additive — it improves latency of parent alerts, not their existence.

**Steps to enable FCM (documented in ShomerFcmService.kt):**
1. Create a Firebase project at https://console.firebase.google.com/; add Android app with package
   `com.shomer.client`; download `google-services.json` → `android_client/app/google-services.json`.
2. In `app/build.gradle.kts`: uncomment `id("com.google.gms.google-services")` in the plugins block
   and `implementation("com.google.firebase:firebase-messaging-ktx:24.0.0")` in dependencies.
3. In root `build.gradle.kts`: uncomment `id("com.google.gms.google-services") version "4.4.2" apply false`.
4. In `AndroidManifest.xml`: uncomment the `ShomerFcmService` `<service>` block.
5. Uncomment the class body in `ShomerFcmService.kt` and delete the placeholder object.
6. On the server: set `FCM_SERVICE_ACCOUNT_PATH` in `server/.env` so `FcmNotifier` can send pushes.

**Alternatives considered:**
- Ship with a dummy/placeholder `google-services.json` — rejected because the file contains real
  app IDs and the dummy must be exact JSON; it's fragile and confusing.
- Use a Gradle flag to conditionally apply the plugin — possible but complex; the opt-in comment
  approach is simpler and self-documenting.
- Wait until FCM is live to write the service — rejected; the full implementation is written now
  while the server contract is fresh. Enabling it is a one-step uncomment + file drop.

**Revisit:** When the ops team creates the Firebase project. Estimated: before the first parent
beta test on a real device.

---

## D2 — Parent auth approach: opaque token MVP (no email/password)

**Question:** How does a parent log in on the Android client?

**Choice:** **Two-path opaque-token screen:** (a) Create new account via `POST /v1/parent/register
{display_name}` — server mints `parent_id` + `parent_token` (UUID secret); client stores
`parent_token` in EncryptedSharedPreferences as the device token with `role=parent`. (b) Use
existing token — parent pastes the opaque `parent_token` directly into the app (useful when moving
the app to a new phone or sharing a token across a household).

**Why:** The server explicitly documents that `POST /v1/parent/register` is on the auth allowlist
(no prior credential required) and that the returned `parent_token` IS the only credential for MVP.
Production-grade email/password + JWTs + MFA are explicitly out of MVP scope (see server/app/identity/router.py docstring). Matching this contract exactly avoids any client-server friction.

**TokenStore integration:** `saveParentToken(parentToken, parentId)` stores `parent_token` in the
`KEY_DEVICE_TOKEN` slot and `parent_id` in the `KEY_CHILD_ID` slot with `role=parent`. This means
`AuthInterceptor` adds the correct `Authorization: Bearer <parent_token>` header to all `/v1/`
calls automatically — no parent-specific auth logic needed in the interceptor.

**Alternatives considered:**
- Separate EncryptedSharedPreferences key for parent token — rejected: AuthInterceptor already
  reads from a single `KEY_DEVICE_TOKEN` slot; doubling the stored token would require interceptor
  changes.
- QR-code pairing from dashboard to phone — better UX but requires extra server work; deferred.

**Revisit:** S5 hardening / production launch — email/password + JWT flows.

---

## D3 — Polling-first, FCM additive (for the review UI)

**Question:** Should the parent alert list require FCM to be useful, or should polling be sufficient?

**Choice:** **Polling is the primary mechanism; FCM is additive.** `AlertListScreen` loads
`GET /v1/parent/alerts` on launch, on pull-to-refresh, and on filter change. The digest screen
loads `GET /v1/parent/digests/{date}` on date change. Neither screen requires an FCM push to show
data.

**Why:** FCM has an ops dependency (Firebase project + service account) and an Android dependency
(google-services.json). Both are pending. The parent's core workflow — see the review queue,
acknowledge, label, check the daily digest — works in the app via polling from day one of testing.
FCM improves notification latency but does not gate the core workflow.

**FCM payload contract (documented for when FCM is enabled):** Data message (not notification
message) with fields: `type` ("daily_digest" | "alert_escalated"), `date` (for digest),
`flag_id` (for alerts), `child_id`, `title`, `body`. Severity maps to FCM Android priority
(high for critical/high, normal for medium/low). Channel IDs reuse the 3 channels already
registered in `ShomerApplication.onCreate()`: `shomer.alerts.escalated`, `shomer.alerts.direct`,
`shomer.alerts.silent`.

**Alternatives considered:**
- FCM-required (no polling) — rejected: blocks testing until ops work is done.
- Long-polling / WebSocket — rejected: overkill for a daily-digest-cadence app; increases battery/network overhead.

**Revisit:** Once FCM is live, add auto-refresh on FCM receipt by posting to a `SharedFlow` in
`AlertListViewModel`.
