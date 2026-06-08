package com.shomer.client.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Button
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.shomer.client.data.ApiService
import com.shomer.client.data.SettingsRepository
import com.shomer.client.viewmodel.ClassifyViewModel
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch

/**
 * Settings screen — server URL configuration + connection test.
 *
 * Migrated from the POC com.dima.offensivehebrew.ui.SettingsScreen.
 * Now uses Hilt-provided SettingsRepository via the ClassifyViewModel.
 *
 * The server URL configures the Retrofit base URL. After changing the URL,
 * the app needs to be restarted for the Retrofit singleton to pick it up
 * (MVP limitation — noted in NetworkModule; dynamic URL interceptor is A6).
 */
@Composable
fun SettingsScreen(
    modifier: Modifier = Modifier,
    onBack: () -> Unit,
) {
    val vm: ClassifyViewModel = hiltViewModel()
    val scope = rememberCoroutineScope()
    val savedUrl by vm.serverUrl.collectAsStateWithLifecycle(
        initialValue = SettingsRepository.DEFAULT_SERVER_URL,
    )

    var url by remember { mutableStateOf(savedUrl) }
    var status by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(savedUrl) { url = savedUrl }

    Column(
        modifier = modifier
            .fillMaxSize()
            .padding(16.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = onBack) {
                Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
            }
            Text("Settings", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold)
        }

        Spacer(Modifier.height(16.dp))

        Text("Server URL", style = MaterialTheme.typography.titleSmall)
        Text(
            "Emulator: http://10.0.2.2:8000/   •   Phone on Wi-Fi: http://<PC-LAN-IP>:8000/",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Spacer(Modifier.height(8.dp))
        OutlinedTextField(
            value = url,
            onValueChange = { url = it; status = null },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )

        Spacer(Modifier.height(12.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Button(onClick = {
                scope.launch {
                    vm.saveServerUrl(url.trim())
                    status = "Saved. Restart the app for the new URL to take effect."
                }
            }) { Text("Save") }
            OutlinedButton(onClick = {
                scope.launch {
                    status = "Testing…"
                    try {
                        val result = vm.testConnection(url.trim())
                        status = result
                    } catch (t: Throwable) {
                        status = "Failed: ${t.message ?: t.javaClass.simpleName}"
                    }
                }
            }) { Text("Test connection") }
        }

        Spacer(Modifier.height(12.dp))
        status?.let { Text(it, style = MaterialTheme.typography.bodyMedium) }

        Spacer(Modifier.height(32.dp))
        Text(
            "Debug classify screen is available via the nav menu in future builds.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}
