# Server SDK — shared client library

This folder hosts the **client SDK**: a library that any client (Android, web, future others) imports to communicate with the FastAPI server in `../app/`. Instead of every client hand-rolling HTTP calls, JSON shapes, and error handling, they all go through this library.

## Status (2026-05-23)

**Placeholder only.** Folder created so the project structure makes the intent visible. No code yet — implementation approach is deferred until the first real client integration starts.

## Decision deferred — pick when we touch this folder for real

| Approach | What goes in here | Pros | Cons |
|---|---|---|---|
| **Generated from OpenAPI** | `openapi.yaml` (exported from FastAPI) + `kotlin/` and `typescript/` subfolders produced by `openapi-generator` | Server changes → regenerate → clients update. Strict contract. Demo-friendly. | Adds a code-gen step; generated code can be verbose. |
| **Hand-written** | `kotlin/ShomerApiClient.kt`, `typescript/shomerApiClient.ts`, plus shared models | Readable, fewer moving parts. Easy to explain in an academic write-up. | Must manually keep client models in sync with `../app/schemas.py`. |

Until this is decided, **clients should keep their own minimal HTTP layer** (as `android_client/` does today) — duplicated work for now, but it's easy to swap to a real SDK once we choose.

## Intended consumers

- `../../android_client/` — Kotlin client. Will depend on the Kotlin SDK published from here.
- *(future)* `../../web_client/` — TypeScript / browser client.
- Any future client (CLI, other mobile platform, integration test harness) should also import from here rather than hand-rolling its own HTTP layer.

## Contract surface (what the SDK will wrap)

The FastAPI server in `../app/main.py` currently exposes:

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness + Ollama reachability |
| GET | `/model/info` | Model id, labels |
| POST | `/classify` | `{ text }` → `{ is_offensive, category, confidence, model, latency_ms }` |

Any change to these endpoints is a contract change and must be reflected here.
