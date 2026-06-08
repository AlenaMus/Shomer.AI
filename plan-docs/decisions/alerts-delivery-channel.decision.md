# Alerts — Delivery Channel Strategy (ntfy.sh + web dashboard over FCM-first)

Locked 2026-06-07 after asking "does FCM cost money / what's easier?". The user
chose **web dashboard (pull) + ntfy.sh (proactive push)** as the near-term
delivery surfaces, with FCM kept available but not the priority. Builds on
[[alerts-fcm]] (the FcmNotifier adapter) and the ports-and-adapters
`NotificationChannel` + `ALERTS_CHANNEL` selection.

## D1 — Near-term delivery = web dashboard + ntfy.sh, not FCM-first

**Question:** FCM is the designed default channel but needs a Firebase
service-account, the Android client, and a device/emulator with Google Play —
none of which exist yet. What delivers alerts to a parent *now*?

**Choice:** Two free, no-Firebase surfaces:
- **Pull** — the existing parent **web dashboard** (`dashboard/index.html` →
  `/v1/parent/alerts` + daily digests). Already built (monitor track); verified
  wired. Zero new code.
- **Push** — a new **`NtfyNotifier`** (`ALERTS_CHANNEL=ntfy`) publishing to
  ntfy.sh. The parent installs the free ntfy app, subscribes to a topic, and
  gets proactive phone pushes. No account, no credential file, no device SDK.

FCM stays implemented and selectable (`ALERTS_CHANNEL=fcm`) for when the Android
client + a real service account land.

**Why:** Both are $0 and stand up in minutes; ntfy is the closest thing to "FCM
without the Firebase tax" and is fully unit-testable with `respx` (no real
account). FCM is free in dollars too, but its setup friction (service account +
Android receiver + Play-services device) is the real cost, and it's blocked on
the unbuilt client.

**Alternatives considered:**
- *FCM first* — designed default, but blocked on Android + ops setup; not
  demonstrable now.
- *Telegram bot* — equally easy/free; deferred (ntfy needs no bot setup and the
  parent app is purpose-built for notifications).
- *Email/SMTP* — good "no app install" fallback; deferred as a future adapter.
- *SMS/WhatsApp (Twilio)* — actually costs money; rejected.

**Revisit:** Promote FCM to default once the Android receiver + service account
exist; add Email/Telegram adapters if a no-app-install path is needed.

## D2 — ntfy uses JSON publish (not the header API) + httpx (no new dep)

**Question:** ntfy's simplest API puts the title in an HTTP header; how to send
Hebrew titles, and what HTTP client?

**Choice:** Use ntfy's **JSON publish** endpoint (`POST {server}` with
`{"topic","title","message","priority","tags","click"}`) via the already-present
**httpx**. Severity → ntfy priority `low→2 … critical→5`; tags carry
`[label, severity]`; optional `click` opens the dashboard; optional Bearer token
for protected/self-hosted topics.

**Why:** HTTP headers are latin-1 and would mangle Hebrew; JSON is UTF-8 and
clean. `httpx` is already a dependency — **zero new packages**. Same retry/queue/
rate-limit/audit/never-raises contract as the other channels.

**Revisit:** If publishing volume grows, reuse a long-lived `httpx.AsyncClient`
instead of one per send.
