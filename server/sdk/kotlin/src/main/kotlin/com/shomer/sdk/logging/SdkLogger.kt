package com.shomer.sdk.logging

import org.slf4j.Logger
import org.slf4j.LoggerFactory

/**
 * Thin SLF4J wrapper tagged `shomer.sdk` (design.md §6.1). Emits structured-ish
 * single-line messages with the standard fields (trace_id, event, endpoint, attempt).
 *
 * Privacy: NEVER logs message text at INFO. Text content must not appear in any
 * INFO-level line (NFR — design.md §7). Callers bridge the SLF4J binding (Timber
 * on Android, slf4j-simple in tests).
 */
class SdkLogger(private val delegate: Logger = LoggerFactory.getLogger("shomer.sdk")) {

    fun requestSuccess(traceId: String, endpoint: String, attempt: Int, httpStatus: Int, latencyMs: Long) {
        delegate.info(
            "event=request_success trace_id={} endpoint={} attempt={} http_status={} latency_ms={}",
            traceId, endpoint, attempt, httpStatus, latencyMs,
        )
    }

    fun requestRetry(traceId: String, endpoint: String, attempt: Int, errorType: String, backoffMs: Long) {
        delegate.warn(
            "event=request_retry trace_id={} endpoint={} attempt={} error_type={} backoff_ms={}",
            traceId, endpoint, attempt, errorType, backoffMs,
        )
    }

    fun requestFailed(traceId: String, endpoint: String, attempt: Int, errorType: String, message: String) {
        delegate.error(
            "event=request_failed trace_id={} endpoint={} attempt={} error_type={} message={}",
            traceId, endpoint, attempt, errorType, message,
        )
    }
}
