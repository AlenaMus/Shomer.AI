package com.shomer.client.onboarding

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.shomer.client.monitor.MonitorActivityLog
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Child-mode "Monitor Activity" screen — a transparency log showing each captured
 * message, when it was captured, and whether the server has confirmed receipt.
 *
 *   PENDING — buffered on device, not yet uploaded
 *   SENT    — server returned 2xx (received + processed)
 *   FAILED  — permanent upload failure (e.g. needs re-pair)
 *
 * Entries are in-memory (last 100) and reset on app restart; the durable record is
 * server-side.
 */
@Composable
fun MonitorActivityScreen(
    vm: OnboardingViewModel = hiltViewModel(),
    onBack: () -> Unit,
) {
    val entries by vm.monitorActivity.collectAsStateWithLifecycle()
    val timeFmt = remember { SimpleDateFormat("HH:mm:ss", Locale.getDefault()) }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = onBack) {
                Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
            }
            Text(
                "Monitor Activity",
                style = MaterialTheme.typography.titleLarge,
                fontWeight = FontWeight.SemiBold,
            )
        }
        Text(
            "Messages captured on this device and whether the server has confirmed receipt.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.height(12.dp))

        if (entries.isEmpty()) {
            Text(
                "No messages captured yet. Send a Hebrew message in a monitored app.",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        } else {
            LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                items(entries, key = { it.clientMsgId }) { entry ->
                    ActivityRow(entry, timeFmt.format(Date(entry.capturedAtMs)))
                }
            }
        }
    }
}

@Composable
private fun ActivityRow(entry: MonitorActivityLog.Entry, timeLabel: String) {
    val (statusText, statusColor) = when (entry.status) {
        MonitorActivityLog.Status.SENT -> "✓ SENT" to Color(0xFF1B5E20)
        MonitorActivityLog.Status.PENDING -> "… PENDING" to Color(0xFFE65100)
        MonitorActivityLog.Status.FAILED -> "✗ FAILED" to MaterialTheme.colorScheme.error
    }
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant),
    ) {
        Column(Modifier.padding(12.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = "$timeLabel · ${entry.direction}",
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Text(
                    text = statusText,
                    style = MaterialTheme.typography.labelMedium,
                    fontWeight = FontWeight.Bold,
                    color = statusColor,
                )
            }
            Spacer(Modifier.height(4.dp))
            HorizontalDivider()
            Spacer(Modifier.height(4.dp))
            Text(
                text = entry.text,
                style = MaterialTheme.typography.bodyMedium,
            )
        }
    }
}
