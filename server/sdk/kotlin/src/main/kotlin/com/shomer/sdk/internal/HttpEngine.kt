package com.shomer.sdk.internal

import com.shomer.sdk.SdkConfig
import com.shomer.sdk.logging.SdkLogger
import okhttp3.OkHttpClient
import java.util.concurrent.TimeUnit

/**
 * Builds the shared [OkHttpClient] from an [SdkConfig] with the trace-id and
 * retry interceptors installed (design.md §3.2). Image classify needs a much
 * longer read timeout (Tesseract), so [imageClient] is derived from the base
 * client — sharing its connection pool and dispatcher — with only the read
 * timeout widened.
 */
internal class HttpEngine(config: SdkConfig, logger: SdkLogger) {

    val textClient: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(config.connectTimeoutMs, TimeUnit.MILLISECONDS)
        .readTimeout(config.readTimeoutMs, TimeUnit.MILLISECONDS)
        // Order matters: trace-id first (so the retry interceptor can read the tag),
        // then retry which re-issues chain.proceed().
        .addInterceptor(TraceIdInterceptor(userAgent = "shomer-sdk/${config.sdkVersion}", apiKey = config.apiKey))
        .addInterceptor(RetryInterceptor(config.maxRetries, config.initialBackoffMs, logger))
        .build()

    val imageClient: OkHttpClient = textClient.newBuilder()
        .readTimeout(config.imageReadTimeoutMs, TimeUnit.MILLISECONDS)
        .build()

    fun close() {
        textClient.dispatcher.executorService.shutdown()
        textClient.connectionPool.evictAll()
        textClient.cache?.close()
    }
}
