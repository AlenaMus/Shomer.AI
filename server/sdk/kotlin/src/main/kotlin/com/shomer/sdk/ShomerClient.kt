package com.shomer.sdk

import com.shomer.sdk.internal.ShomerHttpClient
import com.shomer.sdk.logging.SdkLogger

/**
 * Factory for [ShomerApi]. The single construction point callers use; it returns
 * the interface type so consumer code never names the concrete adapter
 * (design.md §2.5). Swapping to a generated/gRPC client later is a one-line change
 * here — every ViewModel keeps compiling.
 *
 * ```kotlin
 * val api: ShomerApi = ShomerClient.create(SdkConfig(baseUrl = "http://10.0.2.2:8000/"))
 * when (val r = api.classify("שלום")) {
 *     is ShomerResult.Success -> println(r.value.category)
 *     is ShomerResult.Failure -> println(r.error.message)
 * }
 * api.close()
 * ```
 */
object ShomerClient {

    fun create(
        config: SdkConfig,
        metrics: MetricsCallback = MetricsCallback.NONE,
        logger: SdkLogger = SdkLogger(),
    ): ShomerApi = ShomerHttpClient(config, metrics, logger)
}
