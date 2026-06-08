package com.shomer.client.capture

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query

/**
 * Room DAO for the pending_events table (EncryptedEventBuffer).
 *
 * Designed for the MonitorUploader batch cycle:
 *   1. CaptureCoordinator inserts rows via insert().
 *   2. MonitorUploader reads up to 50 rows via getOldestBatch().
 *   3. On successful POST /v1/monitor/events, deletes those rows via deleteByIds().
 *   4. On failure, leaves them in place; WorkManager retries after backoff.
 */
@Dao
interface EventDao {

    @Insert(onConflict = OnConflictStrategy.IGNORE)
    suspend fun insert(event: EventEntity)

    /**
     * Returns the oldest [limit] pending events (FIFO upload order).
     * Max 50 per the server contract (MonitorBatchRequest.events max_length=50).
     */
    @Query("SELECT * FROM pending_events ORDER BY captured_at ASC LIMIT :limit")
    suspend fun getOldestBatch(limit: Int = 50): List<EventEntity>

    /**
     * Deletes successfully uploaded rows by their client_msg_id.
     * Called after a 2xx response from POST /v1/monitor/events.
     */
    @Query("DELETE FROM pending_events WHERE client_msg_id IN (:ids)")
    suspend fun deleteByIds(ids: List<String>)

    /** Total pending rows — shown on the status screen. */
    @Query("SELECT COUNT(*) FROM pending_events")
    suspend fun pendingCount(): Int
}
