package com.shomer.client.data

import okhttp3.Interceptor
import okhttp3.Response
import javax.inject.Inject
import javax.inject.Singleton

/**
 * OkHttp interceptor that adds the Authorization: Bearer header to all /v1/
 * requests EXCEPT /v1/pair (which is how the token is obtained in the first place).
 *
 * The auth allowlist on the server side mirrors this:
 *   - /health, /classify, /classify-image, /metrics: no auth (legacy POC paths)
 *   - /v1/pair: no auth (bootstrap)
 *   - all other /v1/ paths: Bearer required
 *
 * If no token is available (device not yet paired), the header is not added and
 * the server will respond with 401. MonitorUploader checks isPaired() before
 * attempting uploads and no-ops when not paired.
 */
@Singleton
class AuthInterceptor @Inject constructor(
    private val tokenStore: TokenStore,
) : Interceptor {

    override fun intercept(chain: Interceptor.Chain): Response {
        val request = chain.request()
        val path = request.url.encodedPath

        // /v1/pair is unauthenticated — skip the header.
        // Also skip legacy POC paths (/classify, /health, /metrics).
        val needsAuth = path.startsWith("/v1/") && path != "/v1/pair"
        if (!needsAuth) return chain.proceed(request)

        val token = tokenStore.getDeviceToken()
        if (token == null) {
            // Not paired yet — proceed without auth. The server returns 401;
            // MonitorUploader handles this by not uploading when not paired.
            return chain.proceed(request)
        }

        val authedRequest = request.newBuilder()
            .header("Authorization", "Bearer $token")
            .build()
        return chain.proceed(authedRequest)
    }
}
