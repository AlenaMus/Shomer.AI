package com.shomer.sdk

/**
 * Pluggable metrics sink (design.md §6.3). The SDK has no hard dependency on a
 * metrics library; Android callers inject a Prometheus/Firebase-backed
 * implementation, and the default is a no-op so plain JVM tests stay clean.
 */
interface MetricsCallback {
    fun onRequestCompleted(endpoint: String, attempt: Int, latencyMs: Long, httpStatus: Int?)
    fun onRequestFailed(endpoint: String, attempts: Int, errorType: String)

    companion object {
        /** No-op sink used when the caller provides none. */
        val NONE: MetricsCallback = object : MetricsCallback {
            override fun onRequestCompleted(endpoint: String, attempt: Int, latencyMs: Long, httpStatus: Int?) {}
            override fun onRequestFailed(endpoint: String, attempts: Int, errorType: String) {}
        }
    }
}
