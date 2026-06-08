package com.shomer.client.accessibility

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.AccessibilityServiceInfo
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

    override fun onServiceConnected() {
        super.onServiceConnected()
        Log.i(TAG, "ShomerAccessibilityService connected")
        // Runtime config can override the XML config if needed (e.g. to update
        // the package set based on TargetAppRegistry.enabledProfiles()).
        val info = AccessibilityServiceInfo().apply {
            eventTypes = AccessibilityEvent.TYPE_WINDOW_CONTENT_CHANGED or
                    AccessibilityEvent.TYPE_VIEW_TEXT_CHANGED
            feedbackType = AccessibilityServiceInfo.FEEDBACK_GENERIC
            flags = AccessibilityServiceInfo.FLAG_REPORT_VIEW_IDS or
                    AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS
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

        val rootNode = rootInActiveWindow ?: return
        try {
            extractTextFromNode(rootNode, pkg)
        } finally {
            @Suppress("DEPRECATION")
            rootNode.recycle()
        }
    }

    /**
     * Walk the node tree recursively (bounded depth), collect text from leaf
     * nodes, infer direction, and submit to CaptureCoordinator.
     */
    private fun extractTextFromNode(
        node: AccessibilityNodeInfo,
        packageName: String,
        depth: Int = 0,
    ) {
        if (depth > MAX_TREE_DEPTH) return

        val text = (node.text?.toString() ?: node.contentDescription?.toString())
            ?.takeIf { it.isNotBlank() }

        if (text != null && node.childCount == 0) {
            // Only submit leaf nodes to avoid sending parent container text that
            // already contains the concatenation of its children.
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

    override fun onInterrupt() {
        Log.w(TAG, "ShomerAccessibilityService interrupted")
    }

    override fun onDestroy() {
        Log.i(TAG, "ShomerAccessibilityService destroyed")
        super.onDestroy()
    }

    companion object {
        private const val TAG = "ShomerA11y"
        private const val MAX_TREE_DEPTH = 10
    }
}
