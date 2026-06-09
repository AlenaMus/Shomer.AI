package com.shomer.client.notification

import android.app.Notification
import android.os.Bundle
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import android.util.Log
import com.shomer.client.accessibility.TargetAppRegistry
import com.shomer.client.capture.CaptureCoordinator
import dagger.hilt.android.AndroidEntryPoint
import javax.inject.Inject

/**
 * Captures INCOMING messages by reading the notifications that monitored apps post.
 *
 * WhatsApp/Telegram hide chat-bubble text from the accessibility tree, and the
 * accessibility API doesn't deliver notification content either — but a
 * NotificationListenerService receives the full Notification, including the message
 * text in its extras. This is the reliable path for inbound messages.
 *
 * Requires the BIND_NOTIFICATION_LISTENER_SERVICE permission (manifest) AND the user
 * granting "Notification access" in system settings (separate from accessibility).
 *
 * Each extracted message is submitted to the CaptureCoordinator as `inbound`; the
 * Hebrew pre-filter + rolling dedup discard non-Hebrew/system notifications and the
 * repeats that WhatsApp emits as it updates the same notification.
 */
@AndroidEntryPoint
class ShomerNotificationListener : NotificationListenerService() {

    @Inject
    lateinit var captureCoordinator: CaptureCoordinator

    override fun onNotificationPosted(sbn: StatusBarNotification?) {
        val pkg = sbn?.packageName ?: return
        if (!TargetAppRegistry.isEnabled(pkg)) return

        val extras = sbn.notification?.extras ?: return
        val texts = buildList {
            extras.getCharSequence(Notification.EXTRA_TEXT)?.let { add(it.toString()) }
            extras.getCharSequence(Notification.EXTRA_BIG_TEXT)?.let { add(it.toString()) }
            extras.getCharSequenceArray(Notification.EXTRA_TEXT_LINES)
                ?.forEach { line -> line?.let { add(it.toString()) } }
            // MessagingStyle (WhatsApp): each message is a Bundle with a "text" key.
            @Suppress("DEPRECATION")
            extras.getParcelableArray(Notification.EXTRA_MESSAGES)?.forEach { p ->
                (p as? Bundle)?.getCharSequence("text")?.let { add(it.toString()) }
            }
        }

        val unique = texts.map { it.trim() }.filter { it.isNotBlank() }.distinct()
        if (unique.isNotEmpty()) {
            Log.d(TAG, "Notification from $pkg: ${unique.size} text(s)")
            unique.forEach { captureCoordinator.submit(pkg, it, "inbound") }
        }
    }

    companion object {
        private const val TAG = "ShomerNotifListener"
    }
}
