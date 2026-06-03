package com.dima.offensivehebrew.data

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class ClassifyRequest(val text: String)

@JsonClass(generateAdapter = true)
data class ClassifyResponse(
    @Json(name = "is_offensive") val isOffensive: Boolean,
    val category: String,
    val confidence: Double,
    val model: String,
    @Json(name = "latency_ms") val latencyMs: Int,
)

@JsonClass(generateAdapter = true)
data class HealthResponse(
    val status: String,
    @Json(name = "ollama_reachable") val ollamaReachable: Boolean,
    val model: String,
)

@JsonClass(generateAdapter = true)
data class ClassifyImageResponse(
    @Json(name = "is_offensive") val isOffensive: Boolean,
    val category: String,
    val confidence: Double,
    val model: String,
    @Json(name = "latency_ms") val latencyMs: Int,
    @Json(name = "extracted_text") val extractedText: String,
    val backend: String,
    val strategy: String,
)
