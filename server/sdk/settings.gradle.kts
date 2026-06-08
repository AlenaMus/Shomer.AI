// Standalone Gradle build for the Shomer.AI client SDK.
//
// Two modules, named to match docs/design/sdk/design.md §3.5:
//   :sdk      → the hand-written Kotlin library      (dir: kotlin/)
//   :sdk-cli  → the clikt terminal runner / fat-jar  (dir: kotlin-cli/)
//
// This is intentionally a SEPARATE build from android_client/ so the SDK
// compiles headless on a plain JVM (LLD §2.5 forbids android.* imports).
// Folding :sdk into android_client/settings.gradle.kts as project(":sdk")
// is a tracked follow-on — see plan-docs/decisions/sdk-implementation.decision.md.

rootProject.name = "shomer-sdk"

include(":sdk")
project(":sdk").projectDir = file("kotlin")

include(":sdk-cli")
project(":sdk-cli").projectDir = file("kotlin-cli")
