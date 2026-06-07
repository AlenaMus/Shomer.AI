# Decision — `android-developer` Project-Scoped Agent

**Date:** 2026-06-07
**Trigger:** User stated the Android POC (`android_client/`) needs to be rewritten for the real client app and asked for a dedicated Android agent. Previous gap analysis at `.claude/gaps.md` had recommended "defer until Android work is active" — that condition is now met.

---

## D1 — Build the `android-developer` agent now (supersedes "defer")

**Question:** The gap analysis deferred this agent because Android work to date was one settings screen + one classify screen built 2026-05-20. Should we build it now that the real-client rewrite is starting?

**Choice:** Build now. First-of-its-kind project-scoped agent (no user-global twin — only the user-global `android-developer` *skill* exists).

**Why:**

- The trigger condition the gap analysis named has been met: "If Android work picks up (real client implementation, not just the existing settings screen), an agent could orchestrate the skill across multi-screen builds + the `:sdk-cli` Track-C deliverable."
- The rewrite spans: package rename (`com.dima.offensivehebrew` → `com.shomer.client`), Gradle product flavors (`poc` + `client`), multi-screen flow (onboarding → dashboard → settings → debug-classify), FCM receiver for `M6-ALERTS-FCM`, permissions migration (camera + photo picker + notifications across SDK-version table). That's not one task; that's a sprint's worth of correlated work where a coordinator agent is justified.
- Hard-won knowledge worth encoding: the emulator-vs-physical-phone URL split (`10.0.2.2` vs `<PC-LAN-IP>`), the firewall rule, the cleartext-HTTP network-security config, the package-username trap (`com.dima.*` came from the machine username `Dima` but the user is Alona). Encoding these in the agent prevents future drift.
- Cost: one more agent file. Benefit: every Android-side change goes through guidance that already knows the project context.

**Alternatives considered:**

- *Continue invoking the `android-developer` skill from the main thread* — rejected because the skill is generic Android engineering, and the rewrite involves cross-screen + cross-config decisions that benefit from a project-aware orchestrator.
- *Defer until the first new screen is built* — rejected because the package rename is itself a substantive multi-file change that needs the agent's encoded plan (the APK uninstall step is non-obvious and easy to skip).

**Revisit:** If Android work plateaus after the rewrite ships (e.g. only sustaining changes for ~3+ months), reconsider whether the agent's overhead is still justified — sustaining work can route through the skill alone. Trigger: ≤1 substantive Android change per month for 3 consecutive months.

---

## D2 — Skill set: `android-developer` + `software-architect` + `software-diagrams` + `frontend-design` + `pdf`

**Question:** Which skills does the agent declare?

**Choice:** Five — `android-developer`, `software-architect`, `software-diagrams`, `frontend-design`, `pdf`.

**Why:**

- **`android-developer`** — the core skill. Already knows the Shomer.AI project context (has a "Project context: Shomer.AI" section in its `references/`).
- **`software-architect`** — for client-side architecture decisions (single-Activity vs. multi-Activity, navigation library, DI scope, repository layering). Each one warrants a decision file; the skill provides the decision framework.
- **`software-diagrams`** — for screen-flow / state-machine / sequence diagrams in the LLD + PRs. Mermaid renders in PR markdown.
- **`frontend-design`** — for hero / onboarding / parent-dashboard polish. Parent-facing safety tool can't ship generic-Material; the skill prevents the agent from settling for defaults.
- **`pdf`** — for Hebrew RTL design docs that need PDF compile (e.g. the eventual `docs/design/android_client/design.md` + PDF for Dr. Segal review).

**Alternatives considered:**

- *Add `claude-api`* — rejected because Android doesn't call Anthropic directly; the server's Context Agent owns LLM calls. Adding the skill would be misleading.
- *Add `webapp-testing`* — rejected because that's Playwright (web browser), not Android instrumented testing.
- *Add `ml-server-integrator`* — rejected because that's the server-side integration skill; the agent CONSUMES the server contract, doesn't define it.
- *Skip `frontend-design`* — rejected because the parent-facing real client must avoid the generic-AI-aesthetic the skill is designed to prevent. Compose default + Material 3 alone is not enough.

**Revisit:** If `frontend-design` proves unhelpful for native Compose (it's heavier on web styling), drop it and lean on `android-developer` alone. Trigger: 2 invocations where the skill's output is more web-React-flavored than Compose-flavored.

---

## D3 — Boundary against `backend-developer`, Track-C `:sdk-cli`, and the SDK published artifact

**Question:** The Track-C `:sdk-cli` Gradle subproject lives at `server/sdk/kotlin-cli/`. Does the new Android agent own it, or does `backend-developer`?

**Choice:** `backend-developer` owns Track-C `:sdk-cli` (it lives under `server/sdk/`). The Android agent CONSUMES the published SDK when it ships; until then it keeps the existing minimal Retrofit `ApiService` inside `android_client/`.

**Why:**

- The `:sdk-cli` is a *server*-team deliverable per `docs/design/sdk/design.md` §3.5 — it's the terminal runner against the server, designed to share the wire contract across Android + future web clients.
- The Android agent's domain is the *consumer* of the SDK contract, not the *author* of it. Mixing authoring + consuming in one agent breaks the same Protocol+adapter mental model that the server side enforces.
- Once `:sdk-cli` ships, the Android `ApiService` migrates to importing from the SDK module. That migration is a one-line Gradle dep swap + delete-the-local-`ApiService.kt` — Android agent territory. But the SDK ITSELF is server-team.

**Alternatives considered:**

- *Give the Android agent ownership of the SDK module* — rejected because the SDK serves multiple clients (Android + future web); giving Android ownership would bias the wire contract toward Android-specific concerns.
- *Joint ownership* — rejected because joint ownership defeats the point of having owners. One owner with a documented handoff is cleaner.

**Revisit:** If the SDK is never published (e.g. project ships before Track-C completes), reconsider whether the Android `ApiService` should be promoted into a reusable Kotlin module. Trigger: end of Meeting 8 with `:sdk-cli` still not built.

---

## D4 — POC namespace rename strategy: Gradle product flavors

**Question:** The package rename from `com.dima.offensivehebrew` → `com.shomer.client` causes the existing POC APK to fail to install (`INSTALL_FAILED_UPDATE_INCOMPATIBLE`). How do we let the user keep the POC installed alongside the real-client app during development?

**Choice:** Gradle product flavors (`poc` + `client`) under a `stage` flavor dimension. The `poc` flavor adds `applicationIdSuffix = ".poc"` so it installs as `com.shomer.client.poc`; the `client` flavor has no suffix and installs as `com.shomer.client`. Both flavors share source unless a specific divergence emerges.

**Why:**

- Lets the user A/B between the legacy POC behavior and the real-client rewrite on the same device during the transition period.
- Side-by-side install is the only way to compare without uninstalling-and-reinstalling repeatedly.
- Both flavors share source, so divergence is opt-in via `src/poc/` or `src/client/` source sets only when truly needed.
- The user MUST uninstall the original `com.dima.offensivehebrew` APK once (it has a different applicationId so it can't be updated to either flavor). After that one-time uninstall, both flavors install cleanly side-by-side.

**Alternatives considered:**

- *Hard cut — uninstall POC, install real-client only* — rejected because the user wants to keep the working POC reachable during the transition.
- *Different applicationId without flavors* (e.g. keep two source trees) — rejected as a fork: doubles maintenance, doubles every change. Flavors are the standard Android-idiomatic answer.
- *Use Android Studio's `Run/Debug Configurations` to switch packages on each build* — rejected as fragile; configurations don't survive sharing across machines / fresh clones.

**Revisit:** Drop the `poc` flavor once the real-client app is feature-complete and the user has manually confirmed the POC's behavior is preserved in the `debug-classify` screen of the `client` flavor. Trigger: real-client v1.0 ships + Dr. Segal demo passes.

---

## Summary table — files changed in this decision

| File | Change |
|---|---|
| `.claude/agents/android-developer.md` | **Created** — fresh project-scoped agent. |
| `.claude/agents/README.md` | Project-scoped 4 → 6; new section for `android-developer`; handoff matrix updated. |
| `.claude/gaps.md` | Android-developer-agent flipped from "defer" → ✅ DONE; agent count 4 → 6. |
| `plan-docs/decisions/android-developer-agent.decision.md` | **This file** — captures D1–D4. |
| `prompts/2026-06-07_meeting-6.md` | Turn appended (this session). |

---

## Reading list for revisit

When this decision is reopened:

- The skill's `references/permissions-media.md` — still current with Android's permission landscape? Android's permission model evolves; a 6-month-old reference may be stale.
- The LAN networking matrix — still the dev-deployment path? If the project moves to a hosted server (cloud FastAPI), the cleartext-HTTP + LAN-IP guidance is obsolete.
- The Track-C `:sdk-cli` boundary — still server-team? If the project pivots to Android-only (no web client), the boundary may shift.
- The POC flavor — still needed? Once the real client is feature-complete + Dr. Segal demo passes, the POC flavor can be retired.
