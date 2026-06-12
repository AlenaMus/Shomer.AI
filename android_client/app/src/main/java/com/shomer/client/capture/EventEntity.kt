package com.shomer.client.capture

import androidx.room.ColumnInfo
import androidx.room.Entity
import androidx.room.PrimaryKey

/**
 * Room entity representing one pending MonitorEvent in the EncryptedEventBuffer.
 *
 * Rows are inserted by CaptureCoordinator (after PreFilter passes), uploaded in
 * batches by MonitorUploader, and deleted on successful server acknowledgement.
 *
 * Field names intentionally match the wire schema (see data/Models.kt MonitorEvent)
 * so that mapping from entity → wire model is a direct copy, not a transformation.
 *
 * The database file itself is NOT encrypted in this pass (SQLCipher adds a
 * native .so dependency; using Room without SQLCipher is acceptable for the MVP
 * because the individual fields contain no counterparty PII — only the message text,
 * source package name, direction, and hash). Full SQLCipher encryption is a
 * plan-docs/decisions TODO for A6 privacy hardening.
 *
 * DB version 2: added conversation_id column (nullable). The EventDatabase uses
 * fallbackToDestructiveMigration() so the buffer is wiped on version bump. This
 * is acceptable because the buffer only holds pending-upload events; any unflushed
 * events at upgrade time are lost (the server will not have seen them anyway).
 * See design.md "Room migration — conversation_id" for the decision rationale.
 */
@Entity(tableName = "pending_events")
data class EventEntity(
    @PrimaryKey
    @ColumnInfo(name = "client_msg_id")
    val clientMsgId: String,           // UUID — device idempotency key

    @ColumnInfo(name = "app_package")
    val appPackage: String,            // e.g. "com.whatsapp"

    val text: String,                  // captured Hebrew text

    @ColumnInfo(name = "text_hash")
    val textHash: String,              // sha256(text) hex

    @ColumnInfo(name = "captured_at")
    val capturedAt: Double,            // epoch seconds

    val direction: String,             // "inbound" | "outbound"

    @ColumnInfo(name = "conversation_id")
    val conversationId: String? = null, // sha256(package:windowTitle)[:32] or null
)
