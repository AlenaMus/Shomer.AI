# Android Child-Mode Build — Decisions

**Sprint:** A1 + A2 + A3 (milestones implemented in one pass, 2026-06-07)
**Agent:** android-developer
**Status:** DONE — both poc and client debug APKs build successfully.

---

## D1 — Gradle product flavors strategy

**Question:** How do poc and client flavors coexist? Two separate source trees vs. shared sources?

**Choice:** **Single shared source tree under `com.shomer.client` namespace.** Both flavors compile the same Kotlin sources. The `poc` flavor uses `applicationId = "com.dima.offensivehebrew"` (legacy identity); the `client` flavor uses `applicationId = "com.shomer.client"` (real identity). The `namespace` is fixed at `com.shomer.client` — this governs R class and AndroidManifest class resolution.

**Why:** The POC and real client are diverging in applicationId only, not in feature set. The classify + settings screens work in both flavors as a debug connectivity aid. A separate source tree would duplicate all files with no benefit at this stage.

**APK uninstall requirement:** When switching flavors on a device, the EXISTING APK under the OLD applicationId must be uninstalled first. `adb uninstall com.dima.offensivehebrew` before installing the poc flavor for the first time after the rename; `adb uninstall com.shomer.client` before installing the client flavor if a legacy poc was there. Failure produces `INSTALL_FAILED_UPDATE_INCOMPATIBLE`.

**Alternatives considered:**
- Separate `src/poc/` and `src/client/` source sets — rejected: duplicates all sources with no upside at this stage; adds maintenance overhead.
- Single applicationId (no flavors) — rejected: user needs both installed simultaneously during transition.

**Revisit:** When the poc flavor is decommissioned (post-demo), remove the flavor dimension and clean up tombstone files.

---

## D2 — EncryptedEventBuffer encryption approach

**Question:** SQLCipher (full per-file encryption) vs. Android Keystore + Room (file-level FBE) for the event buffer?

**Choice:** **Plain Room (no SQLCipher) for the MVP.** The database file lives in app-private storage protected by Android's File-Based Encryption (FBE) — encrypted when the device is locked on API 24+ with FBE-capable devices. Individual field content (text, package name) contains no counterparty PII per the design.

**Why:** SQLCipher adds a 3–5 MB native .so per ABI, complicates the build, and requires an additional license. FBE provides adequate at-rest protection for the MVP academic deployment (sideload/internal-test). The decision is documented for S5/A6 privacy hardening when SQLCipher would be added.

**Alternatives considered:**
- SQLCipher: strong but adds build complexity + binary size. Deferred to A6.
- EncryptedSharedPreferences for all data: not suitable for a list/DAO pattern.

**Revisit:** A6 privacy hardening.

---

## D3 — Moshi adapter strategy (reflection vs. codegen)

**Question:** Use `moshi-kotlin-codegen` (KSP) for zero-reflection Moshi adapters or `moshi-kotlin` (reflection) adapters?

**Choice:** **Reflection adapters (`moshi-kotlin` + `KotlinJsonAdapterFactory`).** Using both codegen KSP and reflection in the same build caused KSP processing failures on `@JsonClass(generateAdapter = true)` annotations. The reflection path works without the codegen plugin.

**Why:** For a debug/academic MVP, reflection overhead is negligible. The codegen path would require removing `KotlinJsonAdapterFactory` from the Moshi builder. The fix is fast: remove `ksp("com.squareup.moshi:moshi-kotlin-codegen")` from build.gradle.kts.

**Revisit:** Before shipping to Play Store — codegen is correct for production (smaller APK, no reflection).

---

## D4 — `CaptureCoordinator` as `@Singleton` vs. passed-as-parameter

**Question:** Should `CaptureCoordinator` be Hilt-provided singleton or created per-service?

**Choice:** **Hilt `@Singleton`.** Both `ShomerAccessibilityService` (`@AndroidEntryPoint`) and `MainActivity` inject the same `CaptureCoordinator` instance. This means the live counters (`capturedCount`, `insertedCount`) are shared across the process and the status screen sees real numbers.

**Why:** The accessibility service needs to submit events; the status screen needs to read counters. A singleton is the correct scope for shared mutable state in a single-process app.

**Revisit:** If the accessibility service is moved to a separate process (unusual; not planned).

---

## D5 — KDoc comment safety (nested block comment issue)

**Finding (not a design decision — a build fix):** Kotlin's lexer supports nested `/* ... */` block comments. Writing `/v1/*` at the end of a KDoc line opens an unclosed nested block comment because the `/*` opens depth+1 and there is no matching `*/` on the same line. This caused `Unclosed comment` errors at EOF in three data-layer files.

**Fix:** Replace `/v1/*` in KDoc with `/v1/` (path prefix without wildcard) in KDoc comment text. The wire contract documentation is unaffected.

**Rule:** Never end a KDoc line with `/*` — use `/* ... */` (closed on the same line) or avoid the pattern entirely. Applies to all Kotlin KDoc in this project.
