package com.shomer.client.parent

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CalendarToday
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.shomer.client.data.FlaggedEventOut
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Alert list screen — the parent's home screen.
 *
 * Shows flagged events from GET /v1/parent/alerts.
 * Filter chips: All | Needs Review (review_needed) | Alerted | Done (acknowledged).
 * "Needs Review" is the default and is visually prominent — it's the borderline queue.
 *
 * Pull-to-refresh via PullToRefreshBox (Material 3 ExperimentalMaterial3Api).
 *
 * Hebrew RTL: text fields use TextAlign.Start, which mirrors correctly under
 * RTL locale because android:supportsRtl="true" is set in the Manifest.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AlertListScreen(
    vm: AlertListViewModel = hiltViewModel(),
    onAlertClick: (String) -> Unit,
    onOpenDigest: () -> Unit,
) {
    val state by vm.state.collectAsStateWithLifecycle()

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("Alerts") },
                actions = {
                    IconButton(onClick = onOpenDigest) {
                        Icon(Icons.Default.CalendarToday, contentDescription = "Daily Digest")
                    }
                    IconButton(onClick = vm::refreshAlerts) {
                        Icon(Icons.Default.Refresh, contentDescription = "Refresh")
                    }
                },
            )
        },
    ) { paddingValues ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(paddingValues),
        ) {
            // Filter chip row
            FilterChipRow(
                activeFilter = state.activeFilter,
                onFilterSelected = vm::setFilter,
            )

            // Child filter row (only shown if multiple children)
            if (state.children.size > 1) {
                ChildFilterRow(
                    children = state.children.map { it.childId to it.displayName },
                    selectedChildId = state.selectedChildId,
                    onChildSelected = vm::setChildFilter,
                )
            }

            // Content
            PullToRefreshBox(
                isRefreshing = state.isLoading,
                onRefresh = vm::refreshAlerts,
                modifier = Modifier.fillMaxSize(),
            ) {
                when {
                    state.error != null -> {
                        ErrorPanel(message = state.error!!, onRetry = vm::refreshAlerts)
                    }
                    state.alerts.isEmpty() && !state.isLoading -> {
                        EmptyPanel(filter = state.activeFilter)
                    }
                    else -> {
                        LazyColumn(
                            contentPadding = PaddingValues(horizontal = 16.dp, vertical = 8.dp),
                            verticalArrangement = Arrangement.spacedBy(8.dp),
                        ) {
                            items(state.alerts, key = { it.flagId }) { alert ->
                                AlertCard(
                                    alert = alert,
                                    onClick = { onAlertClick(alert.flagId) },
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun FilterChipRow(
    activeFilter: AlertFilter,
    onFilterSelected: (AlertFilter) -> Unit,
) {
    LazyRow(
        contentPadding = PaddingValues(horizontal = 16.dp, vertical = 8.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        items(AlertFilter.entries) { filter ->
            val isSelected = filter == activeFilter
            // Visually distinguish "Needs Review" — it's the parent's main action queue
            val isUrgent = filter == AlertFilter.REVIEW
            FilterChip(
                selected = isSelected,
                onClick = { onFilterSelected(filter) },
                label = { Text(filter.label, fontWeight = if (isUrgent) FontWeight.Bold else FontWeight.Normal) },
                colors = if (isUrgent && !isSelected) {
                    FilterChipDefaults.filterChipColors(
                        containerColor = MaterialTheme.colorScheme.errorContainer,
                        labelColor = MaterialTheme.colorScheme.onErrorContainer,
                    )
                } else {
                    FilterChipDefaults.filterChipColors()
                },
            )
        }
    }
}

@Composable
private fun ChildFilterRow(
    children: List<Pair<String, String>>,
    selectedChildId: String?,
    onChildSelected: (String?) -> Unit,
) {
    LazyRow(
        contentPadding = PaddingValues(horizontal = 16.dp, vertical = 4.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        item {
            FilterChip(
                selected = selectedChildId == null,
                onClick = { onChildSelected(null) },
                label = { Text("All Children") },
            )
        }
        items(children) { (childId, name) ->
            FilterChip(
                selected = childId == selectedChildId,
                onClick = { onChildSelected(childId) },
                label = { Text(name.ifBlank { childId.take(8) }) },
            )
        }
    }
}

@Composable
private fun AlertCard(
    alert: FlaggedEventOut,
    onClick: () -> Unit,
) {
    val isReviewNeeded = alert.status == "review_needed"
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onClick),
        colors = if (isReviewNeeded) {
            CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.errorContainer)
        } else {
            CardDefaults.cardColors()
        },
        elevation = CardDefaults.cardElevation(defaultElevation = if (isReviewNeeded) 4.dp else 1.dp),
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                // Label + severity badge
                Row(verticalAlignment = Alignment.CenterVertically) {
                    SeverityBadge(severity = alert.severity)
                    Spacer(Modifier.width(8.dp))
                    Text(
                        text = labelDisplayName(alert.label),
                        style = MaterialTheme.typography.labelLarge,
                        fontWeight = FontWeight.Bold,
                        color = if (isReviewNeeded) MaterialTheme.colorScheme.onErrorContainer
                        else MaterialTheme.colorScheme.onSurface,
                    )
                }
                // Status + time
                Column(horizontalAlignment = Alignment.End) {
                    StatusChip(status = alert.status)
                    Spacer(Modifier.height(2.dp))
                    Text(
                        text = formatEpoch(alert.createdAt),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }

            Spacer(Modifier.height(8.dp))

            // Quote
            Text(
                text = alert.quote,
                style = MaterialTheme.typography.bodyMedium,
                maxLines = 3,
                overflow = TextOverflow.Ellipsis,
                color = if (isReviewNeeded) MaterialTheme.colorScheme.onErrorContainer
                else MaterialTheme.colorScheme.onSurface,
            )

            Spacer(Modifier.height(4.dp))

            // App + direction
            Text(
                text = "${appDisplayName(alert.appPackage)} · ${directionDisplayName(alert.direction)}",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun ErrorPanel(message: String, onRetry: () -> Unit) {
    Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Text(
                text = message,
                color = MaterialTheme.colorScheme.error,
                style = MaterialTheme.typography.bodyMedium,
            )
            Spacer(Modifier.height(12.dp))
            TextButton(onClick = onRetry) { Text("Retry") }
        }
    }
}

@Composable
private fun EmptyPanel(filter: AlertFilter) {
    Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Text(
            text = when (filter) {
                AlertFilter.REVIEW -> "No events need your review — all clear"
                AlertFilter.ALERTED -> "No new alerts"
                AlertFilter.ACKNOWLEDGED -> "No acknowledged events yet"
                AlertFilter.ALL -> "No events yet"
            },
            style = MaterialTheme.typography.bodyLarge,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun SeverityBadge(severity: String) {
    val color = when (severity) {
        "critical" -> MaterialTheme.colorScheme.error
        "high" -> MaterialTheme.colorScheme.error.copy(alpha = 0.7f)
        "medium" -> MaterialTheme.colorScheme.secondary
        else -> MaterialTheme.colorScheme.outline
    }
    Text(
        text = severity.uppercase(),
        style = MaterialTheme.typography.labelSmall,
        color = color,
        fontWeight = FontWeight.Bold,
    )
}

@Composable
private fun StatusChip(status: String) {
    val displayName = when (status) {
        "review_needed" -> "Needs Review"
        "alerted" -> "Alerted"
        "acknowledged" -> "Acknowledged"
        "labeled" -> "Labeled"
        else -> status
    }
    Text(
        text = displayName,
        style = MaterialTheme.typography.labelSmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
}

// ---------------------------------------------------------------------------
// Display name helpers
// ---------------------------------------------------------------------------

internal fun labelDisplayName(label: String): String = when (label) {
    "abusive" -> "Abusive"
    "hate" -> "Hate Speech"
    "violence" -> "Violence"
    "pornographic" -> "Explicit Content"
    "non_offensive" -> "Non-Offensive"
    else -> label.replaceFirstChar { it.uppercase() }
}

internal fun severityDisplayName(severity: String): String = when (severity) {
    "low" -> "Low"
    "medium" -> "Medium"
    "high" -> "High"
    "critical" -> "Critical"
    else -> severity.replaceFirstChar { it.uppercase() }
}

internal fun directionDisplayName(direction: String): String = when (direction) {
    "inbound" -> "Received"
    "outbound" -> "Sent"
    else -> direction
}

internal fun appDisplayName(packageName: String): String = when (packageName) {
    "com.whatsapp" -> "WhatsApp"
    "com.instagram.android" -> "Instagram"
    "org.telegram.messenger" -> "Telegram"
    "com.facebook.orca" -> "Messenger"
    "com.snapchat.android" -> "Snapchat"
    else -> packageName.substringAfterLast('.')
        .replaceFirstChar { it.uppercase() }
}

private val dateFormat = SimpleDateFormat("dd/MM HH:mm", Locale.getDefault())

internal fun formatEpoch(epochSeconds: Double): String =
    dateFormat.format(Date((epochSeconds * 1000).toLong()))
