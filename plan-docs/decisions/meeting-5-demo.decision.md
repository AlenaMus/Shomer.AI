# Meeting-5 demo — decisions

## D1 — Use a Python `dev_client.py` CLI as the Meeting-5 SDK-style demo (not the Kotlin SDK)

**Question:** How should the "server skeleton + SDK" be shown live at Meeting 5, given the Kotlin SDK (`server/sdk/`) is still a placeholder (README only) and Track C was never built?
**Choice:** Build `scripts/dev_client.py` — a dependency-light Python terminal client (httpx + stdlib) with `health` / `info` / `classify` / `classify-image` / `demo` subcommands + a curated 10-line Hebrew `scripts/golden_inputs.jsonl`. The `demo` command runs the golden set against a live server and prints a per-item table + transport/agreement/latency summary.
**Why:** The Kotlin `:sdk-cli` (Track C, ~4–5 days incl. Gradle setup) is too heavy to rush for a *skeleton* demo. The Python CLI gives a real, runnable, visually-clean live demo today, exercises the exact same wire protocol, and shares the `golden_inputs.jsonl` schema with the planned Kotlin CLI — so it doubles as the future cross-language parity test (`SERVER-DEV-CLI-01` in the backlog). FastAPI's `/docs` Swagger UI covers the server skeleton; this CLI covers the client/SDK story.
**Alternatives considered:**
- *Option 1 — present SDK design only* (LLD + OpenAPI `/docs` as the "SDK surface"): zero build, fully honest, but no live client demo.
- *Option 3 — build the real Kotlin `:sdk-cli`* (Track C): the true deliverable, but ~4–5 days and not worth rushing for a skeleton demo.
**Revisit:** When Track C starts. The Kotlin SDK + `:sdk-cli` remains the real Meeting-5/6 demo deliverable; `dev_client.py` is the interim demo + the reference implementation the Kotlin CLI's output must match (parity test).

## D2 — Fixed the Context Agent composition-root wiring (incidental, not a chosen option)

**Note:** While verifying the demo, the server failed to boot with `CONTEXT_AGENT_ENABLED=true` (the default). `server/app/main.py` `_build_context_agent()` had been written against an imagined `LlmContextAgent(router, tools, settings)` API, but the implemented agent constructs its own `LlmRouter` + tools internally and takes `(primary, fallback, budget, audit_store, slang_lexicon_path, timeout_s, max_history_turns)`. Three concrete mismatches were fixed: `InMemoryTokenManager(settings)` → keyword args; `context_agent_history_turns` → `context_agent_max_history_turns`; and the `LlmContextAgent` call signature. The CA-enabled boot path had never been exercised (the 2026-06-03 smoke test must have run with CA off or via TestClient). Server now boots clean with CA enabled (Mock LLM fallback, since no API keys). This is a fix, not a decision — recorded here only so the audit trail explains why `main.py` changed in this session.
