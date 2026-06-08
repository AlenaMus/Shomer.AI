package com.shomer.sdk

/**
 * Typed configuration for a [ShomerClient]. See design.md §2.4 / §6.2.
 *
 * @property baseUrl FastAPI server base URL, e.g. "http://10.0.2.2:8000/" (emulator)
 *   or "http://<PC-LAN-IP>:8000/" (physical device). A trailing slash is tolerated.
 * @property apiKey Reserved for Phase-9 Gatekeeper auth (design.md §11.3). When non-null
 *   the SDK sends `Authorization: Bearer <apiKey>`; null = no auth header (LAN MVP).
 */
data class SdkConfig(
    val baseUrl: String,
    val connectTimeoutMs: Long = 10_000L,
    val readTimeoutMs: Long = 60_000L,          // text classify
    val imageReadTimeoutMs: Long = 180_000L,    // image classify (Tesseract is slow)
    val maxRetries: Int = 3,                    // total attempts: first + (maxRetries-1) retries
    val initialBackoffMs: Long = 1_000L,        // 1s → 2s → 4s
    val apiKey: String? = null,
    val sdkVersion: String = SdkBuildConfig.SDK_VERSION,
)
