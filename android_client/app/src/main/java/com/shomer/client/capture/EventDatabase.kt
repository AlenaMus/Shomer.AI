package com.shomer.client.capture

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase

/**
 * Room database for the pending event buffer (EncryptedEventBuffer).
 *
 * Database file: files/shomer_events.db (app-private storage, not external).
 * Android's file-based encryption (FBE) protects it at rest when the device is
 * locked (API 24+ with FBE-capable devices). Full SQLCipher per-file encryption
 * is deferred to A6 privacy hardening per the design.md note.
 *
 * Constructed only in NetworkModule (Hilt singleton) so there is exactly one
 * database instance per app process — the Room documentation requirement.
 */
@Database(entities = [EventEntity::class], version = 2, exportSchema = false)
abstract class EventDatabase : RoomDatabase() {
    abstract fun eventDao(): EventDao

    companion object {
        @Volatile
        private var INSTANCE: EventDatabase? = null

        fun getInstance(context: Context): EventDatabase =
            INSTANCE ?: synchronized(this) {
                INSTANCE ?: Room.databaseBuilder(
                    context.applicationContext,
                    EventDatabase::class.java,
                    "shomer_events.db",
                )
                    .fallbackToDestructiveMigration()
                    .build()
                    .also { INSTANCE = it }
            }
    }
}
