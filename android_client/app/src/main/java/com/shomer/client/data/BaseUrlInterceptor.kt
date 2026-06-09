package com.shomer.client.data

import android.util.Log
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.Interceptor
import okhttp3.Response
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Rewrites every outgoing request's scheme/host/port to the server URL currently
 * stored in [SettingsRepository], read fresh on each call.
 *
 * Why this exists: Retrofit fixes its base URL once when the singleton is built at
 * app startup, so changing the URL in Settings used to require a cold restart. With
 * this interceptor the path/query from the Retrofit endpoint annotations are kept,
 * but the host is taken from the live setting — so a Save in Settings (or the
 * onboarding connection editor) takes effect on the very next request.
 *
 * The read uses runBlocking on OkHttp's background dispatcher thread (never the main
 * thread); DataStore returns its cached value, so this is a cheap in-memory read.
 */
@Singleton
class BaseUrlInterceptor @Inject constructor(
    private val settings: SettingsRepository,
) : Interceptor {

    override fun intercept(chain: Interceptor.Chain): Response {
        val request = chain.request()

        val raw = runCatching { runBlocking { settings.serverUrl.first() } }
            .getOrDefault(SettingsRepository.DEFAULT_SERVER_URL)
        val target = raw.toHttpUrlOrNull()

        if (target == null) {
            Log.w(TAG, "Stored server URL '$raw' is invalid; using request URL as-is")
            return chain.proceed(request)
        }

        val newUrl = request.url.newBuilder()
            .scheme(target.scheme)
            .host(target.host)
            .port(target.port)
            .build()

        return chain.proceed(request.newBuilder().url(newUrl).build())
    }

    companion object {
        private const val TAG = "BaseUrlInterceptor"
    }
}
