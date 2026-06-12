# Integration Test — Screenshot → Server OCR (open-chat capture)

**Feature:** capture chat screenshots on the child device → upload to
`POST /v1/monitor/image` → server Tesseract OCR → **per-line** classify → triage → flag.
**Decision:** `../plan-docs/decisions/screenshot-ocr-capture.decision.md`
**Why screenshots:** WhatsApp message bubbles are invisible to the accessibility tree
*and* to notifications, so on-screen capture + server OCR is the only path to read them.

This complements `integration-monitor.md` (which covers the text/accessibility path).

---

## What is already verified (server side, automated)

| Check | How | Result |
|---|---|---|
| Endpoint contract (auth, blank, flag, dedup, 401/403) | `pytest server/tests/monitor/test_monitor_image.py` | 6/6 ✅ |
| OCR line-segmentation | `pytest server/tests/ocr/test_tesseract_adapter.py` | ✅ |
| **Real Tesseract** OCR on a Hebrew chat screenshot | `scripts/test_image_endpoint.py` | reads Hebrew (102–107 chars) ✅ |
| **Real DictaBERT** end-to-end screenshot → parent flag | same script | `flagged≥1`, parent alert appears ✅ |

> **Key fix (2026-06-11):** the endpoint used to OCR the whole screen into ONE
> classification event, which **diluted** a lone offensive line below threshold
> (verified: isolated line `is_offensive=True@0.73`, whole-screen blob
> `False@0.55`). It now emits **one MonitorEvent per OCR line** (timestamps /
> chrome filtered). See the decision doc Revisit section.

---

## Device-side test (interactive — physical phone)

Device under test: Huawei **CLT-L29** (P20), Android 10. `com.shomer.client` installed.

### Connectivity: `adb reverse` (no firewall admin needed)
The phone reaches the PC server over the USB cable — no LAN firewall rule required:
```powershell
adb reverse tcp:8011 tcp:8011          # phone 127.0.0.1:8011 -> PC :8011
adb reverse --list                     # expect: usb tcp:8011 tcp:8011
```
> `adb reverse` does NOT survive a USB unplug or device reboot — re-run it if either happens.
> App base URL with the tunnel: **`http://127.0.0.1:8011/`**.
> (Alternative — Wi-Fi: app base URL `http://192.168.68.100:8011/` + an **admin** firewall
> rule `New-NetFirewallRule -DisplayName Shomer8011 -Direction Inbound -LocalPort 8011 -Protocol TCP -Action Allow`.)

### Server + pairing (already running on :8011)
```powershell
# (server is up; if not)  DIGEST_ALLOW_MANUAL_TRIGGER=true python -m uvicorn server.app.main:app --host 0.0.0.0 --port 8011
python scripts/stage_device_pairing.py            # prints a fresh 10-min OTP + parent_token
```

### Steps on the phone
1. **Open the Shomer app** → Settings → set Base URL to `http://127.0.0.1:8011/`.
2. **Consent** screen → accept (note it discloses screen capture + inbound/outbound).
3. **Pair** → enter the OTP from `stage_device_pairing.py`. App shows the paired `child_id`.
4. **Grant AccessibilityService** (deep-links to Settings → Shomer → enable).
5. **Grant screen capture**: tap "Start screen capture" → accept the system
   **"Start now"** MediaProjection dialog. A non-dismissible "Screen capture active"
   notification appears. *(This dialog cannot be granted via adb — one physical tap.)*
6. **Grant** POST_NOTIFICATIONS + battery exemption if prompted.
7. **Open WhatsApp** (a monitored app) and view a chat showing Hebrew text. For a
   controlled trigger, send yourself (or a test contact) the line:
   **`כולם שונאים אותך תתאבד`** (reliably flags). Keep the chat on screen ~2 s
   (the capture debounces 1.5 s after the last screen change).

### Pass criteria
- Server log (`server/logs/device_test_8011.log`) shows, in order:
  `monitor.image_received` → `ocr_success` → `monitor.image_segmented` → `monitor.batch_processed flagged≥1`.
- The captured bullying line appears at `GET /v1/parent/alerts` (and in `dashboard/index.html`).
- The app's uploaded-screenshot counter increments on the Status screen.

### Known, by-design at this stage (not failures)
- **`adb reverse` lifetime** — re-run after unplug/reboot.
- **Huawei EMUI** aggressively kills background services — disable battery optimization
  for Shomer, or capture may stop when the screen locks.
- **Classifier calibration** — raw softmax over-escalates: some benign lines (e.g.
  `נתראה מחר בבית ספר`) flag, and a mild insult labelled `violence` is force-escalated
  to the Context Agent and may be silenced. Calibration + the violence→CA rule are
  tracked separately from this feature (CLAUDE.md classifier caveats).
- OCR garbles some characters (`תתאבד`→`תתאהז`, niqqud) but offensive tokens survive
  and still flag — Tesseract accuracy on chat bubbles is acceptable for the MVP.
