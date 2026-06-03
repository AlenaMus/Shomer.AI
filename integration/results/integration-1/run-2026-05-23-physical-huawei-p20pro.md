# integration-1 run — 2026-05-23 — physical Huawei P20 Pro

**Status:** ✅ **PASS** — all setup steps completed and all A1–A4-physical tests verified by Alona.
**Machine:** Windows 11 Pro, user `Dima`, owner Alona.
**Phone:** Huawei P20 Pro (typical model codes `CLT-L09` / `CLT-L29`; capture exact value in §1).
**Test plan:** `../../integration-1.md` (main procedure) + Appendix A (physical-device).
**Driven by:** Alona; Claude is guiding via chat and updating this file as steps complete.

> Earlier run `run-2026-05-23.md` covers the **emulator** target and is being closed separately. This file covers only the **physical Huawei P20 Pro** target. If anything fails irrecoverably in this run, create `run-2026-05-23-physical-huawei-p20pro-2.md` rather than editing this one.

---

## 1. Environment snapshot (to fill in as we go)

| Component | Version / value |
|---|---|
| Phone model | Huawei P20 Pro — **`CLT-L29`** (international variant) |
| Android version / EMUI | EMUI **12.0.0** (Android version TBD — pre-Block 3 capture from About phone). *Note:* EMUI 12 on a CLT-L29 is non-standard internationally; could be a late-OTA, custom ROM, or regional variant. Doesn't block testing. |
| Google Play Services version | _TBD_ (Settings → Apps → Google Play Services → version). Matters because Photo Picker backport needs a recent Play Services; P20 Pro's hasn't updated since ~2019 |
| USB cable in use | _TBD_ |
| Connection method | USB / Wireless debugging |
| PC LAN IP at test time | **`192.168.68.101`** |
| Phone LAN IP at test time | _TBD_ (capture from audit log) |
| Wi-Fi SSID (phone & PC) | _TBD — must match, must NOT be guest_ |
| Server `--host` | `0.0.0.0` |
| Firewall rule "ShomerAI" inbound :8000 | **Created** — `Enabled: True`, `PrimaryStatus: OK`, profile Any |
| Reused emulator env (Python 3.12, fastapi 0.136.1, …) | Yes — see `run-2026-05-23.md` §1 |

---

## 2. Setup steps

### A.2.1 — Enable Developer options on phone ✅

- [x] Settings → About phone → tap **Build number** 7 times. (EMUI 10+: Settings → System & updates → About phone → Build number.)
- [x] Toasts count down: "You are now N steps away…" → final "You are now a developer."

### A.2.2 — Enable USB debugging ✅ (per user)

- [x] Settings → Developer options → **USB debugging** ON.
- [ ] (Huawei-specific) If you have **HDB** toggle in Developer options → leave OFF (HDB is used by HiSuite and can hijack USB). *(Not yet verified — confirm in Block 2 via `adb devices` outcome.)*

### A.2.3 — Connect phone via USB + accept RSA ✅

- [x] USB cable plugged into PC.
- [x] Phone in **Transfer files / Transfer photos** mode.
- [x] "Allow USB debugging?" RSA dialog accepted (inferred from Block 2 `device` status).
- [x] HDB toggle confirmed not interfering.

### A.2.4 — Verify `adb devices` sees the phone ✅

- [x] `adb devices` showed the phone as `device` (not `unauthorized`).
- [x] Phone serial: **`WCR7N18B09005537`**
- [x] An emulator (`emulator-5554`) was also visible — fine, just means an AVD is running too. Android Studio will prompt to pick the target when you Run.

### A.3.1 — Restart server bound to 0.0.0.0 ✅

- [x] `uvicorn app.main:app --host 0.0.0.0 --port 8000` running cleanly in a PowerShell window.

### A.3.2 — Firewall rule for inbound TCP 8000 ✅

- [x] Rule created via `New-NetFirewallRule -DisplayName "ShomerAI" ...`. `Enabled: True`, `PrimaryStatus: OK`.

### A.3.3 — PC LAN IP captured ✅

- [x] `ipconfig` → recorded IP: **`192.168.68.101`**

### A.4.1 — Phone on same Wi-Fi as PC ✅

- [x] Phone Wi-Fi SSID matches PC's (proven by A.4.2 succeeding).

### A.4.2 — Browser sanity check: `http://192.168.68.101:8000/health` ✅

- [x] Chrome on phone opened the URL → correct Ollama health JSON returned.

### A.4.3 — App Settings updated to PC IP ✅

- [x] In-app gear icon → Settings → URL changed to `http://192.168.68.101:8000/`.
- [x] Connection verified (Test connection / first classify request succeeded).

---

## 3. Test procedure (A1–A3, plus A4-physical)

### A1 — Project builds & installs to physical phone via Android Studio ✅

- [x] In Android Studio's device dropdown, the physical Huawei P20 Pro was selected.
- [x] Run (▶) succeeded — APK installed, app launched on the phone.

### A2 — Text path on the phone ✅

- [x] Non-offensive Hebrew sentence → result card showed **NOT OFFENSIVE / non_offensive**.
- [x] Offensive Hebrew sentence → result card showed **OFFENSIVE** with a category.

### A3.1 — Photo Picker upload ✅

- [x] Image mode → Pick → gallery opened → photo chosen.
- [x] Preview rendered.
- [x] Classify → stub response card displayed as expected.

### A3.2 — Camera capture ✅

- [x] Camera permission granted on first tap.
- [x] Huawei Camera opened → photo captured + confirmed.
- [x] Preview rendered.
- [x] Classify → stub response card displayed as expected.

### A4-physical — Audit log shows phone's LAN IP as `client` ✅

```powershell
Get-Content "C:\AIDevelopmentCourse\Shomer.AI\server\logs\audit-2026-05-23.jsonl" -Encoding UTF8 -Tail 5 |
    ForEach-Object { $_ | ConvertFrom-Json } | Select-Object client, method, path
```

- [x] Audit log records show phone-LAN-IP `client` for the requests issued from the phone.

---

## 4. Pass criteria

- [x] **A1** — APK installs and runs on the physical Huawei P20 Pro
- [x] **A2** — text classification works from the phone (NOT OFFENSIVE + OFFENSIVE both reachable)
- [x] **A3.1** — Photo Picker → multipart upload → stub response
- [x] **A3.2** — Camera capture with permission → stub response
- [x] **A4-physical** — audit log records the phone's LAN IP as `client`

---

## 5. Defects / follow-ups (fill in as observed)

_(Empty until issues come up.)_

---

## 6. Sign-off (fill in at the end)

| Block | Status |
|---|---|
| Setup (A.2–A.4) | ✅ PASS |
| Tests (A1–A4-physical) | ✅ PASS |
| **Overall physical-device integration-1** | **✅ PASS** |

**Recommendation:** integration-1 is verifiably green on both targets (emulator via `run-2026-05-23.md`, physical Huawei P20 Pro via this file). Phase 1 is done. Next phase: **integration-2 / POC Phase 2** — pluggable image backends (Tesseract OCR + vision LLM via Ollama) + strategy router. After that, the same A3.1 / A3.2 tests will return *real* classifications instead of `backend=stub`.
