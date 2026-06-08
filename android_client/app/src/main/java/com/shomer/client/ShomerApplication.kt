package com.shomer.client

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager
import android.os.Build
import androidx.hilt.work.HiltWorkerFactory
import androidx.work.Configuration
import dagger.hilt.android.HiltAndroidApp
import javax.inject.Inject

/**
 * Application class — entry point for Hilt and notification channel setup.
 *
 * Notification channels are idempotent (safe to call every launch on API 26+).
 * Channels must be registered before any notification is posted; doing it in
 * onCreate() is the correct pattern.
 */
@HiltAndroidApp
class ShomerApplication : Application(), Configuration.Provider {

    @Inject
    lateinit var workerFactory: HiltWorkerFactory

    override val workManagerConfiguration: Configuration
        get() = Configuration.Builder()
            .setWorkerFactory(workerFactory)
            .build()

    override fun onCreate() {
        super.onCreate()
        registerNotificationChannels()
    }

    private fun registerNotificationChannels() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val nm = getSystemService(NotificationManager::class.java) ?: return

        // Monitoring-active indicator — low importance (no sound/vibration).
        // This is the mandatory non-dismissible foreground-service notification.
        nm.createNotificationChannel(
            NotificationChannel(
                CHANNEL_MONITORING,
                getString(R.string.notification_channel_monitoring_name),
                NotificationManager.IMPORTANCE_LOW,
            ).apply {
                description = getString(R.string.notification_channel_monitoring_desc)
                setShowBadge(false)
            },
        )

        // Parent-alert channels (for pass 2 — registered now so the channel IDs
        // are available even before FCM receiver is wired).
        // shomer.alerts.escalated — high severity
        nm.createNotificationChannel(
            NotificationChannel(
                CHANNEL_ALERTS_ESCALATED,
                "Alerts — Escalated",
                NotificationManager.IMPORTANCE_HIGH,
            ),
        )
        // shomer.alerts.direct — medium severity
        nm.createNotificationChannel(
            NotificationChannel(
                CHANNEL_ALERTS_DIRECT,
                "Alerts — Direct",
                NotificationManager.IMPORTANCE_DEFAULT,
            ),
        )
        // shomer.alerts.silent — audit-only, no notification
        nm.createNotificationChannel(
            NotificationChannel(
                CHANNEL_ALERTS_SILENT,
                "Alerts — Silent",
                NotificationManager.IMPORTANCE_NONE,
            ),
        )
    }

    companion object {
        const val CHANNEL_MONITORING = "shomer.monitoring.active"
        const val CHANNEL_ALERTS_ESCALATED = "shomer.alerts.escalated"
        const val CHANNEL_ALERTS_DIRECT = "shomer.alerts.direct"
        const val CHANNEL_ALERTS_SILENT = "shomer.alerts.silent"
    }
}
