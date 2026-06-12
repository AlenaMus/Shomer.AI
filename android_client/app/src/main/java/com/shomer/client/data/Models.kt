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
 * Mapping to server ScreenshotIngestResponse:
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
 *   role         : String — always "child" in this app
 */
@JsonClass(generateAdapter = true)
data class PairResponse(
    @Json(name = "device_token") val deviceToken: String,
    @Json(name = "child_id") val childId: String,
    val role: String,
)

/**
 * Body for PATCH /v1/device/fcm-token.
 * Reserved for future use — field name matches the server schema.
 */
@JsonClass(generateAdapter = true)
data class FcmTokenRequest(
    @Json(name = "fcm_token") val fcmToken: String,
)

@JsonClass(generateAdapter = true)
data class FcmTokenResponse(
    val ok: Boolean,
)
