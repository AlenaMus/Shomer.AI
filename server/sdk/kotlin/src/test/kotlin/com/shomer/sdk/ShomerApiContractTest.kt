package com.shomer.sdk

import kotlinx.coroutines.test.runTest
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import kotlin.test.AfterTest
import kotlin.test.BeforeTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

/**
 * Contract suite for the [ShomerApi] port (design.md §2.5). Exercises the default
 * [com.shomer.sdk.internal.ShomerHttpClient] adapter through MockWebServer:
 * 200→Success, every documented HTTP error→correct ShomerError, retry-on-5xx
 * (not 4xx), X-Trace-ID present, malformed JSON→ParseError.
 */
class ShomerApiContractTest {

    private lateinit var server: MockWebServer
    private lateinit var api: ShomerApi

    @BeforeTest
    fun setUp() {
        server = MockWebServer().apply { start() }
        api = ShomerClient.create(
            SdkConfig(
                baseUrl = server.url("/").toString(),
                initialBackoffMs = 1L, // keep retry tests fast
                maxRetries = 3,
            ),
        )
    }

    @AfterTest
    fun tearDown() {
        api.close()
        server.shutdown()
    }

    @Test
    fun classify_success_parsesResult() = runTest {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """{"is_offensive":true,"category":"abusive","confidence":0.91,"model":"v1.0-standin","latency_ms":42}""",
            ),
        )
        val result = api.classify("תפסיק להיות כזה לוזר")
        val success = assertIs<ShomerResult.Success<*>>(result)
        val value = success.value as com.shomer.sdk.models.ClassificationResult
        assertTrue(value.isOffensive)
        assertEquals("abusive", value.category)
        assertEquals(0.91f, value.confidence)
        assertEquals(42, value.latencyMs)
    }

    @Test
    fun classify_sendsTraceIdHeader() = runTest {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """{"is_offensive":false,"category":"non_offensive","confidence":0.99,"model":"v1.0-standin","latency_ms":10}""",
            ),
        )
        api.classify("שלום חבר")
        val recorded = server.takeRequest()
        assertNotNull(recorded.getHeader("X-Trace-ID"), "every outbound request must carry X-Trace-ID")
        assertTrue(recorded.getHeader("User-Agent")!!.startsWith("shomer-sdk/"))
    }

    @Test
    fun classifyImage_success_parsesDiagnosticFields() = runTest {
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """{"is_offensive":false,"category":"non_offensive","confidence":0.8,"model":"v1.0-standin","latency_ms":900,"extracted_text":"שלום","backend":"tesseract","strategy":"ocr_only"}""",
            ),
        )
        val result = api.classify(byteArrayOf(1, 2, 3, 4), "image/png")
        val value = assertIs<ShomerResult.Success<com.shomer.sdk.models.ClassificationResult>>(result).value
        assertEquals("tesseract", value.backend)
        assertEquals("שלום", value.extractedText)
        // multipart field must be named "image" to match the server's File(...) param
        val recorded = server.takeRequest()
        assertTrue(recorded.body.readUtf8().contains("name=\"image\""))
    }

    @Test
    fun health_and_modelInfo_parse() = runTest {
        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"status":"ok","ollama_reachable":true,"model":"v1.0-standin"}"""))
        val health = assertIs<ShomerResult.Success<com.shomer.sdk.models.HealthResult>>(api.health()).value
        assertEquals("ok", health.status)
        assertTrue(health.ollamaReachable)

        server.enqueue(MockResponse().setResponseCode(200).setBody("""{"model":"v1.0-standin","base":"dicta-il/dictabert","labels":["abusive","hate","violence","pornographic","non_offensive"]}"""))
        val info = assertIs<ShomerResult.Success<com.shomer.sdk.models.ModelInfoResult>>(api.modelInfo()).value
        assertEquals(5, info.labels.size)
    }

    @Test
    fun rateLimit_429_mapsToRateLimitError_andDoesNotRetry() = runTest {
        server.enqueue(MockResponse().setResponseCode(429).setHeader("Retry-After", "30").setBody("rate limited"))
        val result = api.classify("שלום")
        val error = assertIs<ShomerResult.Failure>(result).error
        val rate = assertIs<ShomerError.RateLimitError>(error)
        assertEquals(30, rate.retryAfterSeconds)
        assertEquals(1, server.requestCount, "429 must NOT be retried")
    }

    @Test
    fun validation_422_mapsToValidationError() = runTest {
        server.enqueue(MockResponse().setResponseCode(422).setBody("""{"detail":"text too long"}"""))
        val error = assertIs<ShomerResult.Failure>(api.classify("שלום")).error
        assertIs<ShomerError.ValidationError>(error)
        assertEquals(1, server.requestCount)
    }

    @Test
    fun serverError_500_retriesThenFails() = runTest {
        repeat(3) { server.enqueue(MockResponse().setResponseCode(500).setBody("boom")) }
        val error = assertIs<ShomerResult.Failure>(api.classify("שלום")).error
        val server500 = assertIs<ShomerError.ServerError>(error)
        assertEquals(500, server500.httpStatus)
        assertEquals(3, server.requestCount, "5xx must be retried up to maxRetries")
    }

    @Test
    fun serverError_500_thenSuccess_recovers() = runTest {
        server.enqueue(MockResponse().setResponseCode(500))
        server.enqueue(MockResponse().setResponseCode(500))
        server.enqueue(
            MockResponse().setResponseCode(200).setBody(
                """{"is_offensive":false,"category":"non_offensive","confidence":0.7,"model":"v1.0-standin","latency_ms":5}""",
            ),
        )
        val result = api.classify("שלום")
        assertIs<ShomerResult.Success<*>>(result)
        assertEquals(3, server.requestCount)
    }

    @Test
    fun malformedJson_200_mapsToParseError() = runTest {
        server.enqueue(MockResponse().setResponseCode(200).setBody("not json at all"))
        val error = assertIs<ShomerResult.Failure>(api.classify("שלום")).error
        assertIs<ShomerError.ParseError>(error)
    }

    @Test
    fun blankText_failsLocally_withoutNetworkCall() = runTest {
        val error = assertIs<ShomerResult.Failure>(api.classify("   ")).error
        assertIs<ShomerError.ValidationError>(error)
        assertEquals(0, server.requestCount, "client-side validation must short-circuit")
    }
}
