package com.shomer.client.capture

import android.graphics.Bitmap
import android.util.Log
import com.shomer.client.monitor.ScreenshotUploader
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.withContext
import java.util.ArrayDeque
import java.util.concurrent.atomic.AtomicLong
import javax.inject.Inject
import javax.inject.Singleton
import kotlin.math.abs
import kotlin.math.min

/**
 * Coordinates the screenshot-capture pipeline:
 *
 *   ShomerAccessibilityService (WINDOW_CONTENT_CHANGED for monitored pkg)
 *       ↓  signalScreenChanged(pkg)
 *   ScreenshotCoordinator
 *       ↓  debounce 1.5s
 *       ↓  acquireBitmap via ScreenCaptureService.instance
 *       ↓  crop volatile chrome (status bar top 5%, nav bottom 12%)
 *       ↓  dHash (64-bit) — skip if Hamming distance ≤ 6 to any recent hash
 *       ↓  rate-limit: min 4s + token bucket (20 uploads / 5 min)
 *       ↓  ScreenshotUploader.upload(bitmap, pkg)
 *
 * All bitmap work runs on Dispatchers.Default (never the accessibility main thread).
 *
 * De-dup strategy (see decision doc screenshot-ocr-capture.decision.md):
 *   - Crop volatile chrome FIRST so status-bar clock and compose-box text don't
 *     affect the hash and cause spurious "changed" signals.
 *   - Downscale cropped image to 9×8 grayscale (= 72 pixels) and compute a 64-bit
 *     dHash: for each row, compare each pixel to its right neighbour; set bit if
 *     current < next (brighter → darker = 1). Result is a Long bitmask.
 *   - Keep a ring buffer of the last HASH_RING_SIZE hashes.  Skip upload if the
 *     minimum Hamming distance to any buffered hash is ≤ HAMMING_THRESHOLD.
 *   - Rate limit: enforce MIN_UPLOAD_INTERVAL_MS between consecutive uploads plus
 *     a token bucket that allows at most BUCKET_CAPACITY uploads per BUCKET_WINDOW_MS.
 */
@Singleton
class ScreenshotCoordinator @Inject constructor(
    private val screenshotUploader: ScreenshotUploader,
) {
    private val scope = CoroutineScope(Dispatchers.Default + SupervisorJob())

    // Per-package debounce job: reset on each new CONTENT_CHANGED signal.
    private val debounceJobs = mutableMapOf<String, Job>()

    // Serializes the whole acquire→compress→upload path so at most ONE screenshot
    // is ever in flight.  There is no urgency to capture every frame, so if one is
    // already being processed we DROP the new capture rather than queue it — this
    // keeps both server load and on-device memory (bitmaps) bounded.
    private val uploadMutex = Mutex()

    // Hash ring buffer: stores the last N dHashes for perceptual dedup.
    private val hashRing = ArrayDeque<Long>(HASH_RING_SIZE)

    // Rate-limit state
    private val lastUploadMs = AtomicLong(0L)

    // Token bucket: refills 1 token every BUCKET_REFILL_INTERVAL_MS.
    private var bucketTokens = BUCKET_CAPACITY.toDouble()
    private var lastRefillMs = System.currentTimeMillis()

    // Track whether a ScreenCaptureService projection is currently live.
    @Volatile
    private var projectionLive = false

    // Uploaded screenshot count (for the status screen).
    val uploadedCount = AtomicLong(0L)

    // -------------------------------------------------------------------------
    // Called by ScreenCaptureService when the projection becomes live / stops.
    // -------------------------------------------------------------------------

    fun onProjectionStarted(@Suppress("UNUSED_PARAMETER") service: ScreenCaptureService) {
        projectionLive = true
        Log.i(TAG, "Projection live — screenshot capture enabled")
    }

    fun onProjectionStopped() {
        projectionLive = false
        Log.i(TAG, "Projection stopped — screenshot capture disabled")
    }

    // -------------------------------------------------------------------------
    // Primary entry point: called by ShomerAccessibilityService on
    // TYPE_WINDOW_CONTENT_CHANGED for a monitored foreground package.
    // This MUST NOT block the a11y main thread.
    // -------------------------------------------------------------------------

    fun signalScreenChanged(packageName: String) {
        if (!projectionLive) return   // No projection — silently no-op.

        // Cancel any pending debounce for this package; new content resets the timer.
        debounceJobs[packageName]?.cancel()
        debounceJobs[packageName] = scope.launch {
            delay(DEBOUNCE_MS)
            captureAndProcess(packageName)
        }
    }

    // -------------------------------------------------------------------------
    // Internal: acquire → crop → hash → rate-limit → upload
    // -------------------------------------------------------------------------

    private suspend fun captureAndProcess(packageName: String) {
        // Serialize: only one screenshot is processed/uploaded at a time. If one is
        // already in flight, drop this capture (no urgency) so bitmaps and uploads
        // never pile up.
        if (!uploadMutex.tryLock()) {
            Log.d(TAG, "Busy with a screenshot — dropping capture (pkg=$packageName)")
            return
        }
        try {
            val service = ScreenCaptureService.instance ?: return
            val raw = service.latestBitmap() ?: return

            val cropped = try {
                cropVolatileChrome(raw)
            } catch (e: Exception) {
                Log.w(TAG, "Crop failed: ${e.message}")
                raw
            }

            val hash = dHash(cropped)

            if (isDuplicate(hash)) {
                Log.d(TAG, "dHash dedup skip: Hamming distance ≤ $HAMMING_THRESHOLD (pkg=$packageName)")
                if (cropped !== raw) cropped.recycle()
                raw.recycle()
                return
            }

            if (!checkRateLimit()) {
                Log.d(TAG, "Rate-limit drop (pkg=$packageName)")
                if (cropped !== raw) cropped.recycle()
                raw.recycle()
                return
            }

            // Compress to a small JPEG and FREE the bitmaps BEFORE the network call,
            // so a multi-MB bitmap is never held during a multi-second upload.
            val jpeg = withContext(Dispatchers.IO) { ScreenshotUploader.compress(cropped) }
            if (cropped !== raw) cropped.recycle()
            raw.recycle()

            // Record the hash before uploading (prevents duplicate in-flight uploads).
            addHashToRing(hash)
            lastUploadMs.set(System.currentTimeMillis())

            Log.d(TAG, "Screenshot capture: uploading ${jpeg.size}B for pkg=$packageName hash=${hash.toHex()}")
            try {
                screenshotUploader.upload(jpeg, packageName)
                uploadedCount.incrementAndGet()
            } catch (e: Exception) {
                Log.w(TAG, "Screenshot upload failed: ${e.message}")
            }

            // Deliberate spacing between screenshots — no urgency; keeps server load
            // and battery low. New captures during this window are dropped (tryLock).
            delay(UPLOAD_SPACING_MS)
        } finally {
            uploadMutex.unlock()
        }
    }

    // -------------------------------------------------------------------------
    // Crop volatile chrome
    // -------------------------------------------------------------------------

    /**
     * Remove the top 5% (status bar: clock, battery, signal) and the bottom 12%
     * (compose / navigation bar) before hashing.
     *
     * These regions change every second (clock) or with every character typed
     * (compose box), so including them would cause dHash to see a "changed" image
     * even when the actual chat content has not changed.
     */
    private fun cropVolatileChrome(src: Bitmap): Bitmap {
        val topCrop = (src.height * CROP_TOP_FRACTION).toInt().coerceAtLeast(1)
        val bottomCrop = (src.height * CROP_BOTTOM_FRACTION).toInt().coerceAtLeast(1)
        val usableHeight = src.height - topCrop - bottomCrop
        if (usableHeight <= 0) return src
        return Bitmap.createBitmap(src, 0, topCrop, src.width, usableHeight)
    }

    // -------------------------------------------------------------------------
    // dHash (difference hash) — 64-bit perceptual hash
    // -------------------------------------------------------------------------

    /**
     * Compute a 64-bit dHash of [src]:
     *   1. Downscale to 9×8 grayscale.
     *   2. For each of the 8 rows, compare each of the 8 adjacent pixel pairs
     *      (left vs right). Set the corresponding bit if left < right.
     *
     * Returns a Long bitmask (bit 0 = row 0, col 0 pair; bit 63 = row 7, col 7 pair).
     *
     * dHash is robust to minor colour shifts, small crops, and compression artefacts
     * (all of which happen between consecutive screen frames), but sensitive to
     * layout changes (new message bubbles appearing or scrolling).
     */
    private fun dHash(src: Bitmap): Long {
        // Downscale to 9×8.
        val small = Bitmap.createScaledBitmap(src, DHASH_WIDTH + 1, DHASH_HEIGHT, /* filter= */ false)
        var hash = 0L
        var bit = 0
        for (row in 0 until DHASH_HEIGHT) {
            for (col in 0 until DHASH_WIDTH) {
                val left = grayValue(small.getPixel(col, row))
                val right = grayValue(small.getPixel(col + 1, row))
                if (left < right) hash = hash or (1L shl bit)
                bit++
            }
        }
        small.recycle()
        return hash
    }

    /** Compute luminance (0–255) from an ARGB pixel using BT.601 coefficients. */
    private fun grayValue(argb: Int): Int {
        val r = (argb shr 16) and 0xFF
        val g = (argb shr 8) and 0xFF
        val b = argb and 0xFF
        return (0.299 * r + 0.587 * g + 0.114 * b).toInt()
    }

    /** Count differing bits between two 64-bit hashes (Hamming distance). */
    private fun hammingDistance(a: Long, b: Long): Int = java.lang.Long.bitCount(a xor b)

    private fun isDuplicate(hash: Long): Boolean {
        synchronized(hashRing) {
            return hashRing.any { hammingDistance(hash, it) <= HAMMING_THRESHOLD }
        }
    }

    private fun addHashToRing(hash: Long) {
        synchronized(hashRing) {
            if (hashRing.size >= HASH_RING_SIZE) hashRing.pollFirst()
            hashRing.addLast(hash)
        }
    }

    // -------------------------------------------------------------------------
    // Rate limiting
    // -------------------------------------------------------------------------

    /**
     * Two-layer rate limit:
     *   1. Minimum interval: at least MIN_UPLOAD_INTERVAL_MS between uploads.
     *   2. Token bucket: consume 1 token; refill at 1 token per BUCKET_REFILL_INTERVAL_MS;
     *      max BUCKET_CAPACITY tokens. Drops when bucket is empty.
     *
     * Returns true if the upload is allowed, false if it should be dropped.
     */
    private fun checkRateLimit(): Boolean {
        val now = System.currentTimeMillis()

        // Minimum interval check.
        val elapsed = now - lastUploadMs.get()
        if (elapsed < MIN_UPLOAD_INTERVAL_MS) return false

        // Token bucket refill.
        synchronized(this) {
            val refillMs = now - lastRefillMs
            val refillTokens = refillMs.toDouble() / BUCKET_REFILL_INTERVAL_MS.toDouble()
            bucketTokens = min(BUCKET_CAPACITY.toDouble(), bucketTokens + refillTokens)
            lastRefillMs = now

            if (bucketTokens < 1.0) return false
            bucketTokens -= 1.0
        }
        return true
    }

    companion object {
        private const val TAG = "ScreenshotCoordinator"

        // Debounce: wait this long after the last CONTENT_CHANGED before capturing.
        // Longer = fewer captures while the user scrolls/types (no urgency).
        private const val DEBOUNCE_MS = 3_000L

        // Deliberate gap held after each upload before the next screenshot may run.
        private const val UPLOAD_SPACING_MS = 2_000L

        // Chrome crop fractions.
        private const val CROP_TOP_FRACTION = 0.05    // status bar (~5% of height)
        private const val CROP_BOTTOM_FRACTION = 0.12 // compose box / nav bar (~12%)

        // dHash parameters.
        private const val DHASH_WIDTH = 8    // 8 column comparisons per row
        private const val DHASH_HEIGHT = 8   // 8 rows = 64 bits total
        private const val HAMMING_THRESHOLD = 6   // bits allowed to differ — still "same"
        // Larger ring → dedup against more recent screens (a chat scrolled back into
        // view is recognised as already-sent and skipped).
        private const val HASH_RING_SIZE = 24

        // Rate-limit parameters: min 8s between uploads.
        private const val MIN_UPLOAD_INTERVAL_MS = 8_000L

        // Token bucket: 10 uploads in 5 minutes = 1 token per 30s refill.
        private const val BUCKET_CAPACITY = 10
        private const val BUCKET_REFILL_INTERVAL_MS = 30_000L  // 1 token per 30s → 10/5min cap

        private fun Long.toHex(): String = java.lang.Long.toHexString(this)
    }
}
