# Shomer.AI — Parent Web Dashboard

The web parent surface (`plan-docs/decisions/parent-surface.decision.md` D1). A single
self-contained `index.html` — no build step, no framework, no dependencies. It reads the
server's S4 parent API and lets a parent **review and react** to flagged content, and view the
**once-a-day digest**.

## Run

**Option A — open directly.** Double-click `index.html` (or open in a browser). Go to
**הגדרות (Settings)**, set:
- **Base URL** — `http://10.0.2.2:8000` (emulator) or `http://<PC-LAN-IP>:8000` (LAN), or
  `http://localhost:8000` when the browser and server are on the same machine.
- **Parent token** — the Bearer token from `POST /v1/parent/register` (MVP bootstrap) or the
  pairing flow.

**Option B — FastAPI-served.** Mount this folder as static files in `server/app/main.py`
(`app.mount("/dashboard", StaticFiles(directory="dashboard", html=True))`). Whether to serve it
from FastAPI or host it standalone is the open S4 item in `parent-surface.decision.md` — this
file works either way (it talks to the API by absolute Base URL, so same-origin is not required;
CORS on the server already allows `*`).

## What it does

- **התראות (Alerts)** — `GET /v1/parent/alerts` with filters (status, child, include-acked).
  The borderline "unknown but may be offensive" cases show as **לבדיקה / review_needed**
  (purple). Click a row → detail.
- **Detail + react** — `POST /v1/parent/alerts/{flag_id}/react`:
  - **סמן כטופל** → `acknowledge`
  - **סמן: פוגעני / תקין** → `label` (`offensive` / `not_offensive`) — the human verdict that
    feeds the future DictaBERT training set
  - **עדכן חומרה** → `severity`
- **סיכום יומי (Digest)** — `GET /v1/parent/digests/{date}` — the aggregated once-a-day summary
  (totals, review-needed count, high-severity count, entries).

## Notes

- Hebrew RTL throughout; labels/severities shown in Hebrew, underscore-spelled on the wire
  (`non_offensive`).
- Base URL + token persist in `localStorage` (this browser only). No data leaves the browser
  except the authenticated API calls.
- Response parsing is defensive (accepts a bare array or an `{alerts: […]}` / `{digests: […]}`
  wrapper) so it tolerates minor server-shape differences — reconcile to the exact S4 shapes when
  wiring the live demo.
