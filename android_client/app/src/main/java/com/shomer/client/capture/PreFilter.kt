package com.shomer.client.capture

import java.security.MessageDigest
import java.util.LinkedHashMap

/**
 * On-device pre-filter — the privacy + volume gate.
 *
 * All logic is pure Kotlin with no Android framework dependencies so it is
 * unit-testable without Robolectric. The filter runs synchronously in the
 * CaptureCoordinator's debounce window before anything is written to storage.
 *
 * Filter pipeline (applied in order — first failing check drops the text):
 *   1. Length gate: drop if blank or < MIN_CHARS characters.
 *   2. Numeric-only / UI-chrome gate: drop if >80% of chars are digits or
 *      punctuation with no letter content.
 *   3. Hebrew content gate: drop if Hebrew-script letter ratio < HEBREW_RATIO_MIN.
 *      Hebrew Unicode block: U+05D0–U+05EA (basic letters).
 *   4. Rolling dedup: drop if sha256(text) was seen within DEDUP_WINDOW_MS.
 *
 * On pass: returns a FilterResult.Pass containing the sha256 hex for the wire.
 * On drop: returns FilterResult.Drop with the drop reason (for logging/metrics).
 *
 * Decisions: monitor-architecture.decision.md D4, privacy.decision.md D2.
 */
class PreFilter(
    private val minChars: Int = MIN_CHARS,
    private val hebrewRatioMin: Float = HEBREW_RATIO_MIN,
    private val dedupWindowMs: Long = DEDUP_WINDOW_MS,
    private val dedupCacheSize: Int = DEDUP_CACHE_SIZE,
) {
    /** LRU cache mapping text_hash → timestamp of last emission. */
    private val recentHashes: LinkedHashMap<String, Long> = object : LinkedHashMap<String, Long>(
        dedupCacheSize, 0.75f, true,
    ) {
        override fun removeEldestEntry(eldest: Map.Entry<String, Long>): Boolean =
            size > dedupCacheSize
    }

    sealed interface FilterResult {
        data class Pass(val textHash: String) : FilterResult
        data class Drop(val reason: String) : FilterResult
    }

    fun filter(text: String, nowMs: Long = System.currentTimeMillis()): FilterResult {
        val trimmed = text.trim()

        // 1. Length gate
        if (trimmed.length < minChars) {
            return FilterResult.Drop("too_short:${trimmed.length}")
        }

        // 2. Numeric / chrome gate — drop if no alphabetic content
        val letterCount = trimmed.count { it.isLetter() }
        if (letterCount == 0) {
            return FilterResult.Drop("no_letters")
        }

        // 3. Hebrew content gate
        val hebrewLetterCount = trimmed.count { c -> c in 'א'..'ת' }
        val hebrewRatio = hebrewLetterCount.toFloat() / letterCount.toFloat()
        if (hebrewRatio < hebrewRatioMin) {
            return FilterResult.Drop("non_hebrew:ratio=${String.format("%.2f", hebrewRatio)}")
        }

        // 4. Rolling dedup
        val hash = sha256Hex(trimmed)
        val lastSeenMs = recentHashes[hash]
        if (lastSeenMs != null && (nowMs - lastSeenMs) < dedupWindowMs) {
            return FilterResult.Drop("dedup:hash=${hash.take(8)}")
        }
        recentHashes[hash] = nowMs

        return FilterResult.Pass(textHash = hash)
    }

    companion object {
        private const val MIN_CHARS = 4
        private const val HEBREW_RATIO_MIN = 0.30f
        private const val DEDUP_WINDOW_MS = 5 * 60 * 1000L  // 5 minutes
        private const val DEDUP_CACHE_SIZE = 512

        /**
         * Compute the SHA-256 hex digest of a string (UTF-8 encoded).
         * This is the text_hash field sent to the server.
         */
        fun sha256Hex(text: String): String {
            val digest = MessageDigest.getInstance("SHA-256")
            val bytes = digest.digest(text.toByteArray(Charsets.UTF_8))
            return bytes.joinToString("") { "%02x".format(it) }
        }
    }
}
