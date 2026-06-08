package com.shomer.sdk

/**
 * Result of every [ShomerApi] call. Either a [Success] wrapping the parsed
 * response, or a [Failure] wrapping a typed [ShomerError]. No exceptions cross
 * the SDK boundary on the happy or the expected-error path — callers branch on
 * the result instead of try/catching.
 *
 * See docs/design/sdk/design.md §2.3.
 */
sealed class ShomerResult<out T> {
    data class Success<T>(val value: T) : ShomerResult<T>()
    data class Failure(val error: ShomerError) : ShomerResult<Nothing>()

    val isSuccess get() = this is Success

    fun getOrNull(): T? = (this as? Success)?.value
    fun errorOrNull(): ShomerError? = (this as? Failure)?.error
}

/**
 * The closed set of failures the SDK can report. Every documented HTTP error
 * code maps to exactly one of these (see design.md §8 failure-modes table).
 */
sealed class ShomerError(open val message: String) {

    /** TCP-level failure: no route to host, connection refused, DNS failure. */
    data class NetworkError(override val message: String, val cause: Throwable) : ShomerError(message)

    /** HTTP 4xx (excluding 429/422) or 5xx from FastAPI after retries are exhausted. */
    data class ServerError(val httpStatus: Int, override val message: String) : ShomerError(message)

    /** HTTP 429 Too Many Requests — Gatekeeper rate limit. Not auto-retried. */
    data class RateLimitError(val retryAfterSeconds: Int?) : ShomerError("Rate limit exceeded")

    /** HTTP 422 Unprocessable Entity — payload validation failed server-side. */
    data class ValidationError(val detail: String) : ShomerError("Validation error: $detail")

    /** SDK-side / network timeout (connect or read timeout, or HTTP 408/504). */
    data class TimeoutError(val timeoutMs: Long) : ShomerError("Request timed out after ${timeoutMs}ms")

    /** Response was HTTP 200 but the JSON could not be parsed into the expected shape. */
    data class ParseError(override val message: String, val cause: Throwable) : ShomerError(message)
}
