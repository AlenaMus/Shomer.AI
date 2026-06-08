# Decision — Client SDK implementation kickoff

**Date:** 2026-06-08
**Phase/Step:** POC Phase 5 (Client SDK) · Meeting-7 prep
**Status:** Active

---

## D-SDK-1 — Build the SDK now, hand-written (not OpenAPI-generated)

**Question:** The SDK was design-only (`docs/design/sdk/design.md`, 0/13 tasks). Start it now, and which approach — hand-written Kotlin or OpenAPI-generated?

**Choice:** Implement now, **hand-written Kotlin** (`:sdk` library), MVP `1.0.0`.

**Why:** Confirms the prior PRD §8.6 / `prd-enrichment.decision.md` D1 direction — readable, fewer moving parts, easy to explain academically. The gap audit (`plan-docs/meetings/m7/00-gap-audit.md`) flagged the SDK as the single biggest unbuilt deliverable besides model training. The hand-written surface matches the server contract verified field-by-field against `server/app/schemas.py` + `main.py` routes.

**Alternatives considered:** OpenAPI-generated (`openapi-generator` from FastAPI `/openapi.json`) — kept as the Phase-9 migration seam (`ShomerApi` port + `ShomerEndpoint` make the swap a one-liner), but deferred: adds a codegen step and verbose output for no MVP benefit.

**Revisit:** Phase 9, if a published artifact or TypeScript variant is scoped.

---

## D-SDK-2 — Standalone Gradle build (not folded into android_client yet)

**Question:** Where does the SDK Gradle module live — inside `android_client/settings.gradle.kts` as `project(":sdk")` (per LLD §9), or as its own build under `server/sdk/`?

**Choice:** A **standalone composite build** rooted at `server/sdk/` (`:sdk` → `kotlin/`, `:sdk-cli` → `kotlin-cli/`), pure Kotlin/JVM, with its own copy of the Gradle 9.0.0 wrapper.

**Why:** (1) The LLD (§2.5) requires the SDK to compile headless on plain JVM with **no `android.*` imports** — a standalone JVM build enforces that mechanically and lets `:sdk-cli` run on a server box without the Android SDK. (2) Folding into the Android build now would force an APK uninstall/rebuild and entangle SDK iteration with the app's flavor matrix. (3) It is independently testable today: `./gradlew :sdk:test` (10 MockWebServer contract tests pass) + `:sdk-cli:fatJar`.

**Alternatives considered:** Include `:sdk` directly in `android_client/settings.gradle.kts` now — deferred to the "wire Android onto `:sdk`" follow-on (replace `android_client/.../data/ApiService.kt`). A pure-JVM `:sdk` is consumable by Android via `implementation(project(...))` when that happens.

**Revisit:** When migrating the Android client off its hand-rolled `ApiService.kt` onto `:sdk`.

---

## D-SDK-3 — Target Java 17 bytecode with the running JDK (no JDK-17 toolchain)

**Question:** Gradle `java.toolchain { languageVersion = 17 }` failed — the only JDK on the machine is the Android Studio JBR (JDK **21**), and toolchain auto-provisioning isn't configured.

**Choice:** Drop the toolchain; set `sourceCompatibility/targetCompatibility = 17` + Kotlin `jvmTarget = JVM_17`, compiled by the JBR 21.

**Why:** Produces Java-17 bytecode (matching the Android client's `JavaVersion.VERSION_17`) using the JDK already installed — no extra JDK download, builds on this machine out of the box (`JAVA_HOME` = `C:\Program Files\Android\Android Studio\jbr`).

**Revisit:** If CI pins a JDK-17 toolchain, the toolchain block can return.
