# Manual Testing Guide — Shomer.AI Android App ↔ Server

A hands-on, step-by-step guide to manually test the real monitoring app against the live server.
Follow it top to bottom; each test has **steps** and **expected results** with checkboxes.

- **App:** `android_client/` — `com.shomer.client` (the `client` flavor). Child-mode (capture) + parent-mode (review/react).
- **Server:** FastAPI at `server/app/` — endpoints `POST /v1/monitor/events`, `/v1/pair`, `/v1/parent/*`, `/internal/digest/run`.
- **Companion docs:** `../integration/integration-monitor.md` (formal pass criteria) · `../dashboard/README.md` (web dashboard) · `design.md` (app architecture).

> **What's a stub today (by design — not a bug):** the classifier is the Ollama `v1.0-standin`, so
> labels are approximate (DictaBERT not trained yet); the daily digest scheduler is manual (trigger
> via `/internal/digest/run`); push is `LogNotifier` (no real FCM until a Firebase project exists).
> This guide tests the **plumbing**, not classification accuracy.

---

## 0. Prerequisites

| # | Requirement | Check |
|---|---|---|
| 0.1 | Repo at `C:\AIDevelopmentCourse\Shomer.AI`, server venv at `server/.venv` | |
| 0.2 | Ollama running (the stand-in classifier transport): `ollama list` shows `offensive-hebrew:v1` | |
| 0.3 | Android Studio installed (bundled JDK/JBR) | |
| 0.4 | A target: **emulator** (Pixel API 34+) OR a **physical Android phone** (API 24+) | |
| 0.5 | For a physical phone: phone + PC on the **same Wi-Fi**; you know the PC's LAN IP (`ipconfig` → IPv4) | |
| 0.6 | At least one messaging app installed on the test device: **WhatsApp** / Instagram / Telegram / Messenger | |

---

## 1. Start the server

Run in a **foreground** PowerShell window (keep it open to watch logs):

```powershell
cd C:\AIDevelopmentCourse\Shomer.AI
$env:DIGEST_ALLOW_MANUAL_TRIGGER = "true"
.\server\.venv\Scripts\python.exe -m uvicorn server.app.main:app --host 0.0.0.0 --port 8000
```

- `--host 0.0.0.0` lets a physical phone reach the server (not just localhost).
- Wait for the `server_ready` log line.

**Physical phone only — one-time firewall rule** (elevated PowerShell):
```powershell
New-NetFirewallRule -DisplayName "ShomerServer" -Direction Inbound -LocalPort 8000 -Protocol TCP -Action Allow
```

- [ ] `GET http://localhost:8000/health` in a browser returns `{"status":"ok",...}`.
- [ ] Physical phone: open `http://<PC-LAN-IP>:8000/health` in the phone's browser → same JSON. (If it
      times out: firewall rule missing, or different Wi-Fi networks.)

**Server base URL the app will use:**
| Target | Base URL |
|---|---|
| Emulator | `http://10.0.2.2:8000/` (the app's default — `10.0.2.2` is the emulator's alias for the host PC) |
| Physical phone | `http://<PC-LAN-IP>:8000/` (e.g. `http://192.168.1.50:8000/`) — set this in the app's Settings |

---

## 2. Build & install the app

From `android_client/` (set `JAVA_HOME` to Android Studio's bundled JBR if Gradle can't find a JDK):

```powershell
cd C:\AIDevelopmentCourse\Shomer.AI\android_client
$env:JAVA_HOME = "C:\Program Files\Android\Android Studio\jbr"

# If a pre-flavors POC build is already on the device, uninstall it first (one time):
adb uninstall com.dima.offensivehebrew   # ignore "Unknown package" if not installed

# Build + install the real client flavor:
.\gradlew.bat installClientDebug
```

Or in **Android Studio**: open the `android_client/` folder (NOT `app/`), pick the **clientDebug**
build variant (Build Variants panel), select your emulator/device, press Run.

- [ ] App installs and launches; you see the **"Who is using this device?"** role chooser.

> **Two test roles, two installs:** child-mode and parent-mode are the same app picking a role at
> first launch. To test both on one device you can reuse one install for the child and the **web
> dashboard** (`dashboard/index.html`) as the parent surface — or use two devices/emulators.

---

## 3. Mint a pairing code (the parent side of onboarding)

There's no "create child" screen yet, so generate the parent token + child + OTP with the helper
(server must be running):

```powershell
cd C:\AIDevelopmentCourse\Shomer.AI
.\server\.venv\Scripts\python.exe scripts\make_pairing_code.py
# (physical phone server on a different host? add  --base http://<PC-LAN-IP>:8000)
```

It prints:
```
  PAIRING CODE (type this into the child device):
      >>>  314018  <<<
  parent_token (dashboard / parent-mode app): kPkG...long...token
  child_id  : a3034117-...
```

- [ ] You have a **6-digit code** and a **parent_token**. (Code expires in ~10 min, single-use.)

*(Manual alternative without the helper: see `../integration/integration-monitor.md` §S2 for the raw
`/v1/parent/register` → `/children` → `/pairing-code` PowerShell.)*

---

## 4. CHILD-MODE tests

### TC1 — Server connectivity
1. Role chooser → **"This is my child's device"**.
2. If on a physical phone: first go to **Settings** (gear) and set the Server URL to
   `http://<PC-LAN-IP>:8000/`, tap **Save**, then **Test Connection**.
- [ ] Test Connection reports success (or `/health` is reachable).

### TC2 — Consent
1. The **Parental Monitoring Consent** screen appears.
2. Read it — confirm it states **both inbound (received) and outbound (sent)** messages are checked.
3. Tick both boxes (guardian consent + child informed) → **I Understand — Continue**.
- [ ] Continue is disabled until **both** boxes are ticked.
- [ ] Consent text explicitly mentions WhatsApp/Instagram/Telegram/Messenger and inbound+outbound.

### TC3 — Pairing
1. On the **Pair This Device** screen, type the 6-digit code from step 3 → **Pair Device**.
- [ ] "Device paired successfully"; the app advances.
- [ ] Server log shows `identity.pair_endpoint_success child_id=...`.
- [ ] **Negative:** a wrong/expired code → an error, not a crash.

### TC4 — Permissions
1. **Accessibility:** tap **Open Accessibility Settings** → find **"Shomer.AI Monitoring Service"** →
   enable it → accept the system warning → back to the app.
2. **Notifications:** allow (Android 13+).
3. **Battery:** **Open Battery Settings** → set Shomer.AI to "Don't optimize".
- [ ] The app detects accessibility is **enabled** (status flips to enabled on return).
- [ ] A persistent, **non-dismissible** notification **"Shomer.AI is monitoring"** appears in the shade.

### TC5 — Capture & upload (the core)
1. On the **Status** screen, ensure **Monitoring Active** (toggle on). Note the paired Child ID and the
   Captured/Uploaded counters.
2. Open **WhatsApp**. In any chat, **receive or send a Hebrew message** with a clearly offensive phrase,
   e.g. `אתה מטומטם ואני שונא אותך` (send it to yourself or a test contact).
3. Return to Shomer.AI (or pull down the shade to keep it alive). Wait for the upload.
- [ ] The **Captured** counter increments after the Hebrew message.
- [ ] The **Uploaded** counter increments (upload runs on a ~15-min periodic worker **and** an expedited
      trigger; to force it immediately, toggle Monitoring off/on, or just wait).
- [ ] Server log shows `monitor.batch_received` then `monitor.flagged ... label=... flag_status=...`.
- [ ] Send a **benign** Hebrew message (`נתראה מחר`) → it is captured but **not** flagged (server logs
      `triage_decision=silent`, no `monitor.flagged`).
- [ ] Send an **English** message → it is **dropped on-device** (pre-filter; never uploaded — no
      counter change, no server log).

### TC6 — Confirm the flag reached the server
```powershell
# Using the parent_token from step 3:
$ph = @{ Authorization = "Bearer <parent_token>" }
irm "http://localhost:8000/v1/parent/alerts?include_acked=true" -Headers $ph
```
- [ ] The offensive message appears as a flag: matching `quote`, `app_package=com.whatsapp`, a
      `direction`, and a `status` of `alerted` (or `review_needed` if the stand-in was unsure).

---

## 5. PARENT-MODE tests

Use **either** the Android parent-mode **or** the web dashboard — both hit the same API.

### Option A — Web dashboard (fastest)
1. Open `dashboard/index.html` in a browser → **הגדרות (Settings)** → Base URL `http://localhost:8000`
   + the **parent_token** → Save.
- [ ] **התראות (Alerts)** lists the flag from TC5; the borderline `review_needed` items are visually distinct.

### Option B — Android parent-mode
1. On a second device/emulator (or a fresh install): role chooser → **"I am a Parent"** →
   **Create Account** (or paste the parent_token under "Existing Token").
- [ ] The **Alert List** loads the flag(s); pull-to-refresh works; filter chips (All / Needs Review /
      Alerted / Done) re-query.

### TC7 — Review & react
1. Open a flagged item (ideally a `review_needed` one) → **Alert Detail**: quote + explanation + metadata.
2. Try each react action:
   - **Acknowledge** → status becomes `acknowledged`.
   - **Label** → **offensive** / **not_offensive** → status becomes `labeled`, `parent_label` set.
   - **Severity** → pick low/med/high/critical → `parent_severity` set.
- [ ] Each action persists (re-open / re-list shows the new status).
- [ ] `GET /v1/parent/labels/export` (with the parent token) includes any item you labeled — this is the
      DictaBERT training feedback loop.

### TC8 — Daily digest
1. Build today's digest (the scheduler is manual in dev):
   ```powershell
   irm "http://localhost:8000/internal/digest/run" -Method Post
   ```
2. Dashboard **סיכום יומי (Digest)** with today's date, **or** Android **Digest** screen.
- [ ] The digest shows `total_flagged`, `review_needed`, and `by_severity` / `by_label` breakdowns
      consistent with what you sent in TC5.

### TC9 — Dedup
1. In WhatsApp, send the **exact same** offensive message text again.
- [ ] On the next upload, the server reports it as **deduped** (server log `monitor.deduped`; the batch
      response `deduped` count increments) — no second flag for the identical text.

---

## 6. Negative / security checks

- [ ] **No token:** `irm http://localhost:8000/v1/monitor/events -Method Post -Body '{}' -ContentType application/json` → **401**.
- [ ] **Wrong child:** posting a batch whose `child_id` differs from the device token's child → **403**
      (see `../integration/integration-monitor.md` §S3 for the exact call).
- [ ] **Parent endpoint with a child token** → **403**; **child endpoint with a parent token** → **403**.
- [ ] **Privacy:** a benign/English message leaves **no content** server-side (only captured-and-dropped
      on device, or classified-and-not-stored) — confirm with `python scripts/inspect_audit.py`.

---

## 7. Pass criteria (manual sign-off)

- [ ] TC1–TC9 pass on at least one target (emulator or physical phone)
- [ ] An offensive Hebrew message sent in a real app appears as a flag on a parent surface
- [ ] The parent react loop persists (acknowledge / label / severity)
- [ ] The daily digest reflects the day's flags
- [ ] All negative/security checks (§6) hold
- [ ] Record the run under `../integration/results/integration-monitor/run-YYYY-MM-DD.md`

---

## 8. Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| App can't reach server (Test Connection fails) | Emulator must use `10.0.2.2`, never `localhost`/`127.0.0.1`. Physical phone: set `<PC-LAN-IP>`, add the firewall rule, same Wi-Fi, server started with `--host 0.0.0.0`. |
| `INSTALL_FAILED_UPDATE_INCOMPATIBLE` | An older POC APK with the same id is installed — `adb uninstall com.dima.offensivehebrew` then reinstall. |
| Gradle "no JDK" / build fails | `$env:JAVA_HOME = "C:\Program Files\Android\Android Studio\jbr"` before `gradlew`. |
| Accessibility toggle won't stick / no capture | Re-enable "Shomer.AI Monitoring Service" in Settings → Accessibility; disable battery optimization; keep the foreground notification alive. Some OEMs aggressively kill services. |
| Captured but never uploaded | Upload is periodic (~15 min) + expedited. Force it: toggle Monitoring off/on; ensure network; check `isPaired()` (must have completed TC3). |
| Hebrew message captured but not flagged | Expected for benign text. For offensive text, remember the classifier is the **stand-in** — labels are approximate until DictaBERT is trained. Use a clearly-abusive phrase. |
| Pairing code rejected | Codes expire in ~10 min and are single-use — mint a fresh one (step 3). |
| 401 on every parent call | Wrong/expired parent_token — mint a new one, or re-create the account in parent-mode. |
| Digest is empty / 404 | Run `POST /internal/digest/run` first (manual scheduler in dev); use **today's** date `YYYY-MM-DD`. |

---

## 9. Known limitations at this stage (don't file as bugs)

- Classifier = Ollama `v1.0-standin` (approximate labels); DictaBERT not trained.
- Daily digest scheduler is `manual` (`DIGEST_BACKEND=asyncio` + `DIGEST_HOUR` to enable the real cron).
- Push = `LogNotifier` (no device push until a Firebase project + `google-services.json` + `ALERTS_CHANNEL=fcm`).
- `MONITOR_STORE_RAW=false` not yet enforced (raw text still persisted server-side) — S5.
- Direction inference is heuristic (defaults to inbound); per-app accuracy improves in Android A5.
- Apps that render text in Canvas (some Snapchat/IG surfaces) need the MediaProjection+OCR fallback — Android A5, not yet built.
- Upload cadence is ~15 min (WorkManager minimum) + expedited; not real-time by design (battery).
