package com.shomer.sdk.internal

import okhttp3.Interceptor
import okhttp3.Response
import java.util.UUID

/**
 * Adds a per-request UUID4 `X-Trace-ID` header for end-to-end correlation
 * (design.md §3.2), a `User-Agent` carrying the SDK version, and — when
 * configured — an `Authorization: Bearer` header (reserved Phase-9 auth, §11.3).
 *
 * The trace id is also stashed on the request tag so downstream code (the
 * executor / logger) can read the exact id that went out on the wire.
 */
internal class TraceIdInterceptor(
    private val userAgent: String,
    private val apiKey: String?,
) : Interceptor {

    override fun intercept(chain: Interceptor.Chain): Response {
        // Honor a trace id the executor pre-seeded on the tag (so it can log the
        // exact id that went out); otherwise mint one here.
        val existing = chain.request().tag(TraceTag::class.java)
        val traceId = existing?.traceId ?: UUID.randomUUID().toString()
        val builder = chain.request().newBuilder()
            .header("X-Trace-ID", traceId)
            .header("User-Agent", userAgent)
        if (existing == null) {
            builder.tag(TraceTag::class.java, TraceTag(traceId))
        }
        if (!apiKey.isNullOrBlank()) {
            builder.header("Authorization", "Bearer $apiKey")
        }
        return chain.proceed(builder.build())
    }
}

/** Carries the outbound trace id on the OkHttp request tag. */
internal data class TraceTag(val traceId: String)
