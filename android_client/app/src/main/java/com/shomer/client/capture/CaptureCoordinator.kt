package com.shomer.client.capture

import android.util.Log
import com.shomer.client.accessibility.TargetAppRegistry
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.util.UUID
import java.util.concurrent.atomic.AtomicLong
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Coordinates the capture pipeline: receives raw text candidates from
 * ShomerAccessibilityService, applies debouncing + PreFilter, and writes
 * passing events to the EncryptedEventBuffer (EventDao).
 *
 * Architecture:
 *   AccessibilityService  →  CaptureCoordinator  →  PreFilter  →  EventDao
 *
 * Debounce: text from a given (packageName) source is held for DEBOUNCE_MS
 * after the last update; only then is it run through PreFilter and inserted.
 * This collapses rapid redraws of the same screen into a single candidate.
 *
 * The coordinator runs on Dispatchers.Default for debounce timing and
 * Dispatchers.IO for the Room insert. It must be started (start()) before
 * events are submitted and stopped (stop()) on service destruction.
 */
@Singleton
class CaptureCoordinator @Inject constructor(
    private val preFilter: PreFilter,
    private val eventDao: EventDao,
) {
    private val scope = CoroutineScope(Dispatchers.Default + Job())

    // Per-package debounce: maps packageName → pending debounce job
    private val debounceJobs = mutableMapOf<String, Job>()

    // Monotonic counters for the status screen
    val capturedCount = AtomicLong(0L)
    val insertedCount = AtomicLong(0L)

    /**
     * Submit a raw text candidate from the accessibility service.
     * Debounces per packageName, then runs through the PreFilter pipeline.
     */
    fun submit(
        packageName: String,
        text: String,
        direction: String,
    ) {
        // Cancel any existing debounce job for this package — new content resets the timer.
        debounceJobs[packageName]?.cancel()
        debounceJobs[packageName] = scope.launch {
            delay(DEBOUNCE_MS)
            capturedCount.incrementAndGet()
            processCandidate(packageName, text, direction)
        }
    }

    private suspend fun processCandidate(
        packageName: String,
        text: String,
        direction: String,
    ) {
        val result = preFilter.filter(text)
        when (result) {
            is PreFilter.FilterResult.Drop -> {
                Log.d(TAG, "PreFilter DROP pkg=$packageName reason=${result.reason}")
            }
            is PreFilter.FilterResult.Pass -> {
                val entity = EventEntity(
                    clientMsgId = UUID.randomUUID().toString(),
                    appPackage = packageName,
                    text = text.trim(),
                    textHash = result.textHash,
                    capturedAt = System.currentTimeMillis() / 1000.0,
                    direction = direction,
                )
                try {
                    eventDao.insert(entity)
                    insertedCount.incrementAndGet()
                    Log.d(TAG, "Buffered event pkg=$packageName dir=$direction hash=${result.textHash.take(8)}")
                } catch (e: Exception) {
                    Log.e(TAG, "Failed to insert event into buffer", e)
                }
            }
        }
    }

    companion object {
        private const val TAG = "CaptureCoordinator"
        private const val DEBOUNCE_MS = 400L
    }
}
