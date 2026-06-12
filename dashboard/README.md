# Shomer.AI — Parent Web Dashboard

The web parent surface (`plan-docs/decisions/parent-surface.decision.md` D1). A single
self-contained `index.html` — no build step, no framework, no external CDN dependencies. It
talks to the server's parent API and lets a parent **register/log in with email, onboard a
child via an emailed pairing code, pick a child, review and react** to flagged content, and
view the **once-a-day digest**.

## Run

Open **`http://localhost:8000/dashboard/`** (or `http://<PC-LAN-IP>:8000/dashboard/` from
another device). FastAPI serves the dashboard from the same origin as the API, so the base URL
is detected automatically (`location.origin`) — no configuration needed.

> Base-URL override is only needed when opening `index.html` directly as a `file://` page
> (e.g. double-clicking it). In that case use **הגדרות חיבור** (bottom of the login card, or
> the user menu after login) to point it at the server, e.g. `http://localhost:8000`. The
> override persists in `localStorage` (`shomer.base`) and, when set, wins over auto-detection.

## Auth flow (email-based)

- **התחברות (Login)** — email + password → `POST /v1/parent/login` `{email,password}` →
  token + display name + email stored in `localStorage`. Wrong credentials (401) show
  **"אימייל או סיסמה שגויים"** inline.
- **הרשמה (Register)** — toggle on the login card adds **display name** and **child name**
  fields (child name is required — this is the first-time setup) →
  `POST /v1/parent/register` `{display_name,email,password,child_name}`.
  Client-side checks mirror the server: email regex `^[^@\s]+@[^@\s]+\.[^@\s]+$`, password
  min 8 chars. **409** (email already registered) shows an inline error with a **להתחברות**
  shortcut that flips to login with the email prefilled.
- Any later API call that returns **401** clears the token and returns to the login screen.
- **התנתקות (Logout)** — in the user menu (header). The menu also shows the parent's
  display name and email.

## Onboarding wizard (after register)

On a successful registration the dashboard moves to a dedicated **pairing step** (same
centered-card aesthetic):

1. A success banner explains that a **pairing code (OTP) was sent to the parent's email**
   — in dev the server's email adapter logs instead of sending, so the code is **also shown
   on screen** (the register response returns it): large, digit-spaced, with a **copy** button.
2. A numbered guide: install/open the **Shomer.AI child app** on the child's phone → choose
   child mode and enter the code → grant the monitoring (accessibility) permission.
3. If the response includes `pairing_expires_in_s`, a live **expiry countdown** is shown.
4. **המשך ללוח הבקרה** finishes onboarding and enters the app with the **new child
   auto-selected** (the register response's `child_id` is persisted as the selection).

## Child selector + in-app pairing

After login the dashboard fetches `GET /v1/parent/children` and renders the children **by
display name** as chips under the header. A child must be selected to see any data — every
alerts/digest request is scoped to the selected child's `child_id` (there is no "all children"
view and no raw-ID inputs).

- Exactly one child → auto-selected; selection persists per parent (`localStorage`); the bar
  shows **"מציג נתונים עבור: \<name\>"**. Switching child instantly reloads the current view.
- **+ הוסף ילד/ה** (next to the chips, and as the action in the zero-children empty state) —
  asks for the child's name → `POST /v1/parent/children` → `POST /v1/parent/pairing-code` →
  shows the same pairing-code modal (code + copy + steps + countdown). On close the children
  list reloads with the new child selected.
- **קוד התאמה** (shown when a child is selected) — regenerates a pairing code for the
  selected child via `POST /v1/parent/pairing-code` and shows the same modal; a toast notes
  the code was **also emailed**. Parsing is defensive — only `code` is assumed; expiry info
  is used when present under any of the common field names.

## What it does

- **התראות (Alerts)** — `GET /v1/parent/alerts?child_id=…` with filters (status,
  include-acked). The borderline "unknown but may be offensive" cases show as
  **לבדיקה / review_needed** (purple). Click a row → detail modal.
- **Detail + react** — `POST /v1/parent/alerts/{flag_id}/react`:
  - **סמן כטופל** → `acknowledge`
  - **סמן: פוגעני / תקין** → `label` (`offensive` / `not_offensive`) — the human verdict that
    feeds the future DictaBERT training set
  - **עדכן חומרה** → `severity`
  - The Context-Agent panel (context used, real-threat verdict, model, reasoning) renders when
    the alert came through the CA.
- **סיכום יומי (Digest)** — `GET /v1/parent/digests/{date}?child_id=…` — the aggregated
  once-a-day summary (totals, review-needed count, high-severity count, entries; 404 = no
  digest that day).

## Notes

- Hebrew RTL throughout (the "Shomer.AI" wordmark stays LTR); labels/severities shown in
  Hebrew, underscore-spelled on the wire (`non_offensive`).
- `localStorage` keys: `shomer.base` (override only), `shomer.token`, `shomer.parent_id`,
  `shomer.parent_name`, `shomer.email`, `shomer.child.<parent_id>` (selected child per
  parent). No data leaves the browser except the authenticated API calls.
- Response parsing is defensive (accepts a bare array or an `{alerts: […]}` / `{children: […]}` /
  `{digests: […]}` wrapper; tolerates missing pairing-expiry fields) so it survives minor
  server-shape differences.
- Copy-to-clipboard falls back to select-for-manual-copy where the Clipboard API is
  unavailable (e.g. plain-HTTP LAN or `file://`).
