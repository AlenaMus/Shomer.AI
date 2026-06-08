package com.shomer.client.data

import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.PATCH
import retrofit2.http.POST
import retrofit2.http.Path
import retrofit2.http.Query

/**
 * Retrofit interface for the parent-mode API.
 *
 * Auth: all endpoints except registerParent use the Bearer parent token added by
 * AuthInterceptor. registerParent hits POST /v1/parent/register which is on the
 * server auth allowlist (no token required — it bootstraps auth).
 *
 * Base URL is provided by NetworkModule (from SettingsRepository / DataStore).
 *
 * Server contract source of truth:
 *   - server/app/identity/router.py  (register, listChildren, setFcmToken)
 *   - server/app/flagged/router.py   (listAlerts, getAlert, react)
 *   - server/app/digest/router.py    (getDigests)
 */
interface ParentApi {

    // -------------------------------------------------------------------------
    // Identity: parent register + children
    // -------------------------------------------------------------------------

    /**
     * POST /v1/parent/register
     * No auth required (on the server allowlist — bootstraps parent credentials).
     * Response 201 on success; stores parent_token in TokenStore.
     */
    @POST("v1/parent/register")
    suspend fun registerParent(@Body body: ParentRegisterRequest): ParentRegisterResponse

    /**
     * GET /v1/parent/children
     * Auth: Bearer parent token.
     * Returns all children registered under the authenticated parent.
     */
    @GET("v1/parent/children")
    suspend fun listChildren(): List<ChildInfo>

    // -------------------------------------------------------------------------
    // FCM token registration
    // -------------------------------------------------------------------------

    /**
     * PATCH /v1/device/fcm-token
     * Auth: Bearer device token (parent or child role both accepted).
     * Stores or updates the FCM push token for the calling device.
     * Call this from onNewToken() in ShomerFcmService.
     */
    @PATCH("v1/device/fcm-token")
    suspend fun setFcmToken(@Body body: FcmTokenRequest): FcmTokenResponse

    // -------------------------------------------------------------------------
    // Alerts
    // -------------------------------------------------------------------------

    /**
     * GET /v1/parent/alerts
     * Auth: Bearer parent token.
     *
     * Query parameters (all optional):
     *   child_id      — filter to a specific child; null = all children
     *   since         — epoch-seconds lower bound on created_at; null = no bound
     *   status        — filter by FlaggedStatus string; null = no filter
     *   include_acked — include acknowledged/labeled events (default false)
     *   limit         — max events returned (1-200, default 50)
     *
     * Returns newest-first list of FlaggedEventOut.
     */
    @GET("v1/parent/alerts")
    suspend fun listAlerts(
        @Query("child_id") childId: String? = null,
        @Query("since") since: Double? = null,
        @Query("status") status: String? = null,
        @Query("include_acked") includeAcked: Boolean = false,
        @Query("limit") limit: Int = 50,
    ): List<FlaggedEventOut>

    /**
     * GET /v1/parent/alerts/{flag_id}
     * Auth: Bearer parent token.
     * Returns a single FlaggedEventOut or 404 if not found / not owned.
     */
    @GET("v1/parent/alerts/{flag_id}")
    suspend fun getAlert(@Path("flag_id") flagId: String): FlaggedEventOut

    /**
     * POST /v1/parent/alerts/{flag_id}/react
     * Auth: Bearer parent token.
     * Applies a parent reaction. Returns updated FlaggedEventOut.
     *
     * Validation (mirrored from server):
     *   action="label"    → label field required ("offensive"|"not_offensive")
     *   action="severity" → severity field required ("low"|"medium"|"high"|"critical")
     *   action="acknowledge" → label/severity ignored
     */
    @POST("v1/parent/alerts/{flag_id}/react")
    suspend fun react(
        @Path("flag_id") flagId: String,
        @Body body: ReactRequest,
    ): FlaggedEventOut

    // -------------------------------------------------------------------------
    // Digests
    // -------------------------------------------------------------------------

    /**
     * GET /v1/parent/digests/{date}
     * Auth: Bearer parent token.
     * date: "YYYY-MM-DD" (server-local date).
     * Optional child_id query param to scope to one child.
     * Returns list of ChildDigestOut; 404 if no digests found for that date.
     */
    @GET("v1/parent/digests/{date}")
    suspend fun getDigests(
        @Path("date") date: String,
        @Query("child_id") childId: String? = null,
    ): List<ChildDigestOut>
}
