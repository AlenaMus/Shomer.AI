# Decision — Parent web dashboard: username/password login + per-child separation

**Date:** 2026-06-12
**Status:** Implemented on branch `feature/parent-dashboard-login` (merge pending user approval)

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

## Verification

- Full suite from repo root: **648 passed, 8 skipped** (5 pre-existing triage stubs + 3 others).
- New tests: `server/tests/identity/test_parent_credentials_contract.py` (16, both adapters),
  `server/tests/identity/test_parent_login.py` (11, router + dashboard serving).
- End-to-end smoke `scripts/_smoke_dashboard_login.py`: 13/13 PASS against the real
  composition root (dashboard URL, register, dup-409, login 200/401/401-same-body,
  child issue/list by name, own-child alerts 200, foreign-child 403, back-compat register).
