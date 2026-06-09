package com.shomer.client.onboarding

import android.Manifest
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.Button
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.hilt.navigation.compose.hiltViewModel
import com.shomer.client.R

/**
 * Permission flow screen — guides the guardian through three mandatory permissions:
 *   1. Accessibility Service enable (deep-link to system settings)
 *   2. POST_NOTIFICATIONS runtime permission (API 33+)
 *   3. Battery optimization exemption (deep-link to system settings)
 *
 * None of these can be granted programmatically — the user must confirm in the
 * system settings dialogs. We use onResume (via LaunchedEffect re-trigger on
 * lifecycle) to refresh the detected state after the user returns.
 *
 * Once all three are detected, the "Start Monitoring" button becomes active, which
 * starts CaptureForegroundService and navigates to the status screen.
 */
@Composable
fun PermissionFlowScreen(
    vm: OnboardingViewModel = hiltViewModel(),
    onPermissionsDone: () -> Unit,
) {
    val state by vm.state.collectAsStateWithLifecycle()
    val context = LocalContext.current

    // Re-check permission status every time this composable re-enters the composition
    // (e.g. when the user returns from the system settings screen).
    LaunchedEffect(Unit) { vm.refreshPermissionStatus() }

    // POST_NOTIFICATIONS runtime request (API 33+ only)
    val notifPermLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { granted ->
        vm.refreshPermissionStatus()
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(24.dp)
            .verticalScroll(rememberScrollState()),
    ) {
        Text(
            text = "Set Up Monitoring",
            style = MaterialTheme.typography.headlineMedium,
            fontWeight = FontWeight.Bold,
        )
        Text(
            text = "Three permissions are required for monitoring to work. Tap each button to grant them.",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )

        Spacer(Modifier.height(32.dp))

        // --- 1. Accessibility ---
        PermissionRow(
            title = stringResource(R.string.permission_accessibility_title),
            description = stringResource(R.string.permission_accessibility_body),
            isGranted = state.accessibilityEnabled,
            buttonText = stringResource(R.string.permission_accessibility_button),
            onButtonClick = {
                context.startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
            },
        )

        Spacer(Modifier.height(24.dp))

        // --- 2. POST_NOTIFICATIONS (API 33+ only) ---
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            PermissionRow(
                title = stringResource(R.string.permission_notification_title),
                description = stringResource(R.string.permission_notification_body),
                isGranted = state.notificationPermissionGranted,
                buttonText = stringResource(R.string.permission_notification_button),
                onButtonClick = {
                    notifPermLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
                },
            )
            Spacer(Modifier.height(24.dp))
        }

        // --- 3. Battery optimization ---
        PermissionRow(
            title = stringResource(R.string.permission_battery_title),
            description = stringResource(R.string.permission_battery_body),
            isGranted = state.batteryOptimizationExempt,
            buttonText = stringResource(R.string.permission_battery_button),
            onButtonClick = {
                // Some OEMs (e.g. Huawei/EMUI) don't handle the per-app battery
                // intent — fall back to the generic optimization list, then to the
                // app-details page, so the button always opens *something*.
                val intents = buildList {
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                        add(
                            Intent(
                                Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,
                                Uri.parse("package:${context.packageName}"),
                            ),
                        )
                        add(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))
                    }
                    add(
                        Intent(
                            Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                            Uri.parse("package:${context.packageName}"),
                        ),
                    )
                }
                for (intent in intents) {
                    try {
                        context.startActivity(intent)
                        break
                    } catch (e: android.content.ActivityNotFoundException) {
                        // Try the next fallback.
                    }
                }
            },
        )

        Spacer(Modifier.height(32.dp))

        // Refresh button — lets the user recheck after returning from settings.
        OutlinedButton(
            onClick = vm::refreshPermissionStatus,
            modifier = Modifier.fillMaxWidth(),
        ) {
            Text("Refresh permission status")
        }

        Spacer(Modifier.height(16.dp))

        // Start monitoring — requires at minimum the accessibility permission.
        Button(
            onClick = {
                vm.startCapture()
                onPermissionsDone()
            },
            enabled = state.accessibilityEnabled,
            modifier = Modifier.fillMaxWidth(),
        ) {
            Text("Start Monitoring")
        }

        if (!state.accessibilityEnabled) {
            Spacer(Modifier.height(8.dp))
            Text(
                text = "Enable Accessibility access first (required)",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.error,
            )
        }
    }
}

@Composable
private fun PermissionRow(
    title: String,
    description: String,
    isGranted: Boolean,
    buttonText: String,
    onButtonClick: () -> Unit,
) {
    Column {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(
                imageVector = if (isGranted) Icons.Default.Check else Icons.Default.Warning,
                contentDescription = null,
                tint = if (isGranted) Color(0xFF1B5E20) else MaterialTheme.colorScheme.error,
                modifier = Modifier.size(20.dp),
            )
            Spacer(Modifier.width(8.dp))
            Text(
                text = title,
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.SemiBold,
            )
        }
        Spacer(Modifier.height(4.dp))
        Text(
            text = description,
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.height(8.dp))
        if (!isGranted) {
            Button(onClick = onButtonClick) {
                Text(buttonText)
            }
        }
    }
}
