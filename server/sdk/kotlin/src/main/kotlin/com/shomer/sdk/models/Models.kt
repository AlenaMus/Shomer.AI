package com.shomer.sdk.models

/**
 * Unified result for both text and image classify calls — mirrors
 * `server/app/schemas.py` ClassifyResponse / ClassifyImageResponse (design.md §5.1).
 *
 * [extractedText]/[backend]/[strategy] are populated only by image classify.
 * [contextUsed]/[reasoningTrace] are reserved for the Context Agent fields the
 * server will add in a later phase; they parse leniently (null when absent), so
 * the SDK does not break when the server starts emitting them.
 */
data class ClassificationResult(
    val isOffensive: Boolean,
    val category: String,          // "abusive"|"hate"|"violence"|"pornographic"|"non_offensive"|"stub"|...
    val confidence: Float,         // [0.0, 1.0]
    val model: String,
    val latencyMs: Int,
    // Image-only fields (null for text classify):
    val extractedText: String? = null,
    val backend: String? = null,
    val strategy: String? = null,
    // Context Agent fields (null when not invoked / not yet emitted by server):
    val contextUsed: Boolean? = null,
    val reasoningTrace: String? = null,
    // Review flag — true when the server used an LLM fallback (graceful degradation):
    val reviewFlag: Boolean = false,
)

/** Mirrors `HealthResponse` — GET /health. */
data class HealthResult(
    val status: String,            // "ok" | "degraded"
    val ollamaReachable: Boolean,
    val model: String,
)

/** Mirrors `ModelInfoResponse` — GET /model/info. */
data class ModelInfoResult(
    val model: String,
    val base: String?,
    val labels: List<String>,
)
