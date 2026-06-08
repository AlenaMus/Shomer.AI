package com.shomer.client.ui.theme

import android.os.Build
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.dynamicDarkColorScheme
import androidx.compose.material3.dynamicLightColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.platform.LocalContext

private val LightColors = lightColorScheme()
private val DarkColors = darkColorScheme()

/**
 * Shomer.AI Material 3 theme.
 *
 * Uses dynamic color (Material You) on Android 12+ where available.
 * Falls back to the default Material 3 color scheme on older devices.
 *
 * Parent-facing polish (custom color palette, typography) is deferred to the
 * frontend-design skill pass — this theme provides a clean, correct base.
 *
 * RTL layout is handled by the system (android:supportsRtl="true" in the
 * manifest) and Compose's automatic mirroring. No LocalLayoutDirection override
 * is needed at the theme level.
 */
@Composable
fun AppTheme(
    useDarkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit,
) {
    val colors = when {
        Build.VERSION.SDK_INT >= Build.VERSION_CODES.S -> {
            val ctx = LocalContext.current
            if (useDarkTheme) dynamicDarkColorScheme(ctx) else dynamicLightColorScheme(ctx)
        }
        useDarkTheme -> DarkColors
        else -> LightColors
    }
    MaterialTheme(colorScheme = colors, content = content)
}
