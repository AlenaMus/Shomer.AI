package com.shomer.sdk.internal

import com.shomer.sdk.logging.SdkLogger
import okhttp3.Interceptor
import okhttp3.Response
import java.io.IOException

/**
 * Exponential-backoff retry (design.md §3.3): retries on transport IOException
 * or HTTP 5xx, with backoff initialBackoff * 2^(attempt-1) → 1s / 2s / 4s.
 *
 * Does NOT retry 4xx (including 429 / 413 / 422 / 408) — those are deterministic
 * and mapped straight to the matching [com.shomer.sdk.ShomerError] by the executor.
 *
 * Backoff sleeps on the calling thread; calls run on Dispatchers.IO, so this does
 * not block the main thread.
 */
internal class RetryInterceptor(
    private val maxAttempts: Int,
    private val initialBackoffMs: Long,
    private val logger: SdkLogger,
    private val sleeper: (Long) -> Unit = { Thread.sleep(it) },
) : Interceptor {

    override fun intercept(chain: Interceptor.Chain): Response {
        val request = chain.request()
        val endpoint = request.url.encodedPath
        val traceId = request.tag(TraceTag::class.java)?.traceId ?: "-"

        var lastError: IOException? = null

        for (attempt in 1..maxAttempts) {
            try {
                val response = chain.proceed(request)
                if (response.code < 500 || attempt == maxAttempts) {
                    return response
                }
                // 5xx and attempts remain → discard body and back off.
                response.close()
                lastError = IOException("HTTP ${response.code}")
            } catch (e: IOException) {
                lastError = e
                if (attempt == maxAttempts) throw e
            }

            val backoff = initialBackoffMs shl (attempt - 1) // 1s, 2s, 4s, ...
            logger.requestRetry(
                traceId = traceId,
                endpoint = endpoint,
                attempt = attempt + 1,
                errorType = lastError?.let { it::class.simpleName ?: "IOException" } ?: "IOException",
                backoffMs = backoff,
            )
            sleeper(backoff)
        }

        // Unreachable for IOException (rethrown above); the 5xx-exhausted path
        // returns inside the loop. Guard for completeness.
        throw lastError ?: IOException("Retry exhausted")
    }
}
