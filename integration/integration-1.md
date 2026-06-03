# Integration Test 1 — Phase 1: Connection plumbing (text + image)

**Phase reference:** `../plan-docs/POC_Plan.md` §4 Phase 1
**Status:** ready to execute
**Last updated:** 2026-05-23
**Goal:** prove the wire — the Android client sends text **and** image payloads to the FastAPI server, the server returns a structured response in both cases. Image processing is intentionally a stub (`StubImageProcessor`); real OCR + vision arrive in `integration-2.md` / Phase 2.

---

## Architecture under test

```
[android_client]  --HTTP/JSON & HTTP/multipart-->  [FastAPI :8000]  --HTTP-->  [Ollama :11434 → offensive-hebrew:v1]
                                                          │
                                                          └── StubImageProcessor (returns fixed result)
```

What this test verifies:

| Path | Verified by |
|---|---|
| Text request → server → Ollama → JSON response | Tests T1 and A2 |
| Image upload as multipart → server stub → JSON response | Tests T2 and A3 |
| Android cleartext HTTP to local LAN | Tests A2 and A3 |
| Photo Picker on Android 13+ (no permission) | Test A3.1 |
| Camera capture with `CAMERA` permission + FileProvider | Test A3.2 |
| Server audit log: one JSON line per request + `X-Request-ID` header | Test T3 |

What this test does **not** verify (deferred to integration-2+):
- Real OCR on Hebrew images
- Real vision-LLM classification
- Strategy routing (`ocr_only`, `vision_only`, `pipeline`, `parallel`)
- Fine-tuned model accuracy (still on stand-in `qwen2.5:7b-instruct`)

---

## Prerequisites

Everything from Phase 0 must be true:

- [ ] Workspace consolidated at `C:\AIDevelopmentCourse\Shomer.AI\` (migration done 2026-05-23)
- [ ] No leftover Android Studio / Java / Gradle processes (close before running)
- [ ] Ollama installed and running on Windows (`ollama list` works)
- [ ] Python 3.11+ on the `PATH`
- [ ] Android Studio (Ladybug or newer) installed
- [ ] Emulator AVD configured **OR** physical phone on the same Wi-Fi as the PC

---

## Setup (one-time per workstation)

### S1. Recreate the server venv (broken by the migration)

```powershell
cd C:\AIDevelopmentCourse\Shomer.AI\server
Remove-Item -Recurse -Force .venv -ErrorAction SilentlyContinue
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Expected: `pip` installs `fastapi`, `uvicorn`, `httpx`, `pydantic`, `python-dotenv`, `python-multipart` without errors.

### S2. Register the stand-in model with Ollama

```powershell
ollama pull qwen2.5:7b-instruct
ollama create offensive-hebrew:v1 -f Modelfile.standin
ollama run offensive-hebrew:v1 "סווג: שלום עולם"
```

Expected: the model responds with a JSON-shaped classification.

### S3. Open the Android project from the new path

1. Android Studio → File → Open → `C:\AIDevelopmentCourse\Shomer.AI\android_client\`.
2. Let Gradle sync (Coil 2.7.0 + existing deps download).
3. If Gradle gets confused by stale caches from the old path: **File → Invalidate Caches & Restart**.

### S4. (Physical phone only) open the firewall and find the LAN IP

```powershell
# Elevated PowerShell, one-time:
New-NetFirewallRule -DisplayName "ShomerAI" -Direction Inbound -LocalPort 8000 -Protocol TCP -Action Allow

# Find your LAN IP:
ipconfig | Select-String "IPv4"
```

In the app's Settings, replace `http://10.0.2.2:8000/` with `http://<LAN-IP>:8000/`.

---

## Procedure

### T1. Server-only text smoke test

```powershell
cd C:\AIDevelopmentCourse\Shomer.AI\server
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

In a second terminal:

```powershell
curl http://localhost:8000/health
# Expect: {"status":"ok","ollama_reachable":true,"model":"offensive-hebrew:v1"}

curl -Method POST -Uri http://localhost:8000/classify `
  -ContentType "application/json" `
  -Body '{"text":"שלום, מה שלומך?"}'
# Expect: {"is_offensive": false, "category": "non_offensive", "confidence": <0..1>, "model": "offensive-hebrew:v1", "latency_ms": <int>}
```

**Pass when:** both responses come back with HTTP 200 and the JSON shape above. First `/classify` call may take 20–40 s while Ollama warms the model.

### T2. Server-only image smoke test (stub)

In the second terminal, with the server still running:

```powershell
# Any JPEG/PNG works — the stub doesn't look at the bytes.
curl.exe -F "image=@C:\Users\Dima\Pictures\anything.jpg" http://localhost:8000/classify-image
# Expect: {"is_offensive": false, "category": "stub", "confidence": 0.0, "model": "offensive-hebrew:v1", "latency_ms": <int>, "extracted_text": "", "backend": "stub", "strategy": "stub"}
```

Also test the strategy query param (accepted but ignored in Phase 1):

```powershell
curl.exe -F "image=@C:\Users\Dima\Pictures\anything.jpg" "http://localhost:8000/classify-image?strategy=ocr_only"
# Expect: same response — strategy is logged but the stub returns "stub" regardless.
```

Empty-body negative test:

```powershell
curl.exe -F "image=@NUL" http://localhost:8000/classify-image
# Expect: HTTP 400 with {"detail": "Empty image upload"}
```

**Pass when:** all three responses come back as specified.

### A1. Verify the Android build

In Android Studio:

1. Build → Make Project. Expect: BUILD SUCCESSFUL.
2. Resolve any red squigglies by re-syncing Gradle.

**Pass when:** the project compiles with no errors.

### A2. Android text path (regression — must still work after Phase 1)

1. Run the app on the emulator (Pixel 7, API 34 recommended).
2. Confirm the Settings → server URL is `http://10.0.2.2:8000/` (emulator default).
3. On the main screen, the **Text | Image** segmented toggle is visible; **Text** is selected by default.
4. Type `שלום, מה שלומך?` → tap **Classify**.
5. Result card appears with **NOT OFFENSIVE** + category + confidence + `model=offensive-hebrew:v1 • <ms>`.

**Pass when:** the response renders correctly and matches what T1's curl returned (within timing variance).

### A3. Android image path (new in Phase 1)

#### A3.1 — Photo Picker (gallery, no permission)

1. Switch the segmented toggle to **Image**.
2. Tap **Pick**.
3. System photo picker opens. Pick any image.
4. Preview appears in the screen (Coil renders the content URI).
5. Tap **Classify**.
6. Result card appears with **NOT OFFENSIVE**, Category `stub`, Confidence `0%`, footer `backend=stub • strategy=stub • <ms>`.

**Pass when:** the multipart request completes and the stub response renders.

#### A3.2 — Camera capture (permission flow + FileProvider)

1. Tap **Camera**.
2. First time only: system permission dialog appears for `CAMERA`. Tap **Allow**.
3. System camera app opens (in the emulator, this is the built-in fake camera).
4. Take a photo and confirm.
5. Preview appears.
6. Tap **Classify** — stub response renders as in A3.1.

**Pass when:** the camera intent returns and the captured image renders + uploads.

**Negative check:** revoke `CAMERA` permission (Settings → Apps → Offensive Hebrew → Permissions → Camera). Re-tap **Camera**. The permission dialog should re-appear. Tap **Deny**. Nothing should happen (no crash, no progress). Phase 2+ will add a rationale + open-settings flow; silently doing nothing is acceptable for Phase 1.

#### A3.3 — Clear & switch modes

1. With an image selected and a stub result on screen, tap **Clear**. Image preview + result should both disappear.
2. Switch toggle to **Text**, then back to **Image**. Both transitions should clear the result (but should *not* clear the text field or the selected image — those persist across mode switches by design).

---

## Pass criteria (closes integration-1)

All boxes must be ticked:

- [ ] T1: `/health` and `/classify` return the expected JSON.
- [ ] T2: `/classify-image` returns the stub JSON for valid upload **and** HTTP 400 for empty upload **and** accepts `?strategy=...` without erroring.
- [ ] A1: Android project builds with no errors.
- [ ] A2: Text classification still works end-to-end from the emulator.
- [ ] A3.1: Photo Picker → multipart upload → stub response renders.
- [ ] A3.2: Camera capture (with permission grant) → multipart upload → stub response renders.

If any box stays unticked, **do not proceed to integration-2** until the root cause is fixed.

---

## Known limitations (by design, not failures)

- The image **result is always `stub` / not offensive / 0% confidence**. That's the StubImageProcessor by design. Real classification arrives in `integration-2.md`.
- The text classifier is the stand-in `qwen2.5:7b-instruct` with a strong system prompt — accuracy on adversarial Hebrew is limited. The real fine-tuned model swap is `integration-3.md`.
- Camera-permission **denied** path is silent (no rationale dialog, no open-settings button). Phase 2 will add the full UX.
- HEIC images shot by iPhones won't decode on emulator API levels < 28. JPEG/PNG/WebP work everywhere.
- Ollama cold-start can take 20–40 s on the first request. OkHttp `readTimeout` is 60 s; tune if needed.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `curl /health` returns connection refused | Server isn't running or wrong port | Restart `uvicorn`, verify `--port 8000` |
| `curl /classify` returns 502 | Ollama unreachable | `ollama list` should include `offensive-hebrew:v1`; if not, redo S2 |
| `curl /classify-image` returns 422 | Multipart field name mismatch | Field must be `image` (matches `image: UploadFile` in `main.py`) |
| Android "Cannot reach server at http://10.0.2.2:8000/" | Server bound to `127.0.0.1` only, or firewall | Restart with `--host 0.0.0.0`; for physical phone open firewall (S4) |
| Android "CLEARTEXT communication ... not permitted" | `network_security_config` missing or wrong domain | Check `res/xml/network_security_config.xml` allows `10.0.2.2` |
| Gradle: "FileProvider authority duplicated" | Two apps with the same authority | `${applicationId}.fileprovider` should be unique; check `AndroidManifest.xml` |
| Camera button does nothing on emulator | Emulator has no camera configured | Edit AVD → Show Advanced Settings → set Front and Back cameras to `Emulated` or `Webcam0` |
| `coil.compose.AsyncImage` unresolved | Gradle sync didn't pick up the new dep | File → Sync Project with Gradle Files |
| Long load on first `/classify` | Ollama warming the model into VRAM | Expected; subsequent calls are fast |
| Hebrew text in audit log shows as `????` or `×©×œ×•×` | PowerShell 5.1 console / `Get-Content` defaults to Windows-1252 | Use `-Encoding UTF8` with `Get-Content`; for `curl` from PowerShell prefer `curl.exe -F`; for `Invoke-WebRequest` send the body as UTF-8 bytes via `[System.Text.Encoding]::UTF8.GetBytes(...)`. The file on disk is correct UTF-8. |
| No `server/logs/` folder appears after a request | `AuditLoggingMiddleware` not registered, or `AUDIT_LOG_DIR` env var points elsewhere | Confirm `app.add_middleware(AuditLoggingMiddleware)` is in `main.py`; check `AUDIT_LOG_DIR` not set or set to a writable dir |

---

## Where results live

Every execution of this plan is recorded under `results/integration-1/run-YYYY-MM-DD.md`. Don't edit old runs — they're the audit trail. See `results/README.md` for the file format and re-run convention.

---

## Appendix A — Physical-device integration (Samsung Galaxy)

Use this when you want to test on a real phone instead of (or in addition to) the emulator. Written with Samsung Galaxy in mind because that's the device on Alona's desk; deltas for Pixel and other AOSP-stock devices are called out inline.

### A.1 — Why this differs from emulator testing

| Concern | Emulator | Physical device |
|---|---|---|
| App install path | Android Studio installs the APK into the AVD over the VM bridge | Over USB (`adb install`) or Wi-Fi debugging (`adb connect`) |
| Server URL | `http://10.0.2.2:8000/` (emulator's magic alias for the host) | `http://<PC-LAN-IP>:8000/` — the alias does not exist on a real device |
| Server bind | `127.0.0.1` is fine (host & emulator share the loopback) | Must use `0.0.0.0` so the LAN can reach it |
| Firewall on PC | Loopback bypasses Windows Firewall | Inbound TCP 8000 must be allowed |
| Network | Always connected to the PC's host network | Must be on the **same Wi-Fi** as the PC, not a guest SSID, with no client isolation |
| Camera | Emulator's simulated cameras (Webcam0 / Emulated front/back) | The real Galaxy cameras |
| Photo Picker | Emulator gallery — usually a single seeded sample image | Real on-device gallery (much better for testing chat screenshots) |

### A.2 — One-time phone setup (Samsung Galaxy)

1. **Enable Developer options.** On Samsung One UI:
   Settings → About phone → **Software information** → tap **Build number** 7 times. Toast confirms "Developer mode has been enabled."
   *(Pixel / stock Android: Settings → About phone → tap Build number 7 times — no "Software information" wrapper.)*

2. **Enable USB debugging.** Settings → Developer options (now visible near the bottom of the main Settings list, or under System on Pixel) → toggle **USB debugging** ON. Tap OK on the warning dialog.

3. **Connect the phone via USB to the PC.** Use the cable that came with the phone or a known-good data cable. Cheap aftermarket cables are often charge-only and won't enumerate the phone for ADB.

4. **Accept the RSA prompt.** First time only, a dialog appears on the phone: "Allow USB debugging? — The computer's RSA key fingerprint is: …". Tick **Always allow from this computer**, tap **Allow**.

5. **Pick the right USB connection mode.** Samsung shows a notification "Android System • USB controlled by this phone for charging." Swipe down → tap the notification → choose **File transfer / Android Auto** (or **MTP**). Debugging works in any USB mode as long as it's enabled, but File transfer is the most reliable on Samsung.

6. **Verify the PC sees the phone.**
   ```powershell
   # adb ships with Android Studio's SDK. If `adb` isn't on PATH:
   $adb = "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe"
   & $adb devices
   ```
   Expect a line like:
   ```
   R58N12345ABC    device
   ```
   If you see `unauthorized` instead of `device`: unplug, replug, and watch the phone screen for the RSA dialog from step 4. If you see nothing: cable suspected first, Samsung USB driver second (`https://developer.samsung.com/android-usb-driver`), USB port third.

### A.3 — Make the PC server reachable from the LAN

Done once per server start (steps 1, 3) and once ever (step 2).

```powershell
# 1. Restart the server bound to all interfaces.
cd C:\AIDevelopmentCourse\Shomer.AI\server
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --host 0.0.0.0 --port 8000

# 2. ONE-TIME, in a SECOND, ELEVATED PowerShell: open the firewall.
New-NetFirewallRule -DisplayName "ShomerAI" -Direction Inbound -LocalPort 8000 -Protocol TCP -Action Allow

# 3. Find your PC's LAN IP.
ipconfig | Select-String "IPv4"
# Note the line for your Wi-Fi adapter, e.g.  IPv4 Address. . . . . . . . . . . : 192.168.1.42
```

### A.4 — Point the app at the PC's LAN IP

1. Make sure the phone is on the **same Wi-Fi** as the PC (same SSID, not the Guest SSID). On Samsung: Settings → Connections → Wi-Fi → check the active network name.
2. In the running app, tap the gear icon (top-right) → opens the Settings screen.
3. Replace `http://10.0.2.2:8000/` with `http://<your-PC-IP>:8000/` (the IP from A.3 step 3). End it with a slash.
4. Tap **Test connection** (if exposed) — should show `OK — status=ok, ollama=true`.

**Quick sanity check from the phone's browser** (good for ruling out Wi-Fi / firewall issues *before* blaming the app):
- Open Chrome on the phone → visit `http://<PC-IP>:8000/health`.
- Expect: the JSON body `{"status":"ok",...}` shown as text.
- If the browser fails: it's a network problem, not the app's problem.

### A.5 — Test procedure

Same A1–A3 as the emulator run, just with the physical device selected in Android Studio's device dropdown instead of an AVD. Plus one extra check:

#### A.4-physical — `client` IP in audit log

After running A2 (text classify) on the phone, check on the PC:

```powershell
Get-Content "C:\AIDevelopmentCourse\Shomer.AI\server\logs\audit-$(Get-Date -Format yyyy-MM-dd).jsonl" -Encoding UTF8 -Tail 1 |
    ForEach-Object { $_ | ConvertFrom-Json } | Select-Object client, method, path
```

**Pass when:** `client` shows the **phone's** LAN IP (e.g. `192.168.1.57`), not `127.0.0.1`. That proves the request really came over the LAN, not from loopback.

### A.6 — Vendor-specific gotchas

#### A.6a — Samsung Galaxy / One UI

- **Samsung Smart Network Switch / Adaptive Wi-Fi** can drop Wi-Fi when it judges cellular is better. Settings → Connections → Wi-Fi → ⋮ → Intelligent Wi-Fi → **Switch to mobile data** OFF during testing.
- **"USB controlled by computer" toggle.** If you see the notification say "USB controlled by **computer**" instead of "this phone", debugging may still work but file transfer won't. The label is informational; doesn't break ADB.
- **Knox / Secure Folder** does NOT block debug-build installs of regular apps. If you ever see "App not installed — Knox" it means the signing certificate changed; uninstall the old build first.
- **Samsung's "App not installed as app isn't compatible" on first install** usually means a minSdk mismatch. Shomer.AI's minSdk is 24 (Android 7.0) — any Galaxy from S6 onward is fine.
- **"Your phone is connected to a different Wi-Fi"** banner — Samsung sometimes auto-suggests a "better" network. Stay on the PC's Wi-Fi.
- **Bixby / Samsung account prompts** during first-run app launch — dismiss; they don't affect the app.
- **Samsung One UI Settings labels vary by version.** "Developer options" might be under Settings → main list, or under Settings → System depending on One UI version. Search "Developer" in Settings if unsure.

#### A.6b — Huawei EMUI (P20 Pro and similar pre-ban devices)

- **No "Software information" wrapper.** Path is shorter than Samsung: Settings → About phone → tap **Build number** 7 times directly. (On EMUI 10+: Settings → System & updates → About phone → Build number.)
- **HiSuite (Huawei's PC companion app) hijacks USB.** If installed, it intercepts the USB connection and Android Studio can't see the phone. Either uninstall HiSuite or disable its auto-launch behaviour: phone → Developer options → **HDB** OFF (HDB is what HiSuite uses; turning it off forces standard ADB).
- **Default USB mode is "Charge only".** On every connect, swipe down the notification shade → tap "Charging via USB" → choose **Transfer files** (or **Transfer photos**). ADB technically works in Charge-only too, but only after debugging is on **and** the OEM USB driver is loaded — Transfer files is the more reliable initial state.
- **"Allow access to phone data" prompt** appears on first connect in Transfer files mode — tap **Allow**.
- **Huawei USB driver on Windows.** Windows usually auto-installs it, but if `adb devices` shows nothing even with debugging on and the phone awake, install the Huawei Mobile Drivers package from `consumer.huawei.com/.../driver`. Avoid installing HiSuite to get the driver — it brings the hijacking problem.
- **EMUI battery protection** can suspend apps in the background. Not a problem during foreground testing, but if you minimise the app and come back to find it crashed, check Settings → Apps → Offensive Hebrew → Battery → set to **No restrictions**.
- **Photo Picker (PickVisualMedia) may fall back to the legacy gallery picker.** PickVisualMedia is native on API 33+ and backported via Google Play Services for older APIs. The P20 Pro's Play Services hasn't been updated since the ban (~mid-2019), so the modern Photo Picker UI may not appear — instead you'll see the older "Files" / "Gallery" chooser. Functionally identical for our purposes: it returns a content `Uri` that the app can read. Don't treat the older UI as a bug.
- **Google Photos may not be installed by default on EMUI** — the system gallery is "Gallery" (Huawei's). Same outcome from a `Uri` perspective.
- **EMUI's "App Twin / Parallel Apps"** doesn't affect debug installs.
- **`adb devices` keeps showing `unauthorized` on EMUI** — toggle USB debugging OFF and ON in Developer options; the RSA dialog should re-appear on the phone screen. If it doesn't, run `adb kill-server; adb start-server` from PowerShell and replug.
- **EMUI's "Trust this computer?" dialog** is separate from the RSA prompt. Approve it too.

### A.7 — *(Optional)* Wireless debugging instead of USB (Android 11+)

After A.2 step 6 succeeded once over USB, you can switch to wireless for daily use:

```powershell
# On the phone: Settings → Developer options → Wireless debugging → ON.
# Tap "Pair device with pairing code." Phone shows IP:port and a 6-digit code.

& $adb pair <phone-ip>:<pair-port>      # enter the 6-digit code when prompted
& $adb connect <phone-ip>:<connect-port>  # from the main Wireless debugging screen
& $adb devices                            # confirm the device appears
```

Useful when you don't want to keep the phone tethered. After a phone reboot you usually need to `adb connect` again.

---

## After this passes — what's next

Mark integration-1 as **done**. Then either:

1. **integration-3 first (recommended path)** — train the real Hebrew classifier so Phase 2's OCR backend has something good to feed. Less rework downstream.
2. **integration-2 next (alternative)** — wire up real OCR + vision backends while the stand-in text model is still in place. Useful if training is blocked on GPU access.

The choice belongs to `POC_Plan.md` §4; this file just hands off when Phase 1 is verifiably green.
