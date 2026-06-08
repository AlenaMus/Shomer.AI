package com.shomer.sdk.internal

import com.shomer.sdk.MetricsCallback
import com.shomer.sdk.ShomerError
import com.shomer.sdk.ShomerResult
import com.shomer.sdk.logging.SdkLogger
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import java.io.IOException
import java.net.SocketTimeoutException
import java.util.UUID

/**
 * Runs an OkHttp call off the calling thread and maps the outcome to a
 * [ShomerResult]. HTTP-status → [ShomerError] mapping follows design.md §8.
 * Retries happen inside [RetryInterceptor]; by the time control returns here the
 * call has either succeeded, exhausted retries on a 5xx, or thrown.
 */
internal class HttpExecutor(
    private val logger: SdkLogger,
    private val metrics: MetricsCallback,
) {
    private val maxDetailChars = 500

    suspend fun <T> execute(
        client: OkHttpClient,
        request: Request,
        endpoint: String,
        timeoutMs: Long,
        parse: (String) -> T,
    ): ShomerResult<T> = withContext(Dispatchers.IO) {
        val traceId = UUID.randomUUID().toString()
        val tagged = request.newBuilder().tag(TraceTag::class.java, TraceTag(traceId)).build()
        val start = System.nanoTime()

        try {
            client.newCall(tagged).execute().use { response ->
                val latencyMs = (System.nanoTime() - start) / 1_000_000
                val code = response.code
                val body = response.body?.string().orEmpty()

                if (response.isSuccessful) {
                    return@withContext try {
                        val value = parse(body)
                        logger.requestSuccess(traceId, endpoint, attempt = 1, httpStatus = code, latencyMs = latencyMs)
                        metrics.onRequestCompleted(endpoint, attempt = 1, latencyMs = latencyMs, httpStatus = code)
                        ShomerResult.Success(value)
                    } catch (e: Exception) {
                        fail(traceId, endpoint, "ParseError", e.message ?: "unparseable response")
                        ShomerResult.Failure(ShomerError.ParseError("Malformed server response on $endpoint", e))
                    }
                }

                val error = mapHttpError(code, body, response.header("Retry-After"), timeoutMs)
                fail(traceId, endpoint, error::class.simpleName ?: "ServerError", error.message)
                metrics.onRequestCompleted(endpoint, attempt = 1, latencyMs = latencyMs, httpStatus = code)
                ShomerResult.Failure(error)
            }
        } catch (e: SocketTimeoutException) {
            fail(traceId, endpoint, "TimeoutError", e.message ?: "timeout")
            ShomerResult.Failure(ShomerError.TimeoutError(timeoutMs))
        } catch (e: IOException) {
            fail(traceId, endpoint, "NetworkError", e.message ?: "network failure")
            ShomerResult.Failure(ShomerError.NetworkError(e.message ?: "Cannot reach server", e))
        }
    }

    private fun mapHttpError(code: Int, body: String, retryAfter: String?, timeoutMs: Long): ShomerError = when (code) {
        429 -> ShomerError.RateLimitError(retryAfter?.trim()?.toIntOrNull())
        422 -> ShomerError.ValidationError(body.take(maxDetailChars))
        408, 504 -> ShomerError.TimeoutError(timeoutMs)
        else -> ShomerError.ServerError(code, body.take(maxDetailChars).ifBlank { "HTTP $code" })
    }

    private fun fail(traceId: String, endpoint: String, errorType: String, message: String) {
        logger.requestFailed(traceId, endpoint, attempt = 1, errorType = errorType, message = message)
        metrics.onRequestFailed(endpoint, attempts = 1, errorType = errorType)
    }
}
