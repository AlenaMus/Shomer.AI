# Integration Test — Monitoring App (child capture → server → digest → parent)

**Track:** Real monitoring app (not a POC phase). Plan: `~/.claude/plans/linked-yawning-sifakis.md`
**Decisions:** `../plan-docs/decisions/{monitor-architecture,privacy,parent-surface}.decision.md`
**Server status:** S1–S4 shipped + tested (550 tests). **Android status:** child-mode build in progress.
**Goal:** prove the end-to-end flow — a child device captures Hebrew text shown *inside other apps*,
uploads it, the server dedups + classifies + flags, a once-a-day digest aggregates it, and the parent
reviews + reacts — works across the real Android client and the real FastAPI server over the LAN.

---

## Architecture under test

```
[android_client · role=child]                    [FastAPI :8000]                    [parent surface]
 ShomerAccessibilityService                                                         web dashboard /
   → PreFilter (Hebrew/dedup/hash)                                                  Android parent-mode
   → EncryptedEventBuffer (Room)                                                          ▲
   → MonitorUploader (WorkManager)                                                        │
        │ POST /v1/monitor/events  (Bearer device token)                                  │
        ▼                                                                                 │
   [Gatekeeper auth] → [MonitorIngest] → dedup → _run_pipeline → flag (alerted/review)    │
        │                                            │                                    │
   202 {accepted,deduped,flagged,acks}        FlaggedEventStore (sqlite)                   │
                                                     │                                    │
   POST /v1/pair (OTP → device token) ◄── pairing    └── DigestScheduler (daily) ──► GET /v1/parent/digests/{date}
                                                          GET /v1/parent/alerts ──────────┤
                                                          POST /v1/parent/alerts/{id}/react┘ (ack·label·severity)
```

This test verifies, in order:

| # | What | Tests |
|---|---|---|
| 1 | The server monitor flow works in isolation (no device needed) | S1 |
| 2 | A parent can register and pair a (child) device → device token | S2 |
| 3 | A raw `POST /v1/monitor/events` classifies, dedups, flags correctly | S3 |
| 4 | The daily digest builds and the parent API returns it | S4 |
| 5 | The parent review/react loop persists the human verdict | S5 |
| 6 | The Android child app pairs against the LAN server | A1 |
| 7 | The Android app captures a Hebrew message from WhatsApp and uploads it | A2 |
| 8 | The captured message appears as a flag on the parent surface | A3 |
| 9 | The web dashboard shows + reacts to the flag | A4 |

S-tests are runnable **now** (server is done). A-tests run **after the Android build lands**.

---

## Prerequisites

- [ ] Server venv functional: `server/.venv` with deps installed
- [ ] Full suite green from repo root: `.\server\.venv\Scripts\python.exe -m pytest server/tests/ -q` → `550 passed, 5 skipped`
- [ ] Ollama running (the `v1.0-standin` classifier transport) — `ollama list` shows `offensive-hebrew:v1`. *(For deterministic S-tests, `scripts/monitor_demo.py` stubs the classifier; for live A-tests, the real Ollama stand-in classifies — labels will be approximate until DictaBERT is trained.)*
- [ ] For A-tests: Android Studio; the `client` flavor built; a physical phone OR emulator
- [ ] For A-tests on a **physical phone**: PC and phone on the same LAN; firewall rule once:
      `New-NetFirewallRule -DisplayName "OffensiveHebrew" -Direction Inbound -LocalPort 8000 -Protocol TCP -Action Allow`

---

## Part S — Server integration (runnable now)

### S1 — End-to-end flow, deterministic (no device, no Ollama)
```powershell
cd C:\AIDevelopmentCourse\Shomer.AI
.\server\.venv\Scripts\python.exe scripts\monitor_demo.py
```
**Expected:** the walkthrough prints `accepted=3  deduped=1  flagged=2`; m1→`alerted`, m2→`review_needed`,
m3 not flagged, m4 `deduped`; the parent lists 2 flags, labels the borderline (`parent_label=offensive`),
a digest is built (`total=2`), and one labeled example exports. Final line: `DONE … verified end-to-end`.

### Live server for S2–S5 + all A-tests
```powershell
cd C:\AIDevelopmentCourse\Shomer.AI
$env:DIGEST_ALLOW_MANUAL_TRIGGER="true"
.\server\.venv\Scripts\python.exe -m uvicorn server.app.main:app --host 0.0.0.0 --port 8011
```
*(Use a fresh port like 8011 for live runs — background uvicorn can orphan :8000. `--host 0.0.0.0`
so a physical phone can reach it.)* Find the PC LAN IP: `ipconfig` → IPv4 (e.g. `192.168.1.40`).

### S2 — Register a parent + pair a device (the curl flow the app automates)
```powershell
$base = "http://localhost:8011"
$p = irm "$base/v1/parent/register" -Method Post -ContentType application/json -Body '{"display_name":"Test Parent"}'
$ph = @{ Authorization = "Bearer $($p.parent_token)" }
$c = irm "$base/v1/parent/children" -Method Post -Headers $ph -ContentType application/json -Body '{"display_name":"Test Child"}'
$code = (irm "$base/v1/parent/pairing-code" -Method Post -Headers $ph -ContentType application/json -Body (@{child_id=$c.child_id}|ConvertTo-Json)).code
$dev = irm "$base/v1/pair" -Method Post -ContentType application/json -Body (@{code=$code; device_fingerprint="test-pc"}|ConvertTo-Json)
$dh = @{ Authorization = "Bearer $($dev.device_token)" }
"parent_token=$($p.parent_token)`nchild_id=$($c.child_id)`ndevice_token=$($dev.device_token)"
```
**Expected:** `$dev.role` = `child`, `$dev.child_id` = `$c.child_id`. Keep `$p.parent_token` and
`$dev.device_token` for the dashboard + later tests.

### S3 — Upload a batch as the device
```powershell
$body = @{ session_id="s1"; child_id=$c.child_id; events=@(
  @{client_msg_id="e1"; app_package="com.whatsapp"; text="אתה מטומטם ואני שונא אותך";
    text_hash="h1"; captured_at=[double](Get-Date -UFormat %s); direction="inbound"}
)} | ConvertTo-Json -Depth 5
irm "$base/v1/monitor/events" -Method Post -Headers $dh -ContentType application/json -Body $body
```
**Expected:** `accepted=1`; the ack `flagged=true` with a `flag_id` *(label depends on the live
classifier; the abusive phrase should flag)*. A second identical POST → `deduped=1`.
**Negative:** the same POST with a different child's id in the body → **403**; with no Bearer → **401**.

### S4 — Build + read the daily digest
```powershell
irm "$base/internal/digest/run" -Method Post
$today = Get-Date -Format "yyyy-MM-dd"
irm "$base/v1/parent/digests/$today" -Headers $ph
```
**Expected:** `digests_built` ≥ 1; the digest lists `total_flagged`, `review_needed`, `by_severity`, `by_label`.

### S5 — Parent review/react loop
```powershell
$alerts = irm "$base/v1/parent/alerts?include_acked=true" -Headers $ph
$fid = $alerts[0].flag_id
irm "$base/v1/parent/alerts/$fid/react" -Method Post -Headers $ph -ContentType application/json -Body '{"action":"label","label":"offensive"}'
irm "$base/v1/parent/labels/export" -Headers $ph
```
**Expected:** the react returns the updated flag (`status=labeled`, `parent_label=offensive`); the
export lists that labeled example. Confirm the **dashboard**: open `dashboard/index.html`, Settings →
Base URL `http://localhost:8011` + the `parent_token`, then the alert appears and reacts.

---

## Part A — Android ↔ server integration (after the child-mode build)

> Base URL in the app: emulator → `http://10.0.2.2:8011`; physical phone → `http://<PC-LAN-IP>:8011`.

### A1 — Pair the app
1. Build + install the **`client`** flavor (`./gradlew :app:installClientDebug`, or Android Studio).
   *(If switching from the `poc` applicationId on the same device, uninstall the POC APK first.)*
2. Launch → complete **Consent** (note it discloses inbound **and** outbound) → **Pairing**: enter the
   OTP from S2's `/v1/parent/pairing-code` → app stores the device token.
**Pass:** app shows the paired `child_id`; server log shows `identity.pair_endpoint_success`.

### A2 — Capture + upload from WhatsApp
1. Grant the AccessibilityService (deep-link to Settings), `POST_NOTIFICATIONS`, battery exemption.
2. Confirm the non-dismissible "monitoring active" notification is present.
3. On WhatsApp (a target app), receive/send a Hebrew message containing a clearly offensive phrase.
**Pass:** within the upload interval, the server log shows `monitor.batch_received` then
`monitor.flagged`; the app's captured/uploaded counters increment.

### A3 — Flag appears server-side
```powershell
irm "$base/v1/parent/alerts" -Headers $ph
```
**Pass:** the captured message appears as a flag (`quote` matches, `app_package=com.whatsapp`,
`direction` correct). Run `/internal/digest/run` → it appears in `/v1/parent/digests/{today}`.

### A4 — Parent reviews on the dashboard
1. In `dashboard/index.html` (parent token set), the flag appears in the list.
2. Open it → react (acknowledge / label / severity).
**Pass:** the react persists (re-list shows the new status); `labels/export` includes any labeled item.

---

## Pass criteria (close the milestone)

- [ ] **S1–S5 all pass** (server flow + pairing + ingest + digest + parent loop)
- [ ] **A1–A4 all pass** on at least one real target (emulator or physical phone)
- [ ] No raw monitored text leaves the device except via the authenticated `/v1/monitor/events` call
- [ ] The 403/401 negative auth checks hold (child can't post another child's id; no token rejected)

---

## Known limitations (by-design at this stage — not failures)

- **Classifier is the Ollama `v1.0-standin`** — labels are approximate (baseline 69.5% text, hate-recall
  ≈0.10) until DictaBERT is trained + `CLASSIFIER_MODEL_VERSION=v1.1-dictabert`. The *plumbing* is what
  this test proves, not classification quality. For deterministic plumbing checks use S1 (`monitor_demo.py`).
- **Daily digest scheduler is `manual` by default** (`DIGEST_BACKEND=asyncio` + `DIGEST_HOUR` to enable
  the real once-a-day cron). Tests force it via `POST /internal/digest/run`.
- **FCM push is `LogNotifier`** — digest delivery is logged, not pushed to a device, until a Firebase
  project + service-account JSON exist (`ALERTS_CHANNEL=fcm`). Parent-mode FCM receiver is Android pass 2.
- **`MONITOR_STORE_RAW` enforcement is S5** — non-flagged raw text is still persisted server-side until
  the classify-and-discard blanking lands.
- **Direction inference is heuristic** — defaults to `inbound`; per-app accuracy improves in Android A5.
- **MediaProjection/ML-Kit OCR fallback** (for apps that block accessibility) is Android A5, not A2.
