package com.shomer.sdk

import com.shomer.sdk.models.ClassificationResult
import com.shomer.sdk.models.HealthResult
import com.shomer.sdk.models.ModelInfoResult

/**
 * The port. The ONLY symbol callers depend on (design.md §2.5).
 *
 * Production uses [com.shomer.sdk.internal.ShomerHttpClient] (OkHttp + Moshi);
 * tests use a fake. Both implement this interface, so a ViewModel written against
 * `ShomerApi` never changes when the adapter is swapped.
 */
interface ShomerApi {

    /** Classify a Hebrew text string (1..4000 chars). */
    suspend fun classify(text: String): ShomerResult<ClassificationResult>

    /** Classify an image (chat screenshot). [imageBytes] must be JPEG/PNG, ≤ 10 MB. */
    suspend fun classify(
        imageBytes: ByteArray,
        mimeType: String = "image/jpeg",
    ): ShomerResult<ClassificationResult>

    /** Server liveness + Ollama reachability. */
    suspend fun health(): ShomerResult<HealthResult>

    /** Model metadata (id, base, labels). */
    suspend fun modelInfo(): ShomerResult<ModelInfoResult>

    /** Release underlying resources. Call from Application teardown or test teardown. */
    fun close()
}
