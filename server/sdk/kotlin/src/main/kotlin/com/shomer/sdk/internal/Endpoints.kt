package com.shomer.sdk.internal

import com.shomer.sdk.ShomerError
import com.shomer.sdk.ShomerResult
import com.shomer.sdk.models.ClassificationResult
import com.shomer.sdk.models.HealthResult
import com.shomer.sdk.models.ModelInfoResult
import com.squareup.moshi.Moshi
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody

/**
 * Private endpoint seam (design.md §3.4). Each endpoint maps one server route to
 * one typed result. `ShomerHttpClient` calls these through the interface, so they
 * are independently mockable and a future gRPC/generated implementation can drop
 * in without touching the public API.
 */
internal interface ShomerEndpoint<I, O> {
    suspend fun execute(input: I): ShomerResult<O>
}

private val JSON_MEDIA = "application/json; charset=utf-8".toMediaType()
private const val MAX_TEXT = 4000
private const val MAX_IMAGE_BYTES = 10 * 1024 * 1024 // 10 MB

internal class ClassifyEndpoint(
    private val executor: HttpExecutor,
    private val client: OkHttpClient,
    private val baseUrl: String,
    moshi: Moshi,
    private val timeoutMs: Long,
) : ShomerEndpoint<String, ClassificationResult> {

    private val reqAdapter = moshi.adapter(ClassifyRequestDto::class.java)
    private val respAdapter = moshi.adapter(ClassifyResponseDto::class.java)

    override suspend fun execute(input: String): ShomerResult<ClassificationResult> {
        if (input.isBlank()) {
            return ShomerResult.Failure(ShomerError.ValidationError("text must not be blank"))
        }
        if (input.length > MAX_TEXT) {
            return ShomerResult.Failure(ShomerError.ValidationError("text exceeds $MAX_TEXT chars"))
        }
        val request = Request.Builder()
            .url("$baseUrl/classify")
            .post(reqAdapter.toJson(ClassifyRequestDto(text = input)).toRequestBody(JSON_MEDIA))
            .build()
        return executor.execute(client, request, "/classify", timeoutMs) { body ->
            respAdapter.fromJson(body)!!.toModel()
        }
    }
}

internal class ClassifyImageEndpoint(
    private val executor: HttpExecutor,
    private val client: OkHttpClient,
    private val baseUrl: String,
    moshi: Moshi,
    private val timeoutMs: Long,
) : ShomerEndpoint<ClassifyImageEndpoint.Input, ClassificationResult> {

    data class Input(val bytes: ByteArray, val mimeType: String)

    private val respAdapter = moshi.adapter(ClassifyResponseDto::class.java)

    override suspend fun execute(input: ClassifyImageEndpoint.Input): ShomerResult<ClassificationResult> {
        if (input.bytes.isEmpty()) {
            return ShomerResult.Failure(ShomerError.ValidationError("image must not be empty"))
        }
        if (input.bytes.size > MAX_IMAGE_BYTES) {
            return ShomerResult.Failure(ShomerError.ValidationError("image exceeds 10MB"))
        }
        val ext = if (input.mimeType.contains("png")) "png" else "jpg"
        val body = MultipartBody.Builder()
            .setType(MultipartBody.FORM)
            .addFormDataPart(
                name = "image",
                filename = "upload.$ext",
                body = input.bytes.toRequestBody(input.mimeType.toMediaType()),
            )
            .build()
        val request = Request.Builder()
            .url("$baseUrl/classify-image")
            .post(body)
            .build()
        return executor.execute(client, request, "/classify-image", timeoutMs) { responseBody ->
            respAdapter.fromJson(responseBody)!!.toModel()
        }
    }
}

internal class HealthEndpoint(
    private val executor: HttpExecutor,
    private val client: OkHttpClient,
    private val baseUrl: String,
    moshi: Moshi,
    private val timeoutMs: Long,
) : ShomerEndpoint<Unit, HealthResult> {

    private val adapter = moshi.adapter(HealthResponseDto::class.java)

    override suspend fun execute(input: Unit): ShomerResult<HealthResult> {
        val request = Request.Builder().url("$baseUrl/health").get().build()
        return executor.execute(client, request, "/health", timeoutMs) { body ->
            adapter.fromJson(body)!!.toModel()
        }
    }
}

internal class ModelInfoEndpoint(
    private val executor: HttpExecutor,
    private val client: OkHttpClient,
    private val baseUrl: String,
    moshi: Moshi,
    private val timeoutMs: Long,
) : ShomerEndpoint<Unit, ModelInfoResult> {

    private val adapter = moshi.adapter(ModelInfoResponseDto::class.java)

    override suspend fun execute(input: Unit): ShomerResult<ModelInfoResult> {
        val request = Request.Builder().url("$baseUrl/model/info").get().build()
        return executor.execute(client, request, "/model/info", timeoutMs) { body ->
            adapter.fromJson(body)!!.toModel()
        }
    }
}
