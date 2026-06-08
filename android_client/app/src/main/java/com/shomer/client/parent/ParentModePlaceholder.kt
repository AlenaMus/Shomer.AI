package com.shomer.client.parent

/**
 * Parent-mode placeholder — pass 2 will add:
 *
 *   - ShomerFcmService : FirebaseMessagingService
 *       onNewToken     → PATCH /v1/device/fcm-token
 *       onMessageReceived → parse daily digest push → deep-link to AlertListScreen
 *
 *   - AlertListScreen  → GET /v1/parent/alerts
 *   - AlertDetailScreen → GET /v1/parent/alerts/{id} + POST /v1/parent/alerts/{id}/react
 *   - DigestScreen     → GET /v1/parent/digests/{date}
 *
 * The firebase-messaging-ktx dependency and google-services.json are NOT included
 * in pass 1. Add to app/build.gradle.kts when parent-mode work begins:
 *   implementation("com.google.firebase:firebase-messaging-ktx:24.0.0")
 *   Apply plugin: "com.google.gms.google-services"
 *
 * The notification channels for parent alerts (shomer.alerts.escalated,
 * shomer.alerts.direct, shomer.alerts.silent) are already registered in
 * ShomerApplication.onCreate() so they are ready for pass 2.
 *
 * The PATCH /v1/device/fcm-token stub call after pairing lives in
 * OnboardingViewModel. When the FCM SDK is wired, replace the stub with the
 * real FirebaseMessaging.getInstance().token retrieval.
 */
@Suppress("unused")
object ParentModePlaceholder
