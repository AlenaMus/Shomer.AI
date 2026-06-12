package com.shomer.client.data

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

// ---------------------------------------------------------------------------
// Legacy POC models — kept for the debug classify screen (available in both
// the poc and client flavors as a server-connectivity test aid).
// ---------------------------------------------------------------------------

@JsonClass(generateAdapter = true)
data class ClassifyRequest(
    val text: String,
    @Json(name = "child_id") val childId: String? = null,
    @Json(name = "message_id") val messageId: String? = null,
)

@JsonClass(generateAdapter = true)
data class ClassifyResponse(
    @Json(name = "is_offensive") val isOffensive: Boolean,
    val category: String,
    val confidence: Double,
    val model: String,
    @Json(name = "latency_ms") val latencyMs: Int,
)

@JsonClass(generateAdapter = true)
data class HealthResponse(
    val status: String,
    @Json(name = "ollama_reachable") val ollamaReachable: Boolean,
    val model: String,
)

@JsonClass(generateAdapter = true)
data class ClassifyImageResponse(
    @Json(name = "is_offensive") val isOffensive: Boolean,
    val category: String,
    val confidence: Double,
    val model: String,
    @Json(name = "latency_ms") val latencyMs: Int,
    @Json(name = "extracted_text") val extractedText: String,
    val backend: String,
    val strategy: String,
)

// ---------------------------------------------------------------------------
// Monitor wire models — mirror server/app/schemas.py EXACTLY.
// Field names, types, and constraints are FROZEN by the server contract.
// The server tests pin these; do not rename fields without server coordination.
// ---------------------------------------------------------------------------

/**
 * A single captured message event.
 *
 * Mapping to server MonitorEvent schema:
 *   client_msg_id   : String   — device idempotency key, UUID per event
 *   app_package     : String   — source app, e.g. "com.whatsapp"
 *   text            : String   — captured Hebrew text (1–4000 chars)
 *   text_hash       : String   — sha256(text) hex, for server dedup
 *   captured_at     : Double   — epoch seconds from client clock
 *   direction       : String   — "inbound" | "outbound"
 *   conversation_id : String?  — stable per-thread key: sha256(package:windowTitle)[:32].
 *                                 Null when the window title is not available; the server
 *                                 falls back to app_package for history scoping in that case.
 *                                 NEVER set on screenshot/OCR events — the server mints
 *                                 its own conversation_id per screenshot.
 */
@JsonClass(generateAdapter = true)
data class MonitorEvent(
    @Json(name = "client_msg_id") val clientMsgId: String,
    @Json(name = "app_package") val appPackage: String,
    val text: String,
    @Json(name = "text_hash") val textHash: String,
    @Json(name = "captured_at") val capturedAt: Double,
    val direction: String = "inbound",   // "inbound" | "outbound"
    @Json(name = "conversation_id") val conversationId: String? = null,
)

/**
 * Batch request body for POST /v1/monitor/events.
 *
 * Mapping to server MonitorBatchRequest:
 *   session_id : String          — client session identifier (UUID per app session)
 *   child_id   : String          — opaque child identifier from TokenStore
 *   events     : List<MonitorEvent>  — up to 50 events per batch
 */
@JsonClass(generateAdapter = true)
data class MonitorBatchRequest(
    @Json(name = "session_id") val sessionId: String,
    @Json(name = "child_id") val childId: String,
    val events: List<MonitorEvent>,
)

/**
 * Per-event acknowledgement in the batch response.
 *
 * Mapping to server MonitorEventAck:
 *   client_msg_id : String   — echoes back for correlation
 *   status        : String   — "processed" | "deduped" | "filtered" | "error"
 *   flagged       : Boolean
 *   flag_id       : String?
 */
@JsonClass(generateAdapter = true)
data class MonitorEventAck(
    @Json(name = "client_msg_id") val clientMsgId: String,
    val status: String,
    val flagged: Boolean = false,
    @Json(name = "flag_id") val flagId: String? = null,
)

/**
 * Batch response from POST /v1/monitor/events.
 *
 * Mapping to server MonitorBatchResponse:
 *   accepted : Int
 *   deduped  : Int
 *   flagged  : Int
 *   acks     : List<MonitorEventAck>
 */
@JsonClass(generateAdapter = true)
data class MonitorBatchResponse(
    val accepted: Int,
    val deduped: Int,
    val flagged: Int,
    val acks: List<MonitorEventAck>,
)

/**
 * Response from POST /v1/monitor/image (screenshot OCR ingest).
 *
 * Extends the shape of MonitorBatchResponse with an extra ocr_text_len field
 * (the number of characters the server's Tesseract OCR extracted from the image).
 * A value of 0 means the screenshot contained no recognizable text; the upload was
 * accepted but nothing was ingested into the pipeline.
 *
 * Mapping to server ScreenshotIngestResponse (to be added alongside the endpoint):
 *   accepted     : Int
 *   deduped      : Int
 *   flagged      : Int
 *   acks         : List<MonitorEventAck>
 *   ocr_text_len : Int — 0 if OCR found no text
 */
@JsonClass(generateAdapter = true)
data class ScreenshotIngestResponse(
    val accepted: Int,
    val deduped: Int,
    val flagged: Int,
    val acks: List<MonitorEventAck>,
    @Json(name = "ocr_text_len") val ocrTextLen: Int = 0,
)

// ---------------------------------------------------------------------------
// Identity / Pairing models
// ---------------------------------------------------------------------------

/**
 * Body for POST /v1/pair.
 *
 * Mapping to server pairing endpoint:
 *   code               : String — 6-8 digit OTP from parent dashboard
 *   device_fingerprint : String — stable device identifier (no PII)
 */
@JsonClass(generateAdapter = true)
data class PairRequest(
    val code: String,
    @Json(name = "device_fingerprint") val deviceFingerprint: String,
)

/**
 * Response from POST /v1/pair.
 *
 * Mapping to server pairing response:
 *   device_token : String — Bearer token for all subsequent /v1/ calls
 *   child_id     : String — opaque child identifier to include in every batch
 *   role         : String — "child" | "parent"
 */
@JsonClass(generateAdapter = true)
data class PairResponse(
    @Json(name = "device_token") val deviceToken: String,
    @Json(name = "child_id") val childId: String,
    val role: String,
)

/**
 * Body for PATCH /v1/device/fcm-token.
 * Stubbed — the call is made after pairing but the FCM SDK is not wired yet
 * (parent-mode pass 2). The field name matches the server schema.
 */
@JsonClass(generateAdapter = true)
data class FcmTokenRequest(
    @Json(name = "fcm_token") val fcmToken: String,
)

@JsonClass(generateAdapter = true)
data class FcmTokenResponse(
    val ok: Boolean,
)

// ---------------------------------------------------------------------------
// Parent-mode wire models — mirror server/app/flagged/router.py +
// server/app/digest/router.py + server/app/identity/router.py EXACTLY.
// Field names are FROZEN by the server contract. The server tests pin them.
// Any field name change here WILL break integration without a corresponding
// server change.
// ---------------------------------------------------------------------------

/**
 * A flagged event returned by GET /v1/parent/alerts and GET /v1/parent/alerts/{id}.
 *
 * Wire mapping (FlaggedEventOut in server/app/flagged/router.py):
 *   flag_id          : String
 *   child_id         : String
 *   created_at       : Double   — epoch seconds (float on server)
 *   app_package      : String
 *   direction        : String   — "inbound" | "outbound"
 *   label            : String   — classifier label: abusive|hate|violence|pornographic|non_offensive
 *   severity         : String   — low|medium|high|critical
 *   quote            : String   — truncated message text (≤200 chars)
 *   explanation      : String   — human-readable explanation from context agent
 *   source           : String   — classifier source identifier
 *   status           : String   — alerted|review_needed|acknowledged|labeled
 *   parent_label     : String?  — human verdict set by parent ("offensive"|"not_offensive")
 *   parent_severity  : String?  — parent severity override
 *   acknowledged_at  : Double?  — epoch seconds when acknowledged (null if not yet)
 */
@JsonClass(generateAdapter = true)
data class FlaggedEventOut(
    @Json(name = "flag_id") val flagId: String,
    @Json(name = "child_id") val childId: String,
    @Json(name = "created_at") val createdAt: Double,
    @Json(name = "app_package") val appPackage: String,
    val direction: String,
    val label: String,
    val severity: String,
    val quote: String,
    val explanation: String,
    val source: String,
    val status: String,
    @Json(name = "parent_label") val parentLabel: String? = null,
    @Json(name = "parent_severity") val parentSeverity: String? = null,
    @Json(name = "acknowledged_at") val acknowledgedAt: Double? = null,
)

/**
 * Body for POST /v1/parent/alerts/{flag_id}/react.
 *
 * Wire mapping (ReactRequest in server/app/flagged/router.py):
 *   action   : String  — "acknowledge" | "label" | "severity"
 *   label    : String? — required when action=="label": "offensive"|"not_offensive"
 *   severity : String? — required when action=="severity": "low"|"medium"|"high"|"critical"
 */
@JsonClass(generateAdapter = true)
data class ReactRequest(
    val action: String,            // "acknowledge" | "label" | "severity"
    val label: String? = null,     // "offensive" | "not_offensive"  (label action only)
    val severity: String? = null,  // "low"|"medium"|"high"|"critical" (severity action only)
)

/**
 * A single entry in a ChildDigest.
 *
 * Wire mapping (DigestEntryOut in server/app/digest/router.py):
 *   flag_id     : String
 *   app_package : String
 *   direction   : String
 *   label       : String
 *   severity    : String
 *   quote       : String
 *   status      : String
 *   created_at  : Double — epoch seconds
 */
@JsonClass(generateAdapter = true)
data class DigestEntryOut(
    @Json(name = "flag_id") val flagId: String,
    @Json(name = "app_package") val appPackage: String,
    val direction: String,
    val label: String,
    val severity: String,
    val quote: String,
    val status: String,
    @Json(name = "created_at") val createdAt: Double,
)

/**
 * Daily digest for one child, returned by GET /v1/parent/digests/{date}.
 *
 * Wire mapping (ChildDigestOut in server/app/digest/router.py):
 *   child_id      : String
 *   parent_id     : String
 *   date          : String  — "YYYY-MM-DD"
 *   generated_at  : Double  — epoch seconds
 *   total_flagged : Int
 *   review_needed : Int
 *   by_severity   : Map<String,Int>  — {"low":N,"medium":N,...}
 *   by_label      : Map<String,Int>  — {"abusive":N,...}
 *   entries       : List<DigestEntryOut>
 */
@JsonClass(generateAdapter = true)
data class ChildDigestOut(
    @Json(name = "child_id") val childId: String,
    @Json(name = "parent_id") val parentId: String,
    val date: String,
    @Json(name = "generated_at") val generatedAt: Double,
    @Json(name = "total_flagged") val totalFlagged: Int,
    @Json(name = "review_needed") val reviewNeeded: Int,
    @Json(name = "by_severity") val bySeverity: Map<String, Int>,
    @Json(name = "by_label") val byLabel: Map<String, Int>,
    val entries: List<DigestEntryOut>,
)

/**
 * Body for POST /v1/parent/register.
 *
 * Wire mapping (ParentRegisterRequest in server/app/identity/router.py):
 *   display_name : String (optional, max 128 chars)
 */
@JsonClass(generateAdapter = true)
data class ParentRegisterRequest(
    @Json(name = "display_name") val displayName: String = "",
)

/**
 * Response from POST /v1/parent/register.
 *
 * Wire mapping (ParentRegisterResponse in server/app/identity/router.py):
 *   parent_id    : String — opaque UUID
 *   parent_token : String — opaque long-lived secret; store in EncryptedSharedPreferences
 */
@JsonClass(generateAdapter = true)
data class ParentRegisterResponse(
    @Json(name = "parent_id") val parentId: String,
    @Json(name = "parent_token") val parentToken: String,
)

/**
 * One child record in GET /v1/parent/children.
 *
 * Wire mapping (ChildInfo in server/app/identity/router.py):
 *   child_id     : String
 *   display_name : String
 *   created_at   : Double — epoch seconds
 */
@JsonClass(generateAdapter = true)
data class ChildInfo(
    @Json(name = "child_id") val childId: String,
    @Json(name = "display_name") val displayName: String,
    @Json(name = "created_at") val createdAt: Double,
)
