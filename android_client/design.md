# Android Client — Low-Level Design (Real Monitoring App)

**Status:** design (build = backlog task "Android child-capture + parent-mode").
**Supersedes:** the POC client (`com.dima.offensivehebrew`: MainActivity + Classify/Settings
screens + Retrofit `ApiService`). The POC's networking/settings layer is *reused*; the capture
engine + parent surface are net-new.
**Contract source of truth:** `server/app/schemas.py` (`MonitorEvent`/`MonitorBatch*`),
`server/app/monitor/router.py` (`POST /v1/monitor/events`), `server/app/identity/router.py`
(pairing), and the parent API (S4). Decisions: `plan-docs/decisions/{monitor-architecture,
privacy,parent-surface}.decision.md`. Plan: `~/.claude/plans/linked-yawning-sifakis.md`.

---

## 1. Purpose & scope

A single Android app, **two runtime roles chosen at pairing**, separate installs:

- **child-mode** — passively reads Hebrew text shown *inside other apps* (WhatsApp, Instagram,
  Telegram, Messenger, social posts/comments), pre-filters on-device, batches, and uploads to the
  server for bullying/offensive classification. Monitors **inbound + outbound** (text the child
  receives *and* sends). Runs a non-dismissible "monitoring active" indicator.
- **parent-mode** — receives the **once-a-day digest** (FCM), reviews flagged + borderline events,
  and reacts (acknowledge · label offensive/not · severity). Mirrors the web dashboard, same API.

Package rename `com.dima.offensivehebrew` → **`com.shomer.client`** (requires APK uninstall — POC
and client cannot coexist under the same `applicationId` without product flavors).

Out of scope here: server modules (`backend-developer`), DictaBERT training (`ai-researcher-developer`),
the web dashboard (separate frontend), the Kotlin `:sdk-cli` (server/sdk deliverable).

---

## 2. Capture mechanism (the hard part)

Reading text from *other* apps on a non-rooted device has exactly three viable mechanisms:

| Mechanism | Role | Verdict |
|---|---|---|
| **`AccessibilityService`** — subscribe to `TYPE_WINDOW_CONTENT_CHANGED` / `TYPE_VIEW_TEXT_CHANGED`, walk the `AccessibilityNodeInfo` tree of the foreground app, read `text`/`contentDescription`, filter by source `packageName`. | **PRIMARY** | The only general cross-app text reader. Catches chat bubbles, comments, post text. |
| **`MediaProjection` + ML Kit on-device OCR** (`com.google.mlkit:text-recognition`) — capture the screen as a bitmap, OCR locally, extract text. | **FALLBACK** | For apps that render text in Canvas / suppress accessibility nodes (some Snapchat/Instagram surfaces). On-device only — no pixels leave the phone. Reuses the OCR concept from the server image path. |
| `NotificationListenerService` | not used alone | Only captures notification previews, not in-app scrollback. May be a cheap *supplement* later. |
| root / Xposed | out of scope | Not viable for a distributable product. |

**Direction inference (inbound vs outbound):** per target app, use node heuristics — alignment/RTL
gravity, known sender/self view-ids, or "is this in the compose box vs the message list". Tag each
event `direction ∈ {inbound, outbound}`. Default unknown → `inbound` (conservative). Per-app
heuristics live in a `TargetAppProfile` registry so adding an app = adding a profile, not editing the
service.

**Debounce + dedup:** a screen redraws constantly. Debounce per window (~300–500 ms quiet period),
and dedup by a rolling hash of `(packageName, normalizedText)` in a bounded LRU so a static screen is
not re-emitted on every `CONTENT_CHANGED`.

---

## 3. Architecture (child-mode)

```
AccessibilityService (ShomerAccessibilityService)
   │  raw node text + packageName + inferred direction
   ▼
CaptureCoordinator ──► PreFilter (on-device, runs BEFORE anything is stored)
   │                     • drop non-Hebrew (Unicode Hebrew-block ratio check)
   │                     • drop UI chrome / < N chars / numeric-only
   │                     • rolling-hash dedup + debounce
   │                     • compute text_hash = sha256(text) (hex) for server dedup
   ▼
EncryptedEventBuffer (Room + SQLCipher / EncryptedSharedPreferences)
   │  durable offline queue of MonitorEvent rows
   ▼
MonitorUploader (WorkManager periodic + expedited)
   │  batch 5–20 → POST /v1/monitor/events  (Bearer device-token)
   │  on 2xx: delete uploaded rows; on failure: keep, backoff, retry
   ▼
Server  ──► (async) daily digest ──► FCM ──► parent
```

Components:
- **`ShomerAccessibilityService : AccessibilityService`** — declared in manifest with
  `android.accessibilityservice` meta-data (`accessibility_service_config.xml`:
  `accessibilityEventTypes=typeWindowContentChanged|typeViewTextChanged`,
  `packageNames` = target set, `canRetrieveWindowContent=true`). Emits to `CaptureCoordinator`.
- **`CaptureForegroundService : Service`** (`FOREGROUND_SERVICE_SPECIAL_USE`) — keeps the process
  alive and owns the **non-dismissible monitoring-active notification** (ongoing, low-importance
  channel). AccessibilityServices can be killed by OEM battery managers; the foreground service +
  battery-optimization exemption mitigate.
- **`PreFilter`** — pure Kotlin, unit-testable, no Android deps. The privacy + volume gate (see
  decision `privacy.decision.md` D2, `monitor-architecture.decision.md` D4).
- **`EncryptedEventBuffer`** — Room DAO over an encrypted DB; survives reboots/offline; wiped on
  successful upload. Holds the `MonitorEvent` fields only — never counterparty identity.
- **`MonitorUploader`** — `CoroutineWorker`; batches, sends, handles retry/backoff + offline replay;
  attaches `Authorization: Bearer <device_token>` and `X-Trace-Id`.
- **`TargetAppRegistry`** — the monitored package set + per-app direction profiles; user-editable via
  the target-app picker.

State: `ViewModel` + `StateFlow` + `collectAsStateWithLifecycle()`. DI: Hilt. No `LiveData` in new code.

---

## 4. Architecture (parent-mode)

- **`PairingScreen`** — enter the OTP from the parent dashboard → `POST /v1/pair` → store device token
  (role=parent) in `EncryptedSharedPreferences`.
- **`AlertListScreen`** — `GET /v1/parent/alerts` (S4); Compose list, **Hebrew RTL** (`LayoutDirection.Rtl`),
  shows label · severity · app · direction · time · status (incl. `review_needed` borderline queue).
- **`AlertDetailScreen`** — quote (≤200 chars) + Hebrew explanation; react actions →
  `POST /v1/parent/alerts/{id}/react` (`acknowledge` | `label` offensive/not | `severity`).
- **`DigestScreen`** — `GET /v1/parent/digests/{date}` — the once-a-day aggregated summary; FCM
  deep-links here.
- **`ShomerFcmService : FirebaseMessagingService`** — receives the daily digest push (+ critical
  bypass if enabled S3), registers the FCM token at pairing, dedups by digest id, deep-links into the
  list. (This is the Android side of the already-server-done `M6-ALERTS-FCM`.)

---

## 5. Networking & wire contract

Reuse the POC Retrofit/OkHttp/Moshi stack (`data/ApiService.kt`, `data/Models.kt`,
`data/SettingsRepository.kt`). Add:

- **`MonitorApi`** — `@POST("v1/monitor/events") suspend fun ingest(@Body batch: MonitorBatchRequest): MonitorBatchResponse`.
  Bodies mirror `server/app/schemas.py` EXACTLY: `MonitorEvent{client_msg_id, app_package, text,
  text_hash, captured_at, direction}`, `MonitorBatchRequest{session_id, child_id, events[≤50]}`,
  `MonitorBatchResponse{accepted, deduped, flagged, acks[]}`. `client_msg_id` is the device-side
  idempotency key (UUID per captured event).
- **`PairingApi`** — `POST /v1/pair`, parent endpoints (`/v1/parent/*`) for parent-mode.
- **`ParentApi`** (S4) — alerts list/detail/react, digests.
- **Auth interceptor** — OkHttp interceptor adds `Authorization: Bearer <device_token>` from
  `EncryptedSharedPreferences` to all `/v1/*` calls (not the legacy `/classify`).
- **Labels** stay underscore-spelled on the wire (`non_offensive`), matching the server.

**LAN / dev networking (unchanged from POC):** emulator `http://10.0.2.2:8000/`; physical phone
`http://<PC-LAN-IP>:8000/` + one-time firewall rule
(`New-NetFirewallRule -DisplayName "OffensiveHebrew" -Direction Inbound -LocalPort 8000 -Protocol TCP -Action Allow`).
Base URL is user-configurable via `SettingsRepository` (DataStore). `network_security_config.xml`
permits cleartext for the dev host **only** — prod host forbids cleartext (TLS, S5).

---

## 6. Permissions & onboarding

Sequential consent-first onboarding (child-mode):
1. **Consent screen** (mandatory) — dual disclosure: guardian configures; child is informed.
   Explicit copy that **outbound** (sent) messages are also checked. Links to privacy policy.
2. **Pairing** — enter OTP → device token.
3. **Target-app picker** — choose monitored apps.
4. **AccessibilityService enable** — cannot be granted programmatically; deep-link via
   `Settings.ACTION_ACCESSIBILITY_SETTINGS`, explain why, detect return state.
5. **`POST_NOTIFICATIONS`** (API 33+) runtime permission (for the monitoring indicator + alerts).
6. **Battery-optimization exemption** — `ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS`.
7. (Fallback only) **`MediaProjection`** consent if OCR fallback is enabled.

Manifest: `FOREGROUND_SERVICE`, `FOREGROUND_SERVICE_SPECIAL_USE`, `POST_NOTIFICATIONS`,
`INTERNET`, `RECEIVE_BOOT_COMPLETED` (restart capture after reboot), `BIND_ACCESSIBILITY_SERVICE`
(on the service). No camera/contacts/location.

---

## 7. Privacy (client side — see `privacy.decision.md`)

- **On-device pre-filter is the privacy gate** — most content never leaves the phone (non-Hebrew /
  chrome / short / deduped dropped before storage).
- **Encrypted-at-rest** offline buffer; wiped on upload.
- **No counterparty PII** ever captured/stored/sent — only the message text, source `app_package`,
  and direction. No handles, no phone numbers, no social graph, no screenshots persisted (OCR
  fallback extracts text then discards the bitmap).
- **Non-dismissible monitoring indicator** in child-mode (ethical + Play-policy).
- **Deployment reality:** AccessibilityService-for-monitoring is Play-restricted → academic MVP
  ships sideload / internal-test.

---

## 8. Build & module structure

```
android_client/app/src/main/java/com/shomer/client/
├── MainActivity.kt              (role router: child-mode vs parent-mode)
├── data/                        (REUSED + extended: ApiService→MonitorApi/ParentApi/PairingApi,
│                                 Models, SettingsRepository, AuthInterceptor, TokenStore)
├── accessibility/               (ShomerAccessibilityService, CaptureCoordinator, TargetAppRegistry,
│                                 DirectionInference)
├── capture/                     (CaptureForegroundService, PreFilter, EncryptedEventBuffer + Room DAO)
├── monitor/                     (MonitorUploader CoroutineWorker, batching, retry)
├── parent/                      (AlertList/Detail/Digest screens + VMs, ReactActions, ShomerFcmService)
├── onboarding/                  (Consent, Pairing, TargetAppPicker, PermissionFlow)
├── di/                          (Hilt modules)
└── ui/theme/                    (Material 3, RTL-aware)
```

- **Gradle product flavors** `poc` (`com.dima.offensivehebrew`) + `client` (`com.shomer.client`) so the
  rename diff is reviewable and the POC can be kept side-by-side during transition. APK uninstall is
  required when switching `applicationId` on a device.
- **Suggested branch:** `feature/package-rename-com-shomer-client` for the rename, separate from
  new-screen work.
- Deps to add: Hilt, WorkManager, Room (+ SQLCipher or `androidx.security:security-crypto`),
  `firebase-messaging`, ML Kit text-recognition (fallback). Keep Retrofit/OkHttp/Moshi/Coil from POC.

---

## 9. Phased Android milestones (interleave with server S1–S6)

| M | Deliverable | Depends on |
|---|---|---|
| **A1** | Package rename → `com.shomer.client` + flavors; reuse Retrofit layer; `MonitorApi` against the frozen S1 contract. | server S0/S1 (done) |
| **A2** | `AccessibilityService` capture PoC on WhatsApp → `PreFilter` → `EncryptedEventBuffer` → `MonitorUploader` → `POST /v1/monitor/events`. Foreground service + monitoring indicator. | server S1 |
| **A3** | Pairing screen + device-token auth interceptor (Bearer); child_id from token. | server S2 |
| **A4** | parent-mode: `ShomerFcmService` daily-digest receiver + AlertList/Detail/react UI. | server S3/S4 |
| **A5** | Multi-app target picker + direction inference per app; OCR fallback for blocking apps. | — |
| **A6** | Consent + onboarding hardening; cleartext-off prod config; battery/OEM-kill resilience. | server S5 |

---

## 10. Risks

- **OEM battery managers kill the AccessibilityService** → foreground service + battery exemption +
  `RECEIVE_BOOT_COMPLETED` restart; document per-OEM quirks.
- **Node-tree traversal cost** on busy screens → debounce, cap tree depth, off-main-thread parsing.
- **Apps that block accessibility** → MediaProjection+OCR fallback (A5).
- **Hebrew RTL extraction quirks** (bidi, mixed Hebrew/English) → normalize before hashing; test on
  real WhatsApp/IG Hebrew.
- **Play Store policy** on monitoring → sideload/internal-test for the MVP; consent + visible
  indicator are mandatory regardless.
- **Battery/data drain from over-capture** → the pre-filter aggressiveness is the lever (tune in A6
  against server-measured volume).
```
