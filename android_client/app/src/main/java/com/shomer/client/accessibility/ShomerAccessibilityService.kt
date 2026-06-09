package com.shomer.client.accessibility

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.AccessibilityServiceInfo
import android.app.Notification
import android.util.Log
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import com.shomer.client.capture.CaptureCoordinator
import dagger.hilt.android.AndroidEntryPoint
import javax.inject.Inject

/**
 * AccessibilityService — the primary text-reading mechanism.
 *
 * Listens for TYPE_WINDOW_CONTENT_CHANGED and TYPE_VIEW_TEXT_CHANGED events from
 * the target apps (declared in accessibility_service_config.xml). On each event,
 * walks the AccessibilityNodeInfo tree to extract visible text nodes, infers
 * direction via TargetAppRegistry, and hands each candidate to CaptureCoordinator
 * (which debounces + pre-filters before writing to the buffer).
 *
 * Cannot be enabled programmatically — the user must navigate to Accessibility
 * Settings and enable "Shomer.AI Monitoring Service" manually. The onboarding
 * PermissionFlowScreen deep-links there via Settings.ACTION_ACCESSIBILITY_SETTINGS.
 *
 * OEM battery managers may kill this service even with a foreground service running
 * alongside it. The CaptureForegroundService + battery-optimization exemption
 * mitigate this; the BOOT_COMPLETED receiver restarts capture after reboot.
 */
@AndroidEntryPoint
class ShomerAccessibilityService : AccessibilityService() {

    @Inject
    lateinit var captureCoordinator: CaptureCoordinator

    // Per-app latest in-progress compose text. Submitted once when the box clears
    // (= the message was sent), so a sentence isn't captured word-by-word as it grows.
    private val pendingOutbound = HashMap<String, String>()

    override fun onServiceConnected() {
        super.onServiceConnected()
        Log.i(TAG, "ShomerAccessibilityService connected")
        // Runtime config can override the XML config if needed (e.g. to update
        // the package set based on TargetAppRegistry.enabledProfiles()).
        val info = AccessibilityServiceInfo().apply {
            // WINDOW_STATE_CHANGED fires when a chat is opened/switched → triggers a
            // full scan of the now-visible messages. CONTENT_CHANGED catches new
            // messages + scrolling; VIEW_TEXT_CHANGED catches typing (outbound).
            eventTypes = AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED or
                    AccessibilityEvent.TYPE_WINDOW_CONTENT_CHANGED or
                    AccessibilityEvent.TYPE_VIEW_TEXT_CHANGED or
                    // Incoming messages: WhatsApp hides chat bubbles from the view
                    // tree, but the message text is in the posted notification.
                    AccessibilityEvent.TYPE_NOTIFICATION_STATE_CHANGED
            feedbackType = AccessibilityServiceInfo.FEEDBACK_GENERIC
            flags = AccessibilityServiceInfo.FLAG_REPORT_VIEW_IDS or
                    AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS or
                    // WhatsApp may mark message bubbles "not important for
                    // accessibility"; this flag forces them into the tree so the
                    // scan can read on-screen (open-chat) message text.
                    AccessibilityServiceInfo.FLAG_INCLUDE_NOT_IMPORTANT_VIEWS
            notificationTimeout = 300
            // Limit to enabled packages from the registry (subset of XML list).
            packageNames = TargetAppRegistry.enabledProfiles()
                .map { it.packageName }
                .toTypedArray()
        }
        serviceInfo = info
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        event ?: return
        val pkg = event.packageName?.toString() ?: return

        // Fast path: skip events from packages not in the registry.
        if (!TargetAppRegistry.isEnabled(pkg)) return

        when (event.eventType) {
            // Incoming messages arrive as notifications (WhatsApp hides chat bubbles
            // from the view tree). Read the message text from the Notification extras.
            AccessibilityEvent.TYPE_NOTIFICATION_STATE_CHANGED ->
                extractFromNotification(event, pkg)

            // Typing in the compose box. We do NOT submit on every keystroke/pause
            // (that produced word-by-word fragments of the same sentence); we submit
            // once when the box clears, i.e. when the message is actually sent.
            AccessibilityEvent.TYPE_VIEW_TEXT_CHANGED ->
                handleOutboundTyping(event, pkg)

            // Window/content changes: best-effort scan of on-screen text (WhatsApp
            // blocks this, but other apps may expose received messages this way).
            else -> {
                val rootNode = rootInActiveWindow ?: return
                try {
                    extractTextFromNode(rootNode, pkg)
                } finally {
                    @Suppress("DEPRECATION")
                    rootNode.recycle()
                }
            }
        }
    }

    /**
     * Outbound (typed) capture with send-detection. A sentence typed with pauses fires
     * many TYPE_VIEW_TEXT_CHANGED events carrying the growing text; submitting each one
     * produced fragments. Instead we keep only the latest in-progress text per app and
     * submit it once when the compose box clears (the message was sent).
     */
    private fun handleOutboundTyping(event: AccessibilityEvent, packageName: String) {
        val text = event.text
            ?.mapNotNull { it?.toString() }
            ?.joinToString(" ")
            ?.trim()
            .orEmpty()
        if (text.isBlank()) {
            // Compose box cleared -> message sent. Submit the last typed text once.
            pendingOutbound.remove(packageName)?.let { sent ->
                captureCoordinator.submit(packageName, sent, "outbound")
            }
        } else {
            // Still typing: remember the latest snapshot; don't submit yet.
            pendingOutbound[packageName] = text
        }
    }

    /**
     * Walk the node tree recursively (bounded depth) and submit each node's
     * `text` (the rendered message text) to the CaptureCoordinator. We capture
     * text from every node, not just leaves, because chat apps frequently put the
     * message text on a container node that also has child spans (emoji, time,
     * status). `contentDescription` is intentionally NOT used — on WhatsApp/Telegram
     * it returns control labels ("Send", "Voice message, Button") rather than
     * message content. The on-device Hebrew pre-filter + rolling dedup discard the
     * resulting non-Hebrew and duplicate (parent/child) captures.
     */
    private fun extractTextFromNode(
        node: AccessibilityNodeInfo,
        packageName: String,
        depth: Int = 0,
    ) {
        if (depth > MAX_TREE_DEPTH) return

        val text = node.text?.toString()?.takeIf { it.isNotBlank() }
        if (text != null) {
            val direction = TargetAppRegistry.inferDirection(
                packageName = packageName,
                viewClassName = node.className?.toString(),
                viewId = node.viewIdResourceName,
            )
            captureCoordinator.submit(
                packageName = packageName,
                text = text,
                direction = direction,
            )
        }

        for (i in 0 until node.childCount) {
            val child = node.getChild(i) ?: continue
            extractTextFromNode(child, packageName, depth + 1)
            // recycle() is deprecated in API 33+ but still required on older API levels.
            // The @Suppress hides the deprecation warning in both cases.
            @Suppress("DEPRECATION")
            child.recycle()
        }
    }

    /**
     * Extract the message text from an incoming notification. WhatsApp (and most
     * chat apps) put the latest message in EXTRA_TEXT and the sender in EXTRA_TITLE;
     * MessagingStyle / inbox notifications also carry EXTRA_TEXT_LINES. We submit the
     * message body as inbound; the Hebrew pre-filter + dedup discard system/non-Hebrew
     * notifications and repeats. Falls back to the event's own text if no Notification.
     */
    private fun extractFromNotification(event: AccessibilityEvent, packageName: String) {
        val parcel = event.parcelableData
        if (parcel is Notification) {
            val extras = parcel.extras
            val candidates = buildList {
                extras.getCharSequence(Notification.EXTRA_TEXT)?.let { add(it.toString()) }
                extras.getCharSequenceArray(Notification.EXTRA_TEXT_LINES)
                    ?.forEach { it?.toString()?.let(::add) }
                extras.getCharSequence(Notification.EXTRA_BIG_TEXT)?.let { add(it.toString()) }
            }
            candidates.map { it.trim() }
                .filter { it.isNotBlank() }
                .distinct()
                .forEach { captureCoordinator.submit(packageName, it, "inbound") }
        } else {
            val text = event.text?.mapNotNull { it?.toString() }?.joinToString(" ")?.trim()
            if (!text.isNullOrBlank()) captureCoordinator.submit(packageName, text, "inbound")
        }
    }

    override fun onInterrupt() {
        Log.w(TAG, "ShomerAccessibilityService interrupted")
    }

    override fun onDestroy() {
        Log.i(TAG, "ShomerAccessibilityService destroyed")
        super.onDestroy()
    }

    companion object {
        private const val TAG = "ShomerA11y"
        // Deep enough to reach nested message text, but capped to avoid heavy
        // main-thread walks on every content-change event (60 caused jank).
        private const val MAX_TREE_DEPTH = 25
    }
}
