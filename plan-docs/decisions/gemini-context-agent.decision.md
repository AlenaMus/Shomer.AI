# Gemini for the Context Agent — Decision

## D1 — Add Google Gemini as a Context-Agent LLM provider

**Question:** The user has a `GEMINI_API_KEY` and wants the Context Agent to use
Gemini (alongside / instead of OpenAI + Anthropic).

**Choice:** Added a `GeminiClient` adapter (new `LlmClient`) that talks to
**Gemini's OpenAI-compatible endpoint** (`https://generativelanguage.googleapis.com/v1beta/openai/`)
by **reusing the already-installed `openai` SDK** with a different `base_url`.
Default model `gemini-2.5-flash` (override via `GEMINI_MODEL`). Wired into the
composition root: provider priority is **Gemini → OpenAI → Anthropic**; the
first configured key is primary, the second is fallback, Mock fills any empty
slot. Key read from `GEMINI_API_KEY` in `server/.env`.

**Why:**
- The OpenAI-compat endpoint means **zero new dependencies** — no
  `google-generativeai` package, no second SDK to learn/pin. The existing
  `OpenAiClient` and `GeminiClient` share the same call shape (`chat.completions`
  + `response_format=json_object`), so the Context Agent's output parser works
  unchanged.
- Gemini Flash is cheap and fast, a good fit for the borderline-reasoning role.
- Putting Gemini first in priority matches the user's available key while leaving
  OpenAI/Anthropic as drop-in alternates with no code change.

**Also fixed (latent bug):** `_build_llm_clients` previously passed the *settings
object* to `OpenAiClient(...)` / `AnthropicClient(...)`, but those adapters take
an **api-key string**. It never triggered because no keys were ever configured.
The rewrite passes `secret.get_secret_value()` strings.

**Alternatives considered:**
- *`google-generativeai` native SDK* — passed over: extra dependency + a second
  response/JSON shape to adapt; no benefit over the compat endpoint for our
  single-call JSON use.
- *Vertex AI* — passed over: needs GCP project + service-account auth; heavier
  than a single API key for a thesis project.

**Revisit:** If Gemini deprecates the chosen model (bump `GEMINI_MODEL`), if the
OpenAI-compat layer drops `response_format=json_object` (switch to native SDK),
or if cost/latency telemetry favors a different primary.

**To enable:** put `GEMINI_API_KEY=<key>` (and optionally `GEMINI_MODEL=...`) in
`server/.env`, set `CONTEXT_AGENT_ENABLED=true`, restart the server. Boot log
shows `llm_clients_selected primary=gemini`.

## Live-verification fixes (2026-06-07)

First real end-to-end run surfaced three bugs, all fixed:
1. **Model 404** — `gemini-2.0-flash` is retired; default bumped to
   **`gemini-2.5-flash`** (client + settings + `.env.example`).
2. **JSON fences** — Anthropic/Haiku (the fallback) returns JSON wrapped in
   ```` ```json ... ``` ````; `output_parser._extract_json()` now strips the
   fence (and falls back to the outermost `{...}`), so the fallback parses.
   Regression tests added.
3. **Gemini truncation** — Gemini 2.5 Flash is a *thinking* model and spent the
   512-token budget on reasoning, truncating the JSON. `GeminiClient` now passes
   `extra_body={"reasoning_effort": "none"}` to disable thinking.

Verified: a `violence` message escalates → **Gemini 2.5-flash** returns
`is_real_threat=true, severity=high` with a Hebrew rationale → a real
`alerts.sent` (severity critical, source=context_agent). Anthropic Haiku is the
working fallback.

**Common-typo note:** keys in `server/.env` were initially misspelled
(`GEMENI_API_KEY`, `ANTROPIC_API_KEY`) → silently ignored. Correct names are
`GEMINI_API_KEY` and `ANTHROPIC_API_KEY` (note the **H** in ANT**H**ROPIC).
