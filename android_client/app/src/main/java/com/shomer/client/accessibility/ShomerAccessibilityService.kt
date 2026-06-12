package com.shomer.client.accessibility

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.AccessibilityServiceInfo
import android.app.Notification
import android.util.Log
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import com.shomer.client.capture.CaptureCoordinator
import com.shomer.client.capture.PreFilter
import com.shomer.client.capture.ScreenshotCoordinator
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

    @Inject
    lateinit var screenshotCoordinator: ScreenshotCoordinator

    // Per-app latest in-progress compose text. Submitted once when the box clears
    // (= the message was sent), so a sentence isn't captured word-by-word as it grows.
    private val pendingOutbound = HashMap<String, String>()

    // Per-app latest resolved conversation_id (cached so every node-scan in the same
    // window doesn't re-derive it from scratch). Cleared on TYPE_WINDOW_STATE_CHANGED.
    private val currentConversationId = HashMap<String, String?>()

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
            // Notifications carry the conversation title in EXTRA_CONVERSATION_TITLE
            // (MessagingStyle) or EXTRA_TITLE (plain); use it to derive conversation_id.
            AccessibilityEvent.TYPE_NOTIFICATION_STATE_CHANGED ->
                extractFromNotification(event, pkg)

            // Window changed: a new chat thread is now in the foreground. Invalidate
            // the cached conversation_id so it is re-derived from the new window title.
            AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED -> {
                currentConversationId.remove(pkg)
                val convId = deriveConversationId(pkg, event)
                currentConversationId[pkg] = convId
                Log.d(TAG, "Window changed pkg=$pkg convId=${convId?.take(8)}")

                screenshotCoordinator.signalScreenChanged(pkg)

                val rootNode = rootInActiveWindow ?: return
                try {
                    extractTextFromNode(rootNode, pkg)
                } finally {
                    @Suppress("DEPRECATION")
                    rootNode.recycle()
                }
            }

            // Typing in the compose box. We do NOT submit on every keystroke/pause
            // (that produced word-by-word fragments of the same sentence); we submit
            // once when the box clears, i.e. when the message is actually sent.
            AccessibilityEvent.TYPE_VIEW_TEXT_CHANGED ->
                handleOutboundTyping(event, pkg)

            // Content changes: best-effort scan of on-screen text (WhatsApp blocks
            // this, but other apps may expose received messages this way).
            // Also signal ScreenshotCoordinator so it can capture the screen for
            // apps (like WhatsApp) that hide message bubbles from the a11y tree.
            else -> {
                // Signal screen capture FIRST (non-blocking, debounced internally).
                // This is the primary path for open-chat WhatsApp messages that
                // are invisible to the accessibility tree.
                screenshotCoordinator.signalScreenChanged(pkg)

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
                captureCoordinator.submit(
                    packageName = packageName,
                    text = sent,
                    direction = "outbound",
                    conversationId = currentConversationId[packageName],
                )
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
                conversationId = currentConversationId[packageName],
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

            // Derive a conversation_id from the notification's conversation/contact title.
            // MessagingStyle puts the group/contact name in EXTRA_CONVERSATION_TITLE;
            // plain notifications use EXTRA_TITLE (e.g. "Daria" or "Family group").
            // Both are the thread identity, which is exactly what conversation_id needs.
            val threadTitle = (extras.getCharSequence(Notification.EXTRA_CONVERSATION_TITLE)
                ?: extras.getCharSequence(Notification.EXTRA_TITLE))?.toString()?.trim()
            val convId = stableConversationId(packageName, threadTitle)

            val candidates = buildList {
                extras.getCharSequence(Notification.EXTRA_TEXT)?.let { add(it.toString()) }
                extras.getCharSequenceArray(Notification.EXTRA_TEXT_LINES)
                    ?.forEach { it?.toString()?.let(::add) }
                extras.getCharSequence(Notification.EXTRA_BIG_TEXT)?.let { add(it.toString()) }
            }
            candidates.map { it.trim() }
                .filter { it.isNotBlank() }
                .distinct()
                .forEach {
                    captureCoordinator.submit(
                        packageName = packageName,
                        text = it,
                        direction = "inbound",
                        conversationId = convId,
                    )
                }
        } else {
            val text = event.text?.mapNotNull { it?.toString() }?.joinToString(" ")?.trim()
            if (!text.isNullOrBlank()) {
                captureCoordinator.submit(
                    packageName = packageName,
                    text = text,
                    direction = "inbound",
                    conversationId = currentConversationId[packageName],
                )
            }
        }
    }

    /**
     * Derive a stable conversation_id for a text-event window.
     *
     * Strategy (in priority order — first non-blank result wins):
     *   1. The accessibility event's own className, if it looks like a screen/activity
     *      title (e.g. WhatsApp fires TYPE_WINDOW_STATE_CHANGED with the chat title as
     *      event.className on newer builds — actually the Activity class, but the
     *      event.text list sometimes carries the visible title).
     *   2. event.text — the event text list sometimes carries the conversation title
     *      on window-state events fired when a chat is opened.
     *   3. The rootInActiveWindow's own contentDescription or text (toolbar title node).
     *   4. Fall back to null — the server will scope by app_package alone.
     *
     * The returned id is stableConversationId(package, threadKey) so it is
     * consistent across events in the same thread and across sessions.
     */
    private fun deriveConversationId(packageName: String, event: AccessibilityEvent): String? {
        // Attempt 1: event text list (may carry the chat/contact name on window change).
        val eventTextTitle = event.text
            ?.mapNotNull { it?.toString()?.trim() }
            ?.firstOrNull { it.isNotBlank() && it.length < 128 }

        // Attempt 2: walk the accessibility tree to find a toolbar/title node.
        // Bounded to a shallow depth — this runs on every window change event and
        // must not block the main thread. MAX_TITLE_DEPTH is intentionally small.
        val treeTitle: String? = try {
            val root = rootInActiveWindow
            if (root != null) {
                val found = findTitleNode(root, depth = 0)
                @Suppress("DEPRECATION")
                root.recycle()
                found
            } else null
        } catch (_: Exception) {
            null
        }

        val threadKey = eventTextTitle ?: treeTitle
        return stableConversationId(packageName, threadKey)
    }

    /**
     * DFS search for a toolbar/title node — used to read the active chat name.
     *
     * WhatsApp's conversation screen has a toolbar (com.whatsapp:id/conversation_contact_name
     * or similar) near the top of the tree. We look for nodes whose viewIdResourceName
     * or className suggests a title/toolbar role and whose text is short (plausibly a
     * contact/group name rather than a message). Returns null when nothing is found.
     *
     * This is necessarily heuristic: WhatsApp changes its internal view IDs across
     * versions. The caller gracefully handles null (falls back to package-only scope).
     */
    private fun findTitleNode(node: AccessibilityNodeInfo, depth: Int): String? {
        if (depth > MAX_TITLE_DEPTH) return null

        val id = node.viewIdResourceName?.lowercase() ?: ""
        val cls = node.className?.toString()?.lowercase() ?: ""
        val text = node.text?.toString()?.trim()

        // A title/toolbar node is likely to have "title", "name", "toolbar", or
        // "contact" in its resource id, be short (< 100 chars), and non-blank.
        val looksLikeTitle = (
            "title" in id || "contact_name" in id || "toolbar" in id ||
            "actionbar" in cls || "toolbar" in cls
        ) && !text.isNullOrBlank() && text.length < 100

        if (looksLikeTitle) return text

        for (i in 0 until node.childCount) {
            val child = node.getChild(i) ?: continue
            val found = findTitleNode(child, depth + 1)
            @Suppress("DEPRECATION")
            child.recycle()
            if (found != null) return found
        }
        return null
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

        // Shallow depth for the title-search walk. Toolbars are near the root;
        // going deeper wastes main-thread time on window-change events.
        private const val MAX_TITLE_DEPTH = 6

        /**
         * Produce a stable conversation_id string from a package name and a thread key.
         *
         * Formula: sha256("$packageName:$threadKey").hex[:32]
         *   - 32 hex chars = 128 bits of the hash — well within the server's max_length=128.
         *   - Stable: same package + same threadKey always → same id, across sessions.
         *   - Private: the raw contact/group name is NOT stored; only the hash travels
         *     to the server. The server only uses it for scoping; it never sees the name.
         *
         * When threadKey is null (title could not be read), returns null so the server
         * falls back to its own default scoping (by app_package alone).
         */
        fun stableConversationId(packageName: String, threadKey: String?): String? {
            if (threadKey.isNullOrBlank()) return null
            val raw = "$packageName:$threadKey"
            return PreFilter.sha256Hex(raw).take(32)
        }
    }
}
