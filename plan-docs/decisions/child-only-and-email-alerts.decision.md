# Child-only Android + Parent email alerts (Gmail API) — Decisions & Tasks

**Decided:** 2026-06-12 by Alona. Implemented in parallel by `android-developer` + `backend-developer`.

---

## D-CO-1 — Android app is CHILD-ONLY; the web dashboard is the parent surface

**Question:** Should the Android app keep its parent mode, or be child-only?

**Choice:** **Child-only.** Remove the role chooser and ALL parent-mode flows from the Android client
(parent auth, alert list/detail/react, digest screen, `ShomerFcmService`). The app launches straight into
child onboarding (consent → pairing → permissions → monitoring). Parents use the **web dashboard**
(`dashboard/index.html`) for review and receive **email** notifications (D-CO-2).

**Why:** one parent surface (web) is simpler than maintaining parent UI on two platforms; the dashboard
already covers alerts + react + digest; child-only shrinks the app's permission/attack surface.

**Revisit:** if a native parent app is ever wanted, restore from git history.

---

## D-CO-2 — Parent notifications via the Gmail API (OAuth2)

**Question:** How do parents get notified of alerts now that there's no parent app?

**Choice:** **Email via the Gmail API (OAuth2).** A new `GmailApiNotifier` adapter on the existing alerts
notifier port; selected with `ALERTS_CHANNEL=email`. Parent email is captured at `/v1/parent/register` and
stored in the identity store. On an alert, the server resolves child → parent(s) → email and sends.
`LogNotifier` stays the default/dev fallback; `FcmNotifier` remains an adapter but is no longer the parent
path.

**Why:** the user chose Gmail; OAuth2 + `gmail.send` scope avoids app-passwords and uses the user's own
Gmail. Adapter pattern keeps it a one-line composition-root swap.

**Trade-off / one-time setup (user):** requires a Google Cloud project with the Gmail API enabled, a
"Desktop" OAuth client JSON, and a one-time browser consent (`scripts/gmail_oauth_setup.py`) to mint the
stored refresh token. The agent builds the code + script + docs; provisioning the credential is the user's
one-time step.

**Revisit:** if deliverability/limits become an issue, swap the adapter for SES/SendGrid (no other code
changes — same port).

---

## Task breakdown

### Android (`android-developer`) — make it child-only
1. Remove the role chooser; start destination = child onboarding.
2. Delete parent screens + ViewModels + nav routes: parent auth (register/paste token), alert list, alert
   detail, react (ack/label/severity), digest.
3. Remove `ShomerFcmService` + FCM/google-services parent wiring (was opt-in).
4. Remove parent-only `ApiService` methods (register/alerts/react/digests) if unused; keep child endpoints
   (`/v1/pair`, `/v1/monitor/events`, `/v1/monitor/image`).
5. Keep child onboarding, pairing, AccessibilityService capture (+ the new `conversation_id` work), consent,
   permissions, monitoring indicator, `MonitorUploader`.
6. Build `client` flavor; report result. Decision note in `android_client/design.md`.

### Server (`backend-developer`) — Gmail API email alerts
1. Deps: `google-auth`, `google-auth-oauthlib`, `google-api-python-client`.
2. Parent email: already captured at `/v1/parent/register` + persisted in identity store (both adapters).
   `get_parent_email(parent_id)` + `parent_for_child(child_id)` chain is the resolution path.
   SQLite adapter already has the idempotent `email` column migration (`_MIGRATE_EMAIL`).
3. `GmailApiNotifier` adapter at `server/app/alerts/gmail_notifier.py`:
   - RFC 822 MIME, Hebrew subject + body, `base64.urlsafe_b64encode`, `users.messages.send`.
   - Credentials loaded from `GMAIL_TOKEN_JSON` (default `gmail_credentials/token.json`).
   - Auto-refresh via `google.auth`; persists refreshed token back to file.
   - Sender resolved via `ALERT_FROM` env var or Gmail `users.getProfile`.
   - Injectable `send_fn` for tests (no real network in CI).
   - Graceful fallback: any failure → `AlertResult(sent=False, error=...)`, never raises.
4. `scripts/gmail_oauth_setup.py`: one-time consent helper; detects existing refresh_token and skips
   re-consent; `--verify` mode; `--smoke <email>` sends one live test email.
5. Composition root (`main.py lifespan()`): `ALERTS_CHANNEL=email` selects `GmailApiNotifier`.
   `_dispatch_alert` branches on `isinstance(notifier, GmailApiNotifier)`, resolves
   child→parent→email via `app.state.identity`, falls back to warn+return when no email registered.
6. Tests:
   - `server/tests/alerts/test_gmail_notifier.py` — unit tests (happy path, rate-limit, MIME,
     missing-token, missing-google-auth, audit recorder, retry/queue, health_status).
   - `server/tests/identity/test_email_registration.py` — email persistence + resolution contract
     tests, parametrized over InMemory + SQLite adapters.
   - `server/tests/integration/test_email_alert_channel.py` — composition + dispatch integration.
7. `server/.env.example` updated with `GMAIL_CLIENT_JSON`, `GMAIL_TOKEN_JSON`, `ALERT_FROM`.

**Implementation status (2026-06-12):** DONE. All new tests pass. `gmail_credentials/` is git-ignored.
