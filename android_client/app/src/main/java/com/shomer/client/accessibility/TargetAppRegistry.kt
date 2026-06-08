package com.shomer.client.accessibility

/**
 * Registry of monitored app packages and per-app direction inference profiles.
 *
 * Seeded with the four initial target apps. Adding a new app = adding a profile
 * here + adding its packageName to accessibility_service_config.xml (which is
 * the hard ceiling; the runtime registry can be a subset).
 *
 * The user-editable target-app picker (A3) writes its selection to the registry
 * via setEnabled(). Until the picker is built, all seeded apps are enabled.
 */
object TargetAppRegistry {

    /** Direction inference strategy for a given source app. */
    enum class DirectionStrategy {
        /** Treat all captured text as inbound (conservative default). */
        DEFAULT_INBOUND,
        /**
         * Use basic heuristics: text from a compose/reply box is outbound;
         * text from message bubbles is inbound. The exact view-id / class-name
         * heuristics are per-app and may need tuning on actual WhatsApp/IG builds.
         */
        HEURISTIC,
    }

    data class AppProfile(
        val packageName: String,
        val displayName: String,
        val directionStrategy: DirectionStrategy = DirectionStrategy.DEFAULT_INBOUND,
        var enabled: Boolean = true,
    )

    private val profiles: MutableMap<String, AppProfile> = mutableMapOf(
        "com.whatsapp" to AppProfile(
            packageName = "com.whatsapp",
            displayName = "WhatsApp",
            directionStrategy = DirectionStrategy.HEURISTIC,
        ),
        "com.instagram.android" to AppProfile(
            packageName = "com.instagram.android",
            displayName = "Instagram",
            directionStrategy = DirectionStrategy.DEFAULT_INBOUND,
        ),
        "org.telegram.messenger" to AppProfile(
            packageName = "org.telegram.messenger",
            displayName = "Telegram",
            directionStrategy = DirectionStrategy.DEFAULT_INBOUND,
        ),
        "com.facebook.orca" to AppProfile(
            packageName = "com.facebook.orca",
            displayName = "Messenger",
            directionStrategy = DirectionStrategy.DEFAULT_INBOUND,
        ),
    )

    fun isEnabled(packageName: String): Boolean =
        profiles[packageName]?.enabled == true

    fun getProfile(packageName: String): AppProfile? = profiles[packageName]

    fun setEnabled(packageName: String, enabled: Boolean) {
        profiles[packageName]?.let { it.enabled = enabled }
    }

    fun allProfiles(): List<AppProfile> = profiles.values.toList()

    fun enabledProfiles(): List<AppProfile> = profiles.values.filter { it.enabled }

    /** Infer direction from node class name and view-id hints. */
    fun inferDirection(
        packageName: String,
        viewClassName: String?,
        viewId: String?,
    ): String {
        val profile = profiles[packageName] ?: return "inbound"
        return when (profile.directionStrategy) {
            DirectionStrategy.DEFAULT_INBOUND -> "inbound"
            DirectionStrategy.HEURISTIC -> heuristicDirection(viewClassName, viewId)
        }
    }

    /**
     * Heuristic direction inference based on view class / id patterns.
     *
     * Compose boxes are typically EditText / AppCompatEditText and the view-id
     * often contains "compose", "reply", "input", "send", or "message_input".
     * This is a best-effort heuristic; it may misfire on UI updates — the
     * conservative default (inbound) is the privacy-safer choice.
     */
    private fun heuristicDirection(className: String?, viewId: String?): String {
        val lowerClass = className?.lowercase() ?: ""
        val lowerId = viewId?.lowercase() ?: ""

        val composeKeywords = listOf("compose", "reply", "input", "send", "edit", "type")
        if ("edittext" in lowerClass || "edittext" in lowerId) return "outbound"
        if (composeKeywords.any { it in lowerId }) return "outbound"

        return "inbound"
    }
}
