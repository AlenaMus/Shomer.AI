package com.dima.offensivehebrew.ui

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
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.dima.offensivehebrew.data.ApiFactory
import com.dima.offensivehebrew.data.SettingsRepository
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch

@Composable
fun SettingsScreen(
    modifier: Modifier = Modifier,
    onBack: () -> Unit,
) {
    val ctx = LocalContext.current
    val repo = remember { SettingsRepository(ctx) }
    val scope = rememberCoroutineScope()
    val savedUrl by repo.serverUrl.collectAsState(initial = SettingsRepository.DEFAULT_SERVER_URL)

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
                    repo.setServerUrl(url.trim())
                    status = "Saved."
                }
            }) { Text("Save") }
            OutlinedButton(onClick = {
                scope.launch {
                    status = "Testing…"
                    val saved = repo.serverUrl.first()
                    try {
                        val api = ApiFactory.create(url.trim().ifBlank { saved })
                        val h = api.health()
                        status = "OK — status=${h.status}, ollama=${h.ollamaReachable}, model=${h.model}"
                    } catch (t: Throwable) {
                        status = "Failed: ${t.message ?: t.javaClass.simpleName}"
                    }
                }
            }) { Text("Test connection") }
        }

        Spacer(Modifier.height(12.dp))
        status?.let { Text(it, style = MaterialTheme.typography.bodyMedium) }
    }
}
