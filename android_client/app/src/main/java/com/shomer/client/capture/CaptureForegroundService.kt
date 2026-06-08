package com.shomer.client.capture

import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.os.IBinder
import androidx.core.app.NotificationCompat
import com.shomer.client.MainActivity
import com.shomer.client.R
import com.shomer.client.ShomerApplication
import dagger.hilt.android.AndroidEntryPoint

/**
 * Foreground service that keeps the monitoring process alive.
 *
 * Responsibilities:
 *   - Owns the mandatory non-dismissible "monitoring active" ongoing notification
 *     (required by Android policy and Shomer.AI ethics: the child must know
 *     monitoring is active — see privacy.decision.md D4).
 *   - Keeps the process priority high enough that OEM battery managers are less
 *     likely to kill it. This is reinforced by the battery-optimization exemption
 *     requested in onboarding.
 *   - Does NOT own the AccessibilityService; the system manages that lifecycle.
 *     The foreground service is a process-keepalive companion.
 *
 * Lifecycle:
 *   - Started by onboarding (after consent + accessibility grant) via ACTION_START.
 *   - Restarted by BootReceiver on device reboot.
 *   - Stopped by the status screen's "Stop Monitoring" toggle via ACTION_STOP.
 *
 * The service type is FOREGROUND_SERVICE_SPECIAL_USE (declared in the manifest with
 * the android:foregroundServiceType attribute). The PROPERTY_SPECIAL_USE_FGS_SUBTYPE
 * property in the manifest describes this as "monitoring" usage.
 */
@AndroidEntryPoint
class CaptureForegroundService : Service() {

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP -> {
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf()
                return START_NOT_STICKY
            }
            else -> {
                // ACTION_START or null (restarted by system)
                startForeground(NOTIFICATION_ID, buildNotification())
            }
        }
        return START_STICKY
    }

    private fun buildNotification() = NotificationCompat.Builder(this, ShomerApplication.CHANNEL_MONITORING)
        .setSmallIcon(android.R.drawable.ic_menu_info_details)
        .setContentTitle(getString(R.string.notification_monitoring_title))
        .setContentText(getString(R.string.notification_monitoring_text))
        .setOngoing(true)            // Non-dismissible by the user
        .setShowWhen(false)
        .setPriority(NotificationCompat.PRIORITY_LOW)
        .setContentIntent(
            PendingIntent.getActivity(
                this,
                0,
                Intent(this, MainActivity::class.java),
                PendingIntent.FLAG_IMMUTABLE,
            ),
        )
        .build()

    override fun onBind(intent: Intent?): IBinder? = null

    companion object {
        const val ACTION_START = "com.shomer.client.ACTION_START_CAPTURE"
        const val ACTION_STOP = "com.shomer.client.ACTION_STOP_CAPTURE"
        private const val NOTIFICATION_ID = 1001
    }
}
