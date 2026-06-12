package com.shomer.client.data

import okhttp3.MultipartBody
import okhttp3.RequestBody
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.Multipart
import retrofit2.http.PATCH
import retrofit2.http.POST
import retrofit2.http.Part
import retrofit2.http.Query

// ---------------------------------------------------------------------------
// Legacy classify API — kept for the debug classify screen.
// Routes match the existing server /classify + /classify-image + /health.
// ---------------------------------------------------------------------------

interface ApiService {
    @GET("health")
    suspend fun health(): HealthResponse

    @POST("classify")
    suspend fun classify(@Body request: ClassifyRequest): ClassifyResponse

    @Multipart
    @POST("classify-image")
    suspend fun classifyImage(
        @Part image: MultipartBody.Part,
        @Query("strategy") strategy: String? = null,
    ): ClassifyImageResponse
}

// ---------------------------------------------------------------------------
// Monitor API — POST /v1/monitor/events (Bearer auth required).
// Auth is added by AuthInterceptor at the OkHttp layer, not here.
// ---------------------------------------------------------------------------

interface MonitorApi {
    /**
     * Upload a batch of captured monitor events to the server.
     * Max 50 events per batch (enforced server-side).
     * Requires Authorization: Bearer <device_token>.
     */
    @POST("v1/monitor/events")
    suspend fun ingest(@Body batch: MonitorBatchRequest): MonitorBatchResponse

    /**
     * Upload a screenshot (JPEG) for server-side OCR + pipeline ingest.
     *
     * multipart/form-data fields (all snake_case, matching the server contract):
     *   image          — JPEG file bytes
     *   child_id       — opaque child identifier
     *   session_id     — UUID4 (groups this upload; not an auth boundary)
     *   client_msg_id  — UUID4 idempotency key
     *   captured_at    — epoch seconds as string
     *   direction      — "screen"
     *
     * Response extends MonitorBatchResponse with an additional ocr_text_len field.
     * Auth: Bearer added by AuthInterceptor. Base URL rewritten by BaseUrlInterceptor.
     */
    @Multipart
    @POST("v1/monitor/image")
    suspend fun ingestImage(
        @Part image: MultipartBody.Part,
        @Part("child_id") childId: RequestBody,
        @Part("session_id") sessionId: RequestBody,
        @Part("client_msg_id") clientMsgId: RequestBody,
        @Part("captured_at") capturedAt: RequestBody,
        @Part("direction") direction: RequestBody,
    ): ScreenshotIngestResponse
}

// ---------------------------------------------------------------------------
// Pairing API — POST /v1/pair (NO auth — this is how the token is obtained).
// Also PATCH /v1/device/fcm-token (Bearer auth — stubbed for pass 2).
// ---------------------------------------------------------------------------

interface PairingApi {
    /**
     * Exchange a 6-8 digit OTP (from the parent dashboard) for a device token.
     * This endpoint is in the auth allowlist — no Bearer header required.
     */
    @POST("v1/pair")
    suspend fun pair(@Body request: PairRequest): PairResponse

    /**
     * Register or update the FCM token associated with this device.
     * Called after pairing when a token is available.
     * Stubbed in pass 1 — FCM SDK wiring is parent-mode (pass 2).
     */
    @PATCH("v1/device/fcm-token")
    suspend fun updateFcmToken(@Body request: FcmTokenRequest): FcmTokenResponse
}
