package com.shomer.client.parent

/**
 * Firebase Cloud Messaging receiver for parent-mode push alerts.
 *
 * STATUS: Written but NOT active — FCM is opt-in (see "Enabling FCM" below).
 * The file compiles against the firebase-messaging-ktx artifact BUT the class
 * is NOT registered in AndroidManifest.xml and the google-services plugin is
 * NOT applied until you follow the steps below.
 *
 * This means `./gradlew assembleClientDebug` and `./gradlew assemblePocDebug`
 * compile GREEN with no Firebase project configured — the polling UI in
 * AlertListScreen and DigestScreen is fully functional without FCM.
 *
 * ─── Enabling real FCM ──────────────────────────────────────────────────────
 *
 * 1. Create a Firebase project at https://console.firebase.google.com/
 *    - Add Android app with package name "com.shomer.client"
 *    - Download google-services.json → place it at android_client/app/google-services.json
 *    - (Add a second app for the poc flavor if you need FCM there too:
 *       package name "com.dima.offensivehebrew")
 *
 * 2. In android_client/app/build.gradle.kts, uncomment:
 *      plugins { ... id("com.google.gms.google-services") }   // google-services plugin
 *    and uncomment the firebase dependency:
 *      implementation("com.google.firebase:firebase-messaging-ktx:24.0.0")
 *
 * 3. In android_client/build.gradle.kts (root), uncomment:
 *      id("com.google.gms.google-services") version "4.4.2" apply false
 *
 * 4. In AndroidManifest.xml, uncomment the ShomerFcmService <service> block
 *    (marked with TODO:FCM below in the manifest comment).
 *
 * 5. Rebuild. The class below will be live.
 *
 * 6. On the server side, the backend-developer must populate
 *    FIREBASE_SERVICE_ACCOUNT_PATH in server/.env so the digest notifier
 *    (server/app/notify/firebase_notifier.py) can send pushes.
 *
 * ────────────────────────────────────────────────────────────────────────────
 *
 * FCM payload schema (what the server's firebase_notifier.py sends):
 *   Data message (not notification message) so it works in the background:
 *   {
 *     "type":      "daily_digest" | "alert_escalated",
 *     "date":      "YYYY-MM-DD"   (digest messages),
 *     "flag_id":   "<uuid>"       (alert messages),
 *     "child_id":  "<uuid>",
 *     "title":     "...",
 *     "body":      "...",
 *   }
 */

/*
 * Uncomment this entire block when FCM is enabled (step 4 above).
 * The class extends FirebaseMessagingService from firebase-messaging-ktx.
 *
 * import android.app.NotificationManager
 * import android.app.PendingIntent
 * import android.content.Intent
 * import android.util.Log
 * import androidx.core.app.NotificationCompat
 * import com.google.firebase.messaging.FirebaseMessagingService
 * import com.google.firebase.messaging.RemoteMessage
 * import com.shomer.client.MainActivity
 * import com.shomer.client.ShomerApplication
 * import dagger.hilt.android.AndroidEntryPoint
 * import kotlinx.coroutines.CoroutineScope
 * import kotlinx.coroutines.Dispatchers
 * import kotlinx.coroutines.SupervisorJob
 * import kotlinx.coroutines.launch
 * import javax.inject.Inject
 *
 * @AndroidEntryPoint
 * class ShomerFcmService : FirebaseMessagingService() {
 *
 *     @Inject
 *     lateinit var parentApi: com.shomer.client.data.ParentApi
 *
 *     private val serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
 *
 *     // Called when the FCM token is refreshed (first launch, or token rotation).
 *     override fun onNewToken(token: String) {
 *         super.onNewToken(token)
 *         Log.i(TAG, "FCM token refreshed (length=${token.length})")
 *         serviceScope.launch {
 *             try {
 *                 parentApi.setFcmToken(com.shomer.client.data.FcmTokenRequest(fcmToken = token))
 *                 Log.i(TAG, "FCM token registered with server")
 *             } catch (e: Exception) {
 *                 Log.e(TAG, "FCM token registration failed: ${e.message}")
 *                 // Non-fatal: polling still works; token will be retried on next launch.
 *             }
 *         }
 *     }
 *
 *     // Called when a data message arrives (foreground or background).
 *     override fun onMessageReceived(remoteMessage: RemoteMessage) {
 *         super.onMessageReceived(remoteMessage)
 *         val data = remoteMessage.data
 *         val type = data["type"] ?: return
 *         val title = data["title"] ?: "Shomer.AI"
 *         val body = data["body"] ?: "New activity on your child's device"
 *
 *         val channelId = when (type) {
 *             "alert_escalated" -> ShomerApplication.CHANNEL_ALERTS_ESCALATED
 *             "daily_digest"    -> ShomerApplication.CHANNEL_ALERTS_DIRECT
 *             else              -> ShomerApplication.CHANNEL_ALERTS_SILENT
 *         }
 *
 *         // Deep-link intent: tap opens MainActivity which routes to AlertListScreen
 *         val intent = Intent(this, MainActivity::class.java).apply {
 *             addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP)
 *             putExtra("deep_link_type", type)
 *             data["flag_id"]?.let { putExtra("flag_id", it) }
 *             data["date"]?.let { putExtra("date", it) }
 *         }
 *         val pendingIntent = PendingIntent.getActivity(
 *             this, System.currentTimeMillis().toInt(), intent,
 *             PendingIntent.FLAG_ONE_SHOT or PendingIntent.FLAG_IMMUTABLE,
 *         )
 *
 *         val notification = NotificationCompat.Builder(this, channelId)
 *             .setSmallIcon(android.R.drawable.ic_dialog_info)
 *             .setContentTitle(title)
 *             .setContentText(body)
 *             .setAutoCancel(true)
 *             .setContentIntent(pendingIntent)
 *             .build()
 *
 *         val nm = getSystemService(NotificationManager::class.java)
 *         nm.notify(System.currentTimeMillis().toInt(), notification)
 *         Log.i(TAG, "FCM message displayed: type=$type channelId=$channelId")
 *     }
 *
 *     companion object {
 *         private const val TAG = "ShomerFcmService"
 *     }
 * }
 */

// Placeholder object so the file is not completely empty during the opt-in phase.
@Suppress("unused")
internal object ShomerFcmServicePlaceholder
