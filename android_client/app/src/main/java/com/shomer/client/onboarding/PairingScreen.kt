package com.shomer.client.onboarding

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.hilt.navigation.compose.hiltViewModel
import com.shomer.client.R
import kotlinx.coroutines.launch

/**
 * Pairing screen — the guardian enters the 6-8 digit OTP from the parent dashboard.
 *
 * On successful POST /v1/pair, the device_token and child_id are stored in
 * TokenStore (EncryptedSharedPreferences) and the MonitorUploader periodic worker
 * is scheduled. The onPairingDone callback navigates to the permission flow.
 *
 * The frozen server contract for POST /v1/pair:
 *   Request:  { code: string, device_fingerprint: string }
 *   Response: { device_token: string, child_id: string, role: string }
 */
@Composable
fun PairingScreen(
    vm: OnboardingViewModel = hiltViewModel(),
    onPairingDone: () -> Unit,
) {
    val state by vm.state.collectAsStateWithLifecycle()
    val savedServerUrl by vm.serverUrl.collectAsStateWithLifecycle()
    val scope = rememberCoroutineScope()

    var serverEditorOpen by remember { mutableStateOf(false) }
    var serverUrlField by remember { mutableStateOf(savedServerUrl) }
    var connectionStatus by remember { mutableStateOf<String?>(null) }
    var testing by remember { mutableStateOf(false) }
    LaunchedEffect(savedServerUrl) { serverUrlField = savedServerUrl }

    // Navigate when pairing completes (avoids navigation inside a coroutine).
    LaunchedEffect(state.pairingDone) {
        if (state.pairingDone) onPairingDone()
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Spacer(Modifier.height(32.dp))

        Text(
            text = stringResource(R.string.pairing_title),
            style = MaterialTheme.typography.headlineMedium,
            fontWeight = FontWeight.Bold,
        )

        Spacer(Modifier.height(8.dp))

        Text(
            text = "Get this code from the parent dashboard by tapping \"Add Child Device\".",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )

        Spacer(Modifier.height(32.dp))

        OutlinedTextField(
            value = state.pairingCode,
            onValueChange = vm::setPairingCode,
            label = { Text(stringResource(R.string.pairing_hint)) },
            singleLine = true,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
            modifier = Modifier.fillMaxWidth(),
            isError = state.pairingError != null,
            supportingText = state.pairingError?.let { { Text(it, color = MaterialTheme.colorScheme.error) } },
        )

        Spacer(Modifier.height(24.dp))

        if (state.isPairing) {
            CircularProgressIndicator()
            Spacer(Modifier.height(8.dp))
            Text("Pairing with server…", style = MaterialTheme.typography.bodyMedium)
        } else {
            Button(
                onClick = vm::pair,
                modifier = Modifier.fillMaxWidth(),
                enabled = state.pairingCode.isNotBlank(),
            ) {
                Text(stringResource(R.string.pairing_button))
            }
        }

        state.pairedChildId?.let { childId ->
            Spacer(Modifier.height(16.dp))
            Text(
                text = "Paired! Child ID: $childId",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.primary,
            )
        }

        Spacer(Modifier.height(32.dp))

        // --- Server connection (editable + testable before pairing) ---
        TextButton(onClick = { serverEditorOpen = !serverEditorOpen }) {
            Text(if (serverEditorOpen) "Hide server settings" else "Server settings")
        }
        Text(
            text = savedServerUrl,
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )

        if (serverEditorOpen) {
            Spacer(Modifier.height(8.dp))
            OutlinedTextField(
                value = serverUrlField,
                onValueChange = { serverUrlField = it; connectionStatus = null },
                label = { Text("Server URL (http://PC-IP:PORT/)") },
                singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri),
                modifier = Modifier.fillMaxWidth(),
            )
            Spacer(Modifier.height(8.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                OutlinedButton(
                    enabled = !testing,
                    onClick = {
                        scope.launch {
                            testing = true
                            connectionStatus = "Testing…"
                            connectionStatus = vm.testConnection(serverUrlField)
                            testing = false
                        }
                    },
                ) { Text("Test connection") }
                Button(onClick = {
                    vm.saveServerUrl(serverUrlField)
                    connectionStatus = "Saved — applies immediately."
                }) { Text("Save") }
            }
            connectionStatus?.let {
                Spacer(Modifier.height(8.dp))
                Text(it, style = MaterialTheme.typography.bodyMedium)
            }
        }
    }
}
