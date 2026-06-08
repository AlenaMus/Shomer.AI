package com.shomer.sdk.internal

import com.shomer.sdk.MetricsCallback
import com.shomer.sdk.SdkConfig
import com.shomer.sdk.ShomerApi
import com.shomer.sdk.ShomerResult
import com.shomer.sdk.logging.SdkLogger
import com.shomer.sdk.models.ClassificationResult
import com.shomer.sdk.models.HealthResult
import com.shomer.sdk.models.ModelInfoResult
import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory

/**
 * Default [ShomerApi] adapter: hand-written OkHttp + Moshi (design.md §2.5 / §3).
 * Internal — consumers obtain it only via [com.shomer.sdk.ShomerClient.create],
 * typed as `ShomerApi`.
 */
internal class ShomerHttpClient(
    config: SdkConfig,
    metrics: MetricsCallback = MetricsCallback.NONE,
    logger: SdkLogger = SdkLogger(),
) : ShomerApi {

    private val engine = HttpEngine(config, logger)
    private val moshi = Moshi.Builder().add(KotlinJsonAdapterFactory()).build()
    private val executor = HttpExecutor(logger, metrics)
    private val baseUrl = config.baseUrl.trimEnd('/')

    private val classifyEndpoint =
        ClassifyEndpoint(executor, engine.textClient, baseUrl, moshi, config.readTimeoutMs)
    private val classifyImageEndpoint =
        ClassifyImageEndpoint(executor, engine.imageClient, baseUrl, moshi, config.imageReadTimeoutMs)
    private val healthEndpoint =
        HealthEndpoint(executor, engine.textClient, baseUrl, moshi, config.readTimeoutMs)
    private val modelInfoEndpoint =
        ModelInfoEndpoint(executor, engine.textClient, baseUrl, moshi, config.readTimeoutMs)

    override suspend fun classify(text: String): ShomerResult<ClassificationResult> =
        classifyEndpoint.execute(text)

    override suspend fun classify(imageBytes: ByteArray, mimeType: String): ShomerResult<ClassificationResult> =
        classifyImageEndpoint.execute(ClassifyImageEndpoint.Input(imageBytes, mimeType))

    override suspend fun health(): ShomerResult<HealthResult> =
        healthEndpoint.execute(Unit)

    override suspend fun modelInfo(): ShomerResult<ModelInfoResult> =
        modelInfoEndpoint.execute(Unit)

    override fun close() = engine.close()
}
