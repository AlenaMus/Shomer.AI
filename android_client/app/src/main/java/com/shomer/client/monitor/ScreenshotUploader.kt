package com.shomer.client.monitor

import android.graphics.Bitmap
import android.util.Log
import com.shomer.client.data.MonitorApi
import com.shomer.client.data.TokenStore
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.ByteArrayOutputStream
import java.util.UUID
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Compresses a captured screenshot and uploads it to POST /v1/monitor/image.
 *
 * Called from [com.shomer.client.capture.ScreenshotCoordinator] (Dispatchers.Default
 * coroutine) after de-dup + rate-limit checks have passed.
 *
 * Upload steps:
 *   1. Compress the cropped bitmap to JPEG: downscale longest edge to MAX_EDGE_PX,
 *      quality JPEG_QUALITY. Blocking — runs on Dispatchers.IO.
 *   2. Build a multipart/form-data request with:
 *        image          — JPEG bytes
 *        child_id       — from TokenStore
 *        session_id     — UUID4 per upload (the server doesn't mandate a session grouping
 *                          here; we use a fresh UUID to satisfy the field)
 *        client_msg_id  — UUID4 idempotency key
 *        captured_at    — epoch seconds (Double)
 *        direction      — "screen"
 *   3. On 2xx: record in MonitorActivityLog (direction "screen") as SENT, UNLESS
 *      ocr_text_len == 0 (blank screenshot — no text found by the server OCR).
 *   4. On 4xx / 5xx: log and rethrow so ScreenshotCoordinator can log the failure.
 *
 * The Authorization: Bearer header is injected by AuthInterceptor at the OkHttp layer.
 * The base URL is rewritten by BaseUrlInterceptor (live DataStore read per request).
 */
@Singleton
class ScreenshotUploader @Inject constructor(
    private val monitorApi: MonitorApi,
    private val tokenStore: TokenStore,
    private val activityLog: MonitorActivityLog,
) {

    /**
     * POST a pre-compressed JPEG to /v1/monitor/image.
     *
     * The caller compresses the bitmap and recycles it BEFORE calling this, so no
     * large bitmap is held in memory during the (multi-second) network upload —
     * only the small JPEG byte array. See [ScreenshotCoordinator].
     *
     * @param jpegBytes The already-compressed JPEG screenshot.
     * @param packageName The foreground app package (for log context only; not sent to the server).
     */
    suspend fun upload(jpegBytes: ByteArray, packageName: String) {
        val childId = tokenStore.getChildId() ?: run {
            Log.w(TAG, "Upload skipped: no child_id (not paired)")
            return
        }

        val clientMsgId = UUID.randomUUID().toString()
        val capturedAt = System.currentTimeMillis() / 1000.0

        val imagePart = MultipartBody.Part.createFormData(
            "image",
            "capture.jpg",
            jpegBytes.toRequestBody("image/jpeg".toMediaType()),
        )
        val childIdPart    = childId.toRequestBody("text/plain".toMediaType())
        val sessionIdPart  = UUID.randomUUID().toString().toRequestBody("text/plain".toMediaType())
        val msgIdPart      = clientMsgId.toRequestBody("text/plain".toMediaType())
        val capturedAtPart = capturedAt.toString().toRequestBody("text/plain".toMediaType())
        val directionPart  = "screen".toRequestBody("text/plain".toMediaType())

        Log.d(TAG, "Uploading screenshot: pkg=$packageName msgId=$clientMsgId size=${jpegBytes.size}B")

        val response = monitorApi.ingestImage(
            image = imagePart,
            childId = childIdPart,
            sessionId = sessionIdPart,
            clientMsgId = msgIdPart,
            capturedAt = capturedAtPart,
            direction = directionPart,
        )

        Log.i(
            TAG,
            "Screenshot upload ok: accepted=${response.accepted} " +
                "deduped=${response.deduped} flagged=${response.flagged} " +
                "ocr_text_len=${response.ocrTextLen}",
        )

        // Record in the activity log only when the server found text in the image.
        // A blank screenshot (ocr_text_len == 0) is valid (no text found) but there
        // is nothing meaningful to show the parent; skip the log entry.
        if (response.ocrTextLen > 0) {
            activityLog.recordCaptured(
                clientMsgId = clientMsgId,
                text = "[screenshot — ${response.ocrTextLen} chars OCR'd]",
                direction = "screen",
                capturedAtMs = (capturedAt * 1000).toLong(),
            )
            activityLog.markSent(listOf(clientMsgId))
        }
    }

    companion object {
        private const val TAG = "ScreenshotUploader"
        private const val MAX_EDGE_PX = 1280
        private const val JPEG_QUALITY = 60

        /**
         * Downscale [src] so the longest edge is at most [MAX_EDGE_PX], then compress
         * to JPEG at [JPEG_QUALITY].  CPU-bound; call on Dispatchers.IO.
         *
         * Exposed so the caller can compress and then immediately recycle the source
         * bitmap, holding only the small JPEG during the network upload.
         */
        fun compress(src: Bitmap): ByteArray {
            val scaledBitmap = if (src.width > MAX_EDGE_PX || src.height > MAX_EDGE_PX) {
                val scale = MAX_EDGE_PX.toFloat() / maxOf(src.width, src.height)
                Bitmap.createScaledBitmap(
                    src,
                    (src.width * scale).toInt().coerceAtLeast(1),
                    (src.height * scale).toInt().coerceAtLeast(1),
                    /* filter= */ true,
                )
            } else {
                src
            }

            return ByteArrayOutputStream().use { out ->
                scaledBitmap.compress(Bitmap.CompressFormat.JPEG, JPEG_QUALITY, out)
                // Recycle the scaled copy (never the caller's src — that's recycled
                // by the caller after this returns).
                if (scaledBitmap !== src) scaledBitmap.recycle()
                out.toByteArray()
            }
        }
    }
}
