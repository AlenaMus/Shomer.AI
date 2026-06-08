package com.shomer.client.parent

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.shomer.client.data.FlaggedEventOut

/**
 * Alert detail screen.
 *
 * Shows: quote + explanation + metadata (label, severity, app, direction, status, time).
 * Offers three react action groups:
 *   1. Acknowledge (closes the alert)
 *   2. Label offensive / not_offensive (stores human verdict → DictaBERT training data)
 *   3. Severity override: low / medium / high / critical
 *
 * On successful reaction → reactionDone=true → onBack() pops the backstack.
 *
 * RTL: Hebrew text in quote/explanation auto-renders RTL under supportsRtl="true".
 * We do NOT force LayoutDirection here — Compose inherits the device locale.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AlertDetailScreen(
    flagId: String,
    vm: AlertDetailViewModel = hiltViewModel(),
    onBack: () -> Unit,
) {
    val state by vm.state.collectAsStateWithLifecycle()

    // Pop back after successful react
    LaunchedEffect(state.reactionDone) {
        if (state.reactionDone) onBack()
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Alert Detail") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
                    }
                },
            )
        },
    ) { paddingValues ->
        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(paddingValues),
        ) {
            when {
                state.isLoading -> {
                    CircularProgressIndicator(modifier = Modifier.align(Alignment.Center))
                }
                state.error != null -> {
                    Column(
                        modifier = Modifier
                            .fillMaxSize()
                            .padding(24.dp),
                        horizontalAlignment = Alignment.CenterHorizontally,
                        verticalArrangement = Arrangement.Center,
                    ) {
                        Text(
                            text = state.error!!,
                            color = MaterialTheme.colorScheme.error,
                            style = MaterialTheme.typography.bodyMedium,
                        )
                        Spacer(Modifier.height(12.dp))
                        TextButton(onClick = vm::loadAlert) { Text("Retry") }
                    }
                }
                state.alert != null -> {
                    AlertDetailContent(
                        alert = state.alert!!,
                        isReacting = state.isReacting,
                        reactionError = state.reactionError,
                        onAcknowledge = vm::acknowledge,
                        onLabelOffensive = vm::labelOffensive,
                        onLabelNotOffensive = vm::labelNotOffensive,
                        onSetSeverity = vm::setSeverity,
                    )
                }
            }
        }
    }
}

@Composable
private fun AlertDetailContent(
    alert: FlaggedEventOut,
    isReacting: Boolean,
    reactionError: String?,
    onAcknowledge: () -> Unit,
    onLabelOffensive: () -> Unit,
    onLabelNotOffensive: () -> Unit,
    onSetSeverity: (String) -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 20.dp, vertical = 16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        // --- Metadata card ---
        Card(modifier = Modifier.fillMaxWidth()) {
            Column(modifier = Modifier.padding(16.dp)) {
                MetaRow("Label", labelDisplayName(alert.label))
                MetaRow("Severity", severityDisplayName(alert.severity))
                MetaRow("App", appDisplayName(alert.appPackage))
                MetaRow("Direction", directionDisplayName(alert.direction))
                MetaRow("Status", statusDisplayName(alert.status))
                MetaRow("Time", formatEpoch(alert.createdAt))
                if (alert.parentLabel != null) {
                    MetaRow("Your Label", alert.parentLabel)
                }
                if (alert.parentSeverity != null) {
                    MetaRow("Your Severity", alert.parentSeverity)
                }
            }
        }

        // --- Quote card ---
        Card(
            modifier = Modifier.fillMaxWidth(),
            colors = CardDefaults.cardColors(
                containerColor = MaterialTheme.colorScheme.surfaceVariant,
            ),
        ) {
            Column(modifier = Modifier.padding(16.dp)) {
                Text(
                    text = "Message",
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    fontWeight = FontWeight.Bold,
                )
                Spacer(Modifier.height(8.dp))
                Text(
                    text = alert.quote,
                    style = MaterialTheme.typography.bodyLarge,
                )
            }
        }

        // --- Explanation card ---
        if (alert.explanation.isNotBlank()) {
            Card(modifier = Modifier.fillMaxWidth()) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Text(
                        text = "Explanation",
                        style = MaterialTheme.typography.labelMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        fontWeight = FontWeight.Bold,
                    )
                    Spacer(Modifier.height(8.dp))
                    Text(
                        text = alert.explanation,
                        style = MaterialTheme.typography.bodyMedium,
                    )
                }
            }
        }

        // --- Reaction error ---
        if (reactionError != null) {
            Text(
                text = reactionError,
                color = MaterialTheme.colorScheme.error,
                style = MaterialTheme.typography.bodySmall,
            )
        }

        // --- React action section (disabled while reacting) ---
        if (isReacting) {
            Box(modifier = Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
                CircularProgressIndicator()
            }
        } else {
            // 1. Acknowledge
            Button(
                onClick = onAcknowledge,
                modifier = Modifier.fillMaxWidth(),
                colors = ButtonDefaults.buttonColors(
                    containerColor = MaterialTheme.colorScheme.secondary,
                ),
            ) {
                Text("Mark as Seen (Acknowledge)")
            }

            // 2. Label
            Text(
                text = "Your Verdict",
                style = MaterialTheme.typography.labelLarge,
                fontWeight = FontWeight.Bold,
            )
            Row(
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                modifier = Modifier.fillMaxWidth(),
            ) {
                Button(
                    onClick = onLabelOffensive,
                    modifier = Modifier.weight(1f),
                    colors = ButtonDefaults.buttonColors(
                        containerColor = MaterialTheme.colorScheme.error,
                    ),
                ) {
                    Text("Offensive")
                }
                OutlinedButton(
                    onClick = onLabelNotOffensive,
                    modifier = Modifier.weight(1f),
                ) {
                    Text("Not Offensive")
                }
            }

            // 3. Severity override
            Text(
                text = "Set Severity",
                style = MaterialTheme.typography.labelLarge,
                fontWeight = FontWeight.Bold,
            )
            Row(
                horizontalArrangement = Arrangement.spacedBy(6.dp),
                modifier = Modifier.fillMaxWidth(),
            ) {
                listOf("low", "medium", "high", "critical").forEach { sev ->
                    OutlinedButton(
                        onClick = { onSetSeverity(sev) },
                        modifier = Modifier.weight(1f),
                        contentPadding = androidx.compose.foundation.layout.PaddingValues(4.dp),
                    ) {
                        Text(
                            text = sev.replaceFirstChar { it.uppercase() },
                            style = MaterialTheme.typography.labelSmall,
                        )
                    }
                }
            }
        }

        Spacer(Modifier.height(24.dp))
    }
}

@Composable
private fun MetaRow(label: String, value: String) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 2.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(
            text = label,
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Text(
            text = value,
            style = MaterialTheme.typography.bodySmall,
            fontWeight = FontWeight.Medium,
        )
    }
}

private fun statusDisplayName(status: String): String = when (status) {
    "alerted" -> "Alerted"
    "review_needed" -> "Needs Review"
    "acknowledged" -> "Acknowledged"
    "labeled" -> "Labeled"
    else -> status
}
