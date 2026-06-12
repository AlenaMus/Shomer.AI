package com.shomer.client.monitor

import android.content.Context
import android.util.Log
import androidx.hilt.work.HiltWorker
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import androidx.work.workDataOf
import com.shomer.client.capture.EventDao
import com.shomer.client.data.MonitorApi
import com.shomer.client.data.MonitorBatchRequest
import com.shomer.client.data.MonitorEvent
import com.shomer.client.data.SettingsRepository
import com.shomer.client.data.TokenStore
import dagger.assisted.Assisted
import dagger.assisted.AssistedInject
import kotlinx.coroutines.flow.first
import java.util.UUID
import java.util.concurrent.TimeUnit

/**
 * WorkManager CoroutineWorker that batches buffered events and uploads them to
 * POST /v1/monitor/events.
 *
 * Upload cycle:
 *   1. Read up to 50 oldest pending events from EventDao.
 *   2. Build MonitorBatchRequest (session_id per app session UUID, child_id from
 *      TokenStore).
 *   3. POST to the server with Authorization: Bearer <device_token> (added by
 *      AuthInterceptor at the OkHttp layer).
 *   4. On 2xx: delete the uploaded rows; decrement pending count.
 *   5. On network failure / 5xx: return Result.retry() — WorkManager applies
 *      exponential backoff (BACKOFF_DELAY_SECONDS * attempt, capped at 5 minutes).
 *   6. On 401/403 (not paired / wrong child_id): return Result.failure() — stop
 *      retrying; the user must re-pair.
 *
 * Scheduling:
 *   - Periodic: every 15 minutes (WorkManager minimum), requires network.
 *   - Expedited: triggered immediately when CaptureCoordinator inserts the Nth
 *     event (see scheduleExpedited). Uses enqueueUniqueWork to avoid duplicates.
 *
 * The session_id is a UUID generated once per worker invocation (not per app
 * launch) — it groups the events in one upload batch for server correlation.
 * The server does not use session_id as an auth boundary; child_id + device_token
 * are the auth identifiers.
 */
@HiltWorker
class MonitorUploader @AssistedInject constructor(
    @Assisted context: Context,
    @Assisted workerParams: WorkerParameters,
    private val eventDao: EventDao,
    private val monitorApi: MonitorApi,
    private val tokenStore: TokenStore,
    private val settings: SettingsRepository,
    private val activityLog: MonitorActivityLog,
) : CoroutineWorker(context, workerParams) {

    override suspend fun doWork(): Result {
        // If this run is part of the recurring loop, schedule the next run before
        // doing anything else — so the loop keeps ticking even if this run no-ops.
        if (inputData.getBoolean(KEY_IS_LOOP, false)) {
            val intervalMin = settings.uploadIntervalMinutes.first()
            startUploadLoop(applicationContext, delayMinutes = intervalMin)
        }

        // Guard: skip if device is not paired.
        val childId = tokenStore.getChildId()
        if (!tokenStore.isPaired() || childId == null) {
            Log.d(TAG, "Not paired — skipping upload")
            return Result.success()   // success, not failure — nothing to retry
        }

        val batch = eventDao.getOldestBatch(limit = MAX_BATCH_SIZE)
        if (batch.isEmpty()) {
            Log.d(TAG, "No pending events — nothing to upload")
            return Result.success()
        }

        val sessionId = UUID.randomUUID().toString()
        val events = batch.map { entity ->
            MonitorEvent(
                clientMsgId = entity.clientMsgId,
                appPackage = entity.appPackage,
                text = entity.text,
                textHash = entity.textHash,
                capturedAt = entity.capturedAt,
                direction = entity.direction,
                conversationId = entity.conversationId,
            )
        }

        return try {
            val response = monitorApi.ingest(
                MonitorBatchRequest(
                    sessionId = sessionId,
                    childId = childId,
                    events = events,
                ),
            )

            // Delete the successfully uploaded rows + mark them SENT in the activity log.
            val uploadedIds = batch.map { it.clientMsgId }
            eventDao.deleteByIds(uploadedIds)
            activityLog.markSent(uploadedIds)

            Log.i(
                TAG,
                "Uploaded ${batch.size} events: accepted=${response.accepted} " +
                    "deduped=${response.deduped} flagged=${response.flagged}",
            )
            Result.success()
        } catch (e: retrofit2.HttpException) {
            val code = e.code()
            Log.w(TAG, "HTTP $code — ${e.message()}")
            when {
                code == 401 || code == 403 -> {
                    // Auth failure: not paired or wrong child_id. Stop retrying.
                    Log.e(TAG, "Auth failure ($code) — device may need to re-pair")
                    activityLog.markFailed(batch.map { it.clientMsgId })
                    Result.failure()
                }
                code in 500..599 -> Result.retry()
                else -> Result.failure()   // 4xx other than 401/403 — client bug, don't retry
            }
        } catch (e: Exception) {
            Log.w(TAG, "Network error: ${e.message}")
            Result.retry()
        }
    }

    companion object {
        private const val TAG = "MonitorUploader"
        private const val MAX_BATCH_SIZE = 50
        private const val BACKOFF_DELAY_SECONDS = 30L
        private const val WORK_NAME_LOOP = "shomer.monitor.loop"
        private const val WORK_NAME_EXPEDITED = "shomer.monitor.expedited"
        private const val KEY_IS_LOOP = "is_loop"

        private fun networkConstraints() = Constraints.Builder()
            .setRequiredNetworkType(NetworkType.CONNECTED)
            .build()

        /**
         * Start (or restart) the recurring upload loop. Each run reschedules the
         * next one after the user-configured interval (see SettingsRepository), so
         * the cadence can be as low as 1 minute — unlike a PeriodicWorkRequest,
         * which WorkManager floors at 15 minutes.
         *
         * Called after pairing (onboarding), from BootReceiver, and whenever the
         * user changes the interval in Settings. The first run fires after
         * [delayMinutes] (0 = immediately).
         */
        fun startUploadLoop(context: Context, delayMinutes: Long = 0L) {
            val builder = OneTimeWorkRequestBuilder<MonitorUploader>()
                .setConstraints(networkConstraints())
                .setInputData(workDataOf(KEY_IS_LOOP to true))
                .setBackoffCriteria(
                    BackoffPolicy.EXPONENTIAL,
                    BACKOFF_DELAY_SECONDS,
                    TimeUnit.SECONDS,
                )
            if (delayMinutes > 0L) {
                builder.setInitialDelay(delayMinutes, TimeUnit.MINUTES)
            }
            WorkManager.getInstance(context).enqueueUniqueWork(
                WORK_NAME_LOOP,
                ExistingWorkPolicy.REPLACE,
                builder.build(),
            )
            Log.d(TAG, "Upload loop scheduled (next run in ${delayMinutes}m)")
        }

        /**
         * Fire a one-off upload as soon as possible — called by CaptureCoordinator
         * right after an event is buffered, so a captured message reaches the server
         * within seconds instead of waiting for the next loop tick. KEEP policy means
         * a burst of captures coalesces into a single pending upload.
         */
        fun scheduleExpedited(context: Context) {
            // NOTE: do NOT use setExpedited() here — that requires overriding
            // getForegroundInfo() (foreground notification), and without it WorkManager
            // throws IllegalStateException("Not implemented") on a worker thread, which
            // crashes the whole process. A plain one-time request runs ASAP anyway.
            val request = OneTimeWorkRequestBuilder<MonitorUploader>()
                .setConstraints(networkConstraints())
                .build()
            WorkManager.getInstance(context).enqueueUniqueWork(
                WORK_NAME_EXPEDITED,
                ExistingWorkPolicy.KEEP,
                request,
            )
            Log.d(TAG, "Upload enqueued (run-soon)")
        }
    }
}
