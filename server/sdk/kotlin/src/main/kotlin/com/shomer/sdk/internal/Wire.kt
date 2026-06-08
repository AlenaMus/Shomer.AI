package com.shomer.sdk.internal

import com.shomer.sdk.models.ClassificationResult
import com.shomer.sdk.models.HealthResult
import com.shomer.sdk.models.ModelInfoResult
import com.squareup.moshi.Json

/**
 * Wire DTOs that mirror `server/app/schemas.py` exactly (design.md §5.1).
 * Snake_case JSON keys are bound via @Json; the reflective KotlinJsonAdapterFactory
 * fills these. Unknown fields are ignored (lenient), and the optional Context-Agent
 * fields default to null so older SDKs survive newer servers.
 */

internal data class ClassifyRequestDto(
    val text: String,
    @Json(name = "child_id") val childId: String? = null,
    @Json(name = "message_id") val messageId: String? = null,
)

/**
 * Single DTO covering both ClassifyResponse and ClassifyImageResponse — the
 * image-only and context-agent fields are nullable and absent on text responses.
 */
internal data class ClassifyResponseDto(
    @Json(name = "is_offensive") val isOffensive: Boolean,
    val category: String,
    val confidence: Double,
    val model: String,
    @Json(name = "latency_ms") val latencyMs: Int,
    @Json(name = "extracted_text") val extractedText: String? = null,
    val backend: String? = null,
    val strategy: String? = null,
    @Json(name = "context_used") val contextUsed: Boolean? = null,
    @Json(name = "reasoning_trace") val reasoningTrace: String? = null,
    @Json(name = "review_flag") val reviewFlag: Boolean? = null,
) {
    fun toModel(): ClassificationResult = ClassificationResult(
        isOffensive = isOffensive,
        category = category,
        confidence = confidence.toFloat(),
        model = model,
        latencyMs = latencyMs,
        extractedText = extractedText,
        backend = backend,
        strategy = strategy,
        contextUsed = contextUsed,
        reasoningTrace = reasoningTrace,
        reviewFlag = reviewFlag ?: false,
    )
}

internal data class HealthResponseDto(
    val status: String,
    @Json(name = "ollama_reachable") val ollamaReachable: Boolean,
    val model: String,
) {
    fun toModel(): HealthResult = HealthResult(status, ollamaReachable, model)
}

internal data class ModelInfoResponseDto(
    val model: String,
    val base: String? = null,
    val labels: List<String> = emptyList(),
) {
    fun toModel(): ModelInfoResult = ModelInfoResult(model, base, labels)
}
