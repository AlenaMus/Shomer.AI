package com.shomer.client.onboarding

import android.content.Intent
import android.os.Build
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.shomer.client.R
import com.shomer.client.accessibility.TargetAppRegistry
import com.shomer.client.capture.CaptureForegroundService
import com.shomer.client.capture.CaptureCoordinator
import kotlinx.coroutines.delay

/**
 * Child-mode status screen — the home screen after onboarding is complete.
 *
 * Shows:
 *   - Monitoring on/off toggle (starts/stops CaptureForegroundService)
 *   - Paired child_id (from TokenStore)
 *   - Captured event count (from CaptureCoordinator counters)
 *   - Pending upload count (from EventDao.pendingCount())
 *   - List of monitored target apps
 *   - Settings button (server URL config)
 *
 * The counters are refreshed every 5s via a LaunchedEffect loop (cheap: in-memory
 * AtomicLong reads + one Room query per cycle).
 */
@Composable
fun StatusScreen(
    vm: OnboardingViewModel = hiltViewModel(),
    captureCoordinator: CaptureCoordinator,
    onOpenSettings: () -> Unit,
    onOpenActivity: () -> Unit,
) {
    val state by vm.state.collectAsStateWithLifecycle()
    val context = LocalContext.current

    // Refresh live counters every 5s.
    var captured by remember { mutableLongStateOf(0L) }      // lifetime total monitored
    var pendingUpload by remember { mutableLongStateOf(0L) }  // still waiting to upload
    LaunchedEffect(Unit) {
        while (true) {
            captured = captureCoordinator.insertedCount.get()
            // Pending drops to 0 once the server has received the events (immediate
            // push on capture, or the periodic upload loop ~1 min).
            pendingUpload = captureCoordinator.pendingCount().toLong()
            delay(5_000)
        }
    }

    // Re-check accessibility on each composition (user might toggle in settings)
    LaunchedEffect(Unit) { vm.refreshPermissionStatus() }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(24.dp),
    ) {
        // Header
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Text(
                text = "Shomer.AI",
                style = MaterialTheme.typography.headlineMedium,
                fontWeight = FontWeight.Bold,
            )
            IconButton(onClick = onOpenSettings) {
                Icon(Icons.Default.Settings, contentDescription = "Settings")
            }
        }

        Spacer(Modifier.height(8.dp))

        // Monitoring status card
        val isMonitoring = state.accessibilityEnabled
        Card(
            modifier = Modifier.fillMaxWidth(),
            colors = CardDefaults.cardColors(
                containerColor = if (isMonitoring) Color(0xFFE8F5E9) else Color(0xFFFFF3E0),
            ),
        ) {
            Column(modifier = Modifier.padding(16.dp)) {
                Text(
                    text = if (isMonitoring)
                        stringResource(R.string.status_monitoring_on)
                    else
                        stringResource(R.string.status_monitoring_off),
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Bold,
                    color = if (isMonitoring) Color(0xFF1B5E20) else Color(0xFFE65100),
                )
                Spacer(Modifier.height(8.dp))
                state.pairedChildId?.let { childId ->
                    Text(
                        text = stringResource(R.string.status_child_id, childId),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                Spacer(Modifier.height(4.dp))
                Text(
                    text = stringResource(R.string.status_captured, captured),
                    style = MaterialTheme.typography.bodySmall,
                )
                Text(
                    text = stringResource(R.string.status_pending, pendingUpload),
                    style = MaterialTheme.typography.bodySmall,
                    color = if (pendingUpload > 0L) Color(0xFFE65100) else Color(0xFF1B5E20),
                )
            }
        }

        Spacer(Modifier.height(16.dp))

        // Controls
        if (isMonitoring) {
            OutlinedButton(
                onClick = {
                    val intent = Intent(context, CaptureForegroundService::class.java).apply {
                        action = CaptureForegroundService.ACTION_STOP
                    }
                    context.startService(intent)
                    vm.refreshPermissionStatus()
                },
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(stringResource(R.string.status_stop_monitoring))
            }
        } else {
            FilledTonalButton(
                onClick = {
                    vm.startCapture()
                    vm.refreshPermissionStatus()
                },
                modifier = Modifier.fillMaxWidth(),
                enabled = state.pairingDone,
            ) {
                Text(stringResource(R.string.status_start_monitoring))
            }
        }

        Spacer(Modifier.height(12.dp))

        // View the per-message activity log (with server-receipt confirmation).
        OutlinedButton(
            onClick = onOpenActivity,
            modifier = Modifier.fillMaxWidth(),
        ) {
            Text("View monitored messages")
        }

        Spacer(Modifier.height(24.dp))

        // Target apps
        Text(
            text = stringResource(R.string.status_target_apps),
            style = MaterialTheme.typography.titleSmall,
            fontWeight = FontWeight.SemiBold,
        )
        Spacer(Modifier.height(8.dp))
        TargetAppRegistry.allProfiles().forEach { profile ->
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(vertical = 4.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Text(
                    text = profile.displayName,
                    style = MaterialTheme.typography.bodyMedium,
                )
                Text(
                    text = if (profile.enabled) "On" else "Off",
                    style = MaterialTheme.typography.labelSmall,
                    color = if (profile.enabled) Color(0xFF1B5E20)
                    else MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }

        if (!state.accessibilityEnabled) {
            Spacer(Modifier.height(16.dp))
            Card(
                colors = CardDefaults.cardColors(
                    containerColor = MaterialTheme.colorScheme.errorContainer,
                ),
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(
                    text = "Accessibility access is not enabled. Monitoring is inactive.",
                    modifier = Modifier.padding(12.dp),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onErrorContainer,
                )
            }
        }
    }
}
