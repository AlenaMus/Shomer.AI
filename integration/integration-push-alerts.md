# Integration Test — Push Notifications & Alerts (full flow)

**Track:** Alert delivery across the monitoring flow. **Server status:** S1–S4 shipped + tested.
**Channels:** `LogNotifier` (default) · `NtfyNotifier` (free push, no Firebase) · `FcmNotifier`
(Firebase) · `StubNotifier` (tests). **Decisions:**
`../plan-docs/decisions/{alerts-fcm,alerts-delivery-channel,parent-surface}.decision.md`.

**Goal:** prove that a classified-as-offensive message reaches the parent — both as a **push
notification** (proactive) and on the **parent surface** (pull) — end-to-end through the real
FastAPI composition root, with automated tests and copy-paste manual flows.

---

## Where push fires (3 trigger points)

```
                                   ┌─────────────────────────── app.state.notifier ──────────────────────────┐
                                   │  ALERTS_CHANNEL = log | ntfy | fcm | stub   (one instance, all paths)    │
[child device] ─POST /v1/monitor/events─►[MonitorIngest]                                                      │
                                   │        │ dedup → _run_pipeline → flag                                    │
                                   │        ├─(1) status="alerted" AND severity∈{high,critical}               │
                                   │        │        → on_critical_flag → send_alert(message_id="critical:…") ─┤──► PUSH
                                   │        └─ FlaggedEventStore                                               │
[POST /internal/digest/run] ─► DigestScheduler.deliver(child) → send_alert(message_id="digest:{child}:{date}")┤──► PUSH
[POST /classify] ───────────► triage ALERT_DIRECT → send_alert(message_id=<msg_id>) ─────────────────────────┘──► PUSH
```

| # | Trigger | Endpoint that drives it | Fires when | `message_id` prefix |
|---|---|---|---|---|
| 1 | **Critical-immediate** | `POST /v1/monitor/events` | flagged `status="alerted"` **and** severity ∈ {high, critical}; needs `DIGEST_ENABLED=true` + `DIGEST_CRITICAL_IMMEDIATE=true` | `critical:` |
| 2 | **Daily digest** | `POST /internal/digest/run` (or the `asyncio` cron) | any child with ≥1 flagged event that day | `digest:` |
| 3 | **Legacy /classify** | `POST /classify` | triage routes `ALERT_DIRECT` | (the request's msg id) |

**Severity governs trigger #1 — this surprises people:**

| label | conf ≥ 0.70 | triage | immediate push (#1)? |
|---|---|---|---|
| `violence` | **critical** | always escalates to CA first | only after CA confirms |
| `hate` | **high** | threshold | ✅ yes |
| `pornographic` | **high** | **always-alert** (ALERT_DIRECT) | ✅ yes |
| `abusive` | **medium** (capped) | threshold | ❌ **no** (medium < high) — digest only |
| `non_offensive` | low | silent | ❌ no |

So a clearly-abusive message still alerts and shows up in the digest, but does **not** fire the
*immediate* push. Use a `pornographic`/`hate` (≥0.70) message to demo trigger #1.

---

## Channel matrix

| `ALERTS_CHANNEL` | Cost | Setup | Parent receives via | Uses `parent_fcm_token`? |
|---|---|---|---|---|
| `log` (default) | $0 | none | server log + audit + dashboard (pull) | no |
| **`ntfy`** | **$0** | `ALERTS_NTFY_TOPIC` + the free ntfy app subscribes | **proactive phone push** | **no** (publishes to the topic) |
| `fcm` | $0 (setup-heavy) | `pip install firebase-admin` + `FCM_SERVICE_ACCOUNT_PATH` + parent registers a token | proactive phone push | **yes** (`PATCH /v1/device/fcm-token`) |
| `stub` | $0 | none | nothing (records in memory) | no — for tests |

> **Why ntfy is the easy path:** it ignores `parent_fcm_token` and publishes to a server-configured
> *topic*, so push works with **no per-device token registration and no Android parent app** — the
> parent just subscribes the ntfy app to the topic. FCM needs the parent device to register its token.

---

## Prerequisites

- [ ] Server venv: `server/.venv` with deps installed.
- [ ] Full suite green from **repo root**: `.\server\.venv\Scripts\python.exe -m pytest server/tests -q`.
- [ ] For live runs: a free port (background uvicorn can orphan `:8000`).
- [ ] For **ntfy** manual flows: the free **ntfy** app on a phone (or https://ntfy.sh in a browser),
      subscribed to your `ALERTS_NTFY_TOPIC`.
- [ ] For **FCM** manual flows: a Firebase project + service-account JSON, `pip install firebase-admin`.

---

## Part A — Automated integration (runnable now, no phone)

### A1 — Push-path integration test (the core proof)
```powershell
cd C:\AIDevelopmentCourse\Shomer.AI
.\server\.venv\Scripts\python.exe -m pytest server/tests/integration/test_push_alert_flow.py -v
```
**What it proves:** through the real `lifespan()` with `ALERTS_CHANNEL=stub`, a paired child uploads
a `pornographic` message → **critical-immediate push fires** (`message_id="critical:…"`) → the daily
digest run → **digest push fires** (`message_id="digest:…"`); a benign-only batch fires **no** push.
**Expected:** `2 passed`.

### A2 — Alerts channel unit suite (log / ntfy / fcm / stub)
```powershell
.\server\.venv\Scripts\python.exe -m pytest server/tests/alerts -q
```
**Expected:** `129 passed`. `NtfyNotifier` and `FcmNotifier` are each at 100% line coverage
(payload shape, retry→queue, rate-limit, never-raises, not-configured degradation).

### A3 — Deterministic end-to-end walkthrough (log channel)
```powershell
.\server\.venv\Scripts\python.exe scripts\monitor_demo.py
```
**Expected:** prints `accepted=3 deduped=1 flagged=2`, the parent loop, and a digest. The alert is
delivered via `LogNotifier` (look for the `alerts.sent` / `digest.delivered` log lines).

### A4 — Legacy `/classify` alert path
```powershell
.\server\.venv\Scripts\python.exe -m pytest server/tests/integration/test_full_flow.py -q
```
Covers `ALERT_DIRECT → send_alert` and the always-alert/always-escalate overrides.

---

## Part B — Manual flows (real push to a phone)

### B0 — ntfy smoke test (do this first; classifier-independent)
Verifies the phone is subscribed correctly **before** involving the pipeline.
```powershell
# In server/.env set a long, unguessable topic, then subscribe the ntfy app to it:
#   ALERTS_NTFY_TOPIC=shomer-<random>
.\server\.venv\Scripts\python.exe scripts\test_ntfy.py
# or override ad-hoc:
.\server\.venv\Scripts\python.exe scripts\test_ntfy.py --topic shomer-<random> --severity critical
```
**Pass:** prints `✓ Sent (HTTP 200, id=…)` and the push appears on the subscribed phone within ~1 s.
**If it fails:** wrong topic, no network, or (private topic) missing `ALERTS_NTFY_TOKEN`.

### B1 — ntfy push through the real pipeline (digest + critical)
The fastest deterministic way: run the demo with the ntfy channel forced on. `monitor_demo.py` uses
`setdefault`, so a pre-set env var wins.
```powershell
$env:ALERTS_CHANNEL = "ntfy"
$env:ALERTS_NTFY_TOPIC = "shomer-<random>"   # same topic the phone is subscribed to
.\server\.venv\Scripts\python.exe scripts\monitor_demo.py
```
**Pass:** at the digest step the phone gets a **digest push** ("📋 …" Hebrew summary). The demo's
abusive message is *medium* severity, so it does **not** fire the immediate push — to see trigger #1,
send a `pornographic`/`hate` message live (B1-live below).

**B1-live (immediate push, real server):**
```powershell
# 1. Start a live server with ntfy enabled (fresh port; 0.0.0.0 if a phone needs LAN access):
$env:ALERTS_CHANNEL="ntfy"; $env:ALERTS_NTFY_TOPIC="shomer-<random>"; $env:DIGEST_ALLOW_MANUAL_TRIGGER="true"
.\server\.venv\Scripts\python.exe -m uvicorn server.app.main:app --host 0.0.0.0 --port 8021
# 2. In another shell, pair a device and upload (PowerShell):
$base="http://localhost:8021"
$p=irm "$base/v1/parent/register" -Method Post -ContentType application/json -Body '{"display_name":"P"}'
$ph=@{Authorization="Bearer $($p.parent_token)"}
$c=irm "$base/v1/parent/children" -Method Post -Headers $ph -ContentType application/json -Body '{"display_name":"C"}'
$code=(irm "$base/v1/parent/pairing-code" -Method Post -Headers $ph -ContentType application/json -Body (@{child_id=$c.child_id}|ConvertTo-Json)).code
$dev=irm "$base/v1/pair" -Method Post -ContentType application/json -Body (@{code=$code;device_fingerprint="pc"}|ConvertTo-Json)
$dh=@{Authorization="Bearer $($dev.device_token)"}
$txt="שלח לי תמונות עירום"   # pornographic → always-alert → high severity
$body=@{session_id="s1";child_id=$c.child_id;events=@(@{client_msg_id="e1";app_package="com.whatsapp";text=$txt;text_hash="h-$(Get-Random)";captured_at=[double](Get-Date -UFormat %s);direction="inbound"})}|ConvertTo-Json -Depth 5
irm "$base/v1/monitor/events" -Method Post -Headers $dh -ContentType application/json -Body $body
```
**Pass:** if the live classifier labels it `pornographic` (or `hate`) at ≥0.70, the phone gets the
**immediate** push during the upload call. Then `irm "$base/internal/digest/run" -Method Post` → a
**digest** push. *(With the Ollama `v1.0-standin`, labels are approximate — see Known limitations.)*

### B2 — LogNotifier default (no phone; verify the wiring)
Leave `ALERTS_CHANNEL` unset → `LogNotifier`. Run B1-live's upload and watch the server log for
`alerts.sent channel=log …` and `digest.delivered`. Confirm the alert also appears on the dashboard
(B4). This proves the *pipeline → alert → audit → dashboard* path with zero push setup.

### B3 — FCM (when a Firebase service account exists)
```powershell
# server/.env:
#   ALERTS_CHANNEL=fcm
#   FCM_SERVICE_ACCOUNT_PATH=C:\path\to\service-account.json
# and: pip install firebase-admin  (into server/.venv)
# The PARENT device must register its FCM token first:
irm "$base/v1/device/fcm-token" -Method Patch -Headers $dh -ContentType application/json -Body '{"fcm_token":"<token-from-parent-app>"}'
```
**Pass:** uploads/digests deliver to the parent device via FCM. Without a token, FCM returns
`sent=false` (queued) and never crashes — that's the documented graceful-degrade.

### B4 — Dashboard pull review/react (no push needed)
1. Open `dashboard/index.html` → Settings → Base URL (`http://localhost:8021`) + the `parent_token`.
2. The flag appears in the alerts list; open it → **react** (acknowledge / label offensive·not / severity).
3. `GET /v1/parent/labels/export` (or the dashboard export) lists labeled examples.
**Pass:** the react persists (re-list shows the new status); a labeled item appears in the export.

### B5 — Anti-storm + idempotency (observe the guards)
- **Rate-limit:** fire >`ALERTS_RATE_LIMIT_MAX_ALERTS` (default 3) alerts for one child inside the
  window → extra ones return `rate_limited=true` (no push). Metric `alert_rate_limited_total` increments.
- **Dedup:** re-POST a monitor event with the same `text_hash` → `deduped` increments, no second flag/push.
- **Idempotency:** the same `(child_id, message_id, label)` always yields the same `alert_id`
  (so a retried digest/critical push de-dupes on the device).

---

## Verification checklist (close the milestone)

- [ ] **A1** `test_push_alert_flow.py` → `2 passed` (critical-immediate + digest push proven).
- [ ] **A2** `server/tests/alerts` → `129 passed`.
- [ ] **B0** `scripts/test_ntfy.py` → push lands on the phone.
- [ ] **B1** digest push reaches the phone through the pipeline (ntfy).
- [ ] **B4** dashboard shows the flag and the react persists.
- [ ] **B5** rate-limit suppresses the 4th alert; duplicate `text_hash` is deduped.
- [ ] Negative auth holds: `/v1/monitor/events` with no Bearer → **401**; with another child's id → **403**.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| ntfy script prints "No ntfy topic" | `ALERTS_NTFY_TOPIC` unset | set it in `server/.env` or pass `--topic` |
| Push sent (HTTP 200) but phone shows nothing | phone subscribed to a different topic / notifications off | re-subscribe to the *exact* topic; check app notification permission |
| No **immediate** push but digest works | message graded `abusive` (medium) or `non_offensive` | use a `pornographic`/`hate` message (≥0.70) for trigger #1 |
| `/internal/digest/run` → 403 | manual trigger disabled | set `DIGEST_ALLOW_MANUAL_TRIGGER=true` |
| FCM alerts always `sent=false` | no service account or parent token | set `FCM_SERVICE_ACCOUNT_PATH`; `PATCH /v1/device/fcm-token` |
| `:8000` stuck after a run | orphaned background uvicorn | use a fresh `--port` (e.g. 8021) |
| Hebrew/emoji crash in console | cp1252 console | already handled (UTF-8 stdio in `main.py` + `scripts/test_ntfy.py`) |

---

## Known limitations (by design at this stage — not failures)

- **Classifier is the Ollama `v1.0-standin`** for live runs — labels are approximate until DictaBERT
  trains + `CLASSIFIER_MODEL_VERSION=v1.1-dictabert`. For deterministic push assertions use **A1**
  (stub classifier) — it proves the *delivery plumbing*, which is what this guide is about.
- **`violence`** always escalates to the Context Agent first, so its immediate push only fires after
  the CA confirms a real threat (needs an LLM key, else the mock resolves it to silent).
- **FCM over-the-wire** delivery to a real device still needs a Firebase project + the Android
  parent-mode receiver (Android pass 2). ntfy fully covers proactive push in the meantime.
- **Daily digest scheduler** is `manual` by default; set `DIGEST_BACKEND=asyncio` + `DIGEST_HOUR` for
  the real once-a-day cron. Tests/manual runs force it via `POST /internal/digest/run`.
