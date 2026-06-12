# Shomer.AI — Parent Web Dashboard

The web parent surface (`plan-docs/decisions/parent-surface.decision.md` D1). A single
self-contained `index.html` — no build step, no framework, no external CDN dependencies. It
talks to the server's parent API and lets a parent **log in, pick a child, review and react**
to flagged content, and view the **once-a-day digest**.

## Run

Open **`http://localhost:8000/dashboard/`** (or `http://<PC-LAN-IP>:8000/dashboard/` from
another device). FastAPI serves the dashboard from the same origin as the API, so the base URL
is detected automatically (`location.origin`) — no configuration needed.

> Base-URL override is only needed when opening `index.html` directly as a `file://` page
> (e.g. double-clicking it). In that case use **הגדרות חיבור** (bottom of the login card, or
> the user menu after login) to point it at the server, e.g. `http://localhost:8000`. The
> override persists in `localStorage` (`shomer.base`) and, when set, wins over auto-detection.

## Login flow

- **התחברות (Login)** — username + password → `POST /v1/parent/login` → token + display name
  stored in `localStorage`. Wrong credentials (401) show an inline Hebrew error.
- **הרשמה (Register)** — toggle on the login card adds a display-name field →
  `POST /v1/parent/register` (username 3–32 chars, lowercase letters/digits/`._-`; password
  min 8 chars; 409 = username taken) and auto-logs in with the returned token.
- Any later API call that returns **401** clears the token and returns to the login screen.
- **התנתקות (Logout)** — in the user menu (top of the header, shows the parent's display name).

## Child selector

After login the dashboard fetches `GET /v1/parent/children` and renders the children **by
display name** as chips under the header. A child must be selected to see any data — every
alerts/digest request is scoped to the selected child's `child_id` (there is no "all children"
view and no raw-ID inputs).

- Exactly one child → auto-selected.
- Zero children → friendly empty state explaining that pairing happens from the Shomer.AI app
  on the child's device (child mode + pairing code).
- The selection persists per parent (`localStorage`), and the header shows
  **"מציג נתונים עבור: \<name\>"**. Switching child instantly reloads the current view.

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
  `shomer.parent_name`, `shomer.child.<parent_id>` (selected child per parent). No data leaves
  the browser except the authenticated API calls.
- Response parsing is defensive (accepts a bare array or an `{alerts: […]}` / `{children: […]}` /
  `{digests: […]}` wrapper) so it tolerates minor server-shape differences.
