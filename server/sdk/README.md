# Shomer.AI Client SDK

The shared client library every client (Android child/parent, future web, CLI,
integration harnesses) imports to talk to the FastAPI server in `../app/` —
instead of each hand-rolling HTTP calls, JSON shapes, retries, and error handling.

## Status (2026-06-08)

**Implemented (MVP `1.0.0`).** Approach = **hand-written Kotlin** (not OpenAPI-generated),
per `docs/design/sdk/design.md` and `plan-docs/decisions/sdk-implementation.decision.md`.

Two Gradle modules in a standalone build rooted here:

| Module | Dir | What it is |
|---|---|---|
| `:sdk` | `kotlin/` | The hand-written library — pure Kotlin/JVM (no `android.*`), OkHttp + Moshi |
| `:sdk-cli` | `kotlin-cli/` | clikt terminal runner / fat-jar wrapping the same `ShomerApi` |

## Public surface

```kotlin
val api: ShomerApi = ShomerClient.create(SdkConfig(baseUrl = "http://10.0.2.2:8000/"))

when (val r = api.classify("תפסיק להיות כזה לוזר")) {
    is ShomerResult.Success -> println("${r.value.category} @ ${r.value.confidence}")
    is ShomerResult.Failure -> println(r.error.message)   // typed ShomerError
}
api.close()
```

- Port: `ShomerApi` (`classify(text)`, `classify(bytes,mime)`, `health()`, `modelInfo()`, `close()`).
- Default adapter: `internal ShomerHttpClient` (OkHttp + Moshi). Callers only ever name `ShomerApi`.
- Results: `ShomerResult.Success | Failure`; errors: `NetworkError · ServerError · RateLimitError · ValidationError · TimeoutError · ParseError`.
- Retry: 3 attempts, 1s/2s/4s backoff, on 5xx + IOException only (never 4xx).
- Every request carries a UUID4 `X-Trace-ID` + `User-Agent: shomer-sdk/<ver>`.
- Models mirror `../app/schemas.py`; unknown/new fields parse leniently.

## Build & test

Requires JDK 17+. Uses the bundled Gradle 9.0.0 wrapper.

```bash
cd server/sdk
./gradlew :sdk:test          # MockWebServer contract suite
./gradlew :sdk-cli:fatJar    # → kotlin-cli/build/libs/shomer-cli.jar
```

## CLI usage

```bash
java -jar kotlin-cli/build/libs/shomer-cli.jar classify "תפסיק להיות כזה לוזר"
java -jar shomer-cli.jar classify-image screenshot.png --verbose
java -jar shomer-cli.jar health --server http://localhost:8000
java -jar shomer-cli.jar info
java -jar shomer-cli.jar demo          # runs the curated golden set
```

Or without building the jar: `./gradlew :sdk-cli:run --args="health"`.

## Server contract wrapped

| Method | Path | Purpose |
|---|---|---|
| POST | `/classify` | `{text, child_id?, message_id?}` → classification |
| POST | `/classify-image` | multipart `image=@file` → OCR + classification |
| GET | `/health` | liveness + Ollama reachability |
| GET | `/model/info` | model id, base, labels |

Any change to these endpoints is a contract change and must be reflected in
`kotlin/src/main/kotlin/com/shomer/sdk/internal/Wire.kt` + the contract test.

## Not yet done (tracked)

- **`:sdk-cli batch` mode** for Meeting-8 gold-set evals (SDK-CLI-03, Phase 6).
- **Wire the Android client onto `:sdk`** (replace `android_client/.../data/ApiService.kt`).
  Today the SDK is a standalone build; folding it into `android_client/settings.gradle.kts`
  as `project(":sdk")` is the follow-on — see the decision file.
- **TypeScript variant** (Phase 9) and **published Maven/JitPack artifact** (post-Meeting-8).
