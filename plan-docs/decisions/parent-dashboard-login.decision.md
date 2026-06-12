# Decision — Parent web dashboard: login + per-child separation + email-OTP onboarding

**Date:** 2026-06-12
**Status:** Implemented on branch `feature/parent-dashboard-login` (merge pending user approval)
**Note:** D1 (below) was implemented with `username` as the login identifier; superseded the same
day by D2 — **email** is the login identifier and the OTP onboarding channel. D1's mechanics
(PBKDF2, token reuse, StaticFiles, mandatory child selection) all carry over unchanged.

---

## Question

How should parents access the web dashboard — and how is per-child data separation surfaced?
(User request: URL-accessible webapp, login with username+password, full alert separation by
choosing a child *by name*, English "Shomer.AI" logo, centered login page.)

## Choice

1. **Auth = username/password on top of the existing opaque parent-token system.**
   `POST /v1/parent/login {username, password}` → the same `parent_token` all parent endpoints
   already accept. `POST /v1/parent/register` gains optional `username`+`password`
   (display-name-only registration kept for Android back-compat). Passwords hashed with
   stdlib **PBKDF2-SHA256 (600k iterations, per-user salt)** in `identity/passwords.py`;
   both `SqliteIdentityStore` and `InMemoryIdentityStore` implement the new
   `authenticate_parent_credentials` protocol method. Idempotent SQLite migration
   (ALTER TABLE + partial unique index on username).
2. **Dashboard served by FastAPI** at `http://<host>:8000/dashboard/` (StaticFiles mount,
   `GET /` → 302 to it). `/v1/parent/login` and `/dashboard*` added to the
   `DeviceAuthMiddleware` allowlist (static page public; data calls Bearer-authed).
3. **UI: mandatory child-by-name selector.** After login the dashboard fetches
   `GET /v1/parent/children` and renders name chips; *every* alerts/digest request carries the
   selected `child_id` — no "all children" view, no free-text child-id inputs. Server-side
   isolation was already enforced (`_owned_child_ids` → 403/404 for foreign children) and is
   covered by `server/tests/parent/test_cross_parent_isolation.py`.
4. **Login screen centered**, English LTR **"Shomer.AI"** wordmark on login card + header;
   rest of UI stays Hebrew RTL. Single self-contained `dashboard/index.html` (no build step).

## Why

- Reusing the opaque parent-token as the session credential means **zero changes** to the
  existing parent endpoints, the Android parent mode, or the auth middleware — login only adds
  a new way to *obtain* the token.
- PBKDF2 via `hashlib` avoids a new dependency (bcrypt/argon2) for an MVP; 600k iterations is
  OWASP-current for PBKDF2-SHA256.
- Forcing a named-child selection in the UI (rather than an optional filter) matches the user's
  "full separation" requirement and removes the raw-UUID UX.
- Serving from FastAPI gives the requested stable URL and makes the API same-origin
  (CORS already `*`, but same-origin removes base-URL configuration for the normal path).

## Alternatives considered

- **JWT sessions** — rejected: parallel auth scheme for no MVP benefit; opaque tokens already
  exist and are revocable in the DB.
- **bcrypt/argon2 dependency** — rejected for MVP; PBKDF2 stdlib is sufficient and dependency-free.
  Revisit for production hardening (S5).
- **Separate SPA build (React/Vite)** — rejected: the no-build single-file dashboard is a
  deliberate prior decision (parent-surface.decision.md D1); kept.
- **Optional child filter ("all children" default)** — rejected per explicit user requirement of
  full separation by chosen child.

## Revisit

- S5 privacy/production: TLS, rate-limiting login attempts (lockout), password reset flow,
  argon2id, session expiry/refresh.
- If the Android parent mode adopts login, share the same `/v1/parent/login` endpoint.

## Verification (D1)

- Full suite from repo root: **648 passed, 8 skipped** (5 pre-existing triage stubs + 3 others).
- New tests: `server/tests/identity/test_parent_credentials_contract.py` (16, both adapters),
  `server/tests/identity/test_parent_login.py` (11, router + dashboard serving).
- End-to-end smoke `scripts/_smoke_dashboard_login.py`: 13/13 PASS against the real
  composition root (dashboard URL, register, dup-409, login 200/401/401-same-body,
  child issue/list by name, own-child alerts 200, foreign-child 403, back-compat register).

---

# D2 — Email login + OTP-by-email first-time onboarding (same day, supersedes username)

## Question

How does first-time onboarding connect the dashboard and the child app? (User requirement: parent
registers → receives the pairing OTP **by email** → uses it to pair the child app → logs into the
dashboard with **email + password**.)

## Choice

1. **Email replaces username** as the login identifier (`POST /v1/parent/login {email, password}`).
   Idempotent SQLite migration adds `email` (partial unique index); the never-merged `username`
   column stays unused (SQLite can't drop columns — harmless). Lowercased + regex-validated;
   duplicate → 409; bad login → uniform 401 (no enumeration).
2. **New `EmailSender` port** (`server/app/mailer/` — not `email/`, which would shadow the stdlib):
   `LogEmailSender` (default, dev) + `SmtpEmailSender` (`MAILER_BACKEND=smtp`, STARTTLS via
   `asyncio.to_thread`, Gmail app-password documented in `.env.example`). Constructed only in
   lifespan(). The **Gmail API OAuth2** sender for *alert* notifications was implemented in a
   parallel session on the alerts-notifier port (`GmailApiNotifier`, `ALERTS_CHANNEL=email` —
   see `child-only-and-email-alerts.decision.md`); both compose with this work.
3. **Onboarding flow:** `register` accepts optional `child_name` — creates parent + child +
   pairing OTP in one call, emails the OTP (Hebrew body, "Shomer.AI" Latin), AND returns it in
   the 201 response (MVP/demo pragmatism; email is the primary channel). Existing
   `/v1/parent/pairing-code` now also emails the code. Email failures never fail the request
   (fire-and-forget + warning log).
4. **Dashboard onboarding wizard:** register form gains child-name; on 201 a centered pairing
   step shows the code (copy button + expiry countdown) + 3-step child-app guide; in-app
   "add child" / "pairing code" actions reuse the same modal. Login card switched to email.

## Why

- Email is required anyway as the alert-notification address (D-CO-2) — one identifier serves
  login + OTP delivery + alerts.
- One-call register-with-child removes the multi-step setup for the common first-run case.
- Returning the code in the response keeps the demo workable with the Log mailer (no SMTP creds).

## Alternatives considered

- Username + separate email field — rejected: two identifiers, no benefit.
- Email-only OTP (not shown on screen) — rejected for MVP: blocks the demo without SMTP/Gmail creds.
- Verifying email ownership before pairing (click-through link) — deferred to S5 hardening.

## Revisit

S5: email verification link, OTP rate limiting, resend throttling; possibly route OTP through the
Gmail API sender once its credential is provisioned (same port swap).

## Verification (D2)

- Full suite from repo root: **660 passed, 8 skipped**.
- Smoke `scripts/_smoke_dashboard_login.py`: **21/21 PASS** including full onboarding —
  register(email+password+child_name) → OTP captured from mailer → `POST /v1/pair` →
  device_token(role=child) → child listed under the parent.
