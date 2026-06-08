package com.shomer.client.onboarding

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.shomer.client.R

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
    vm: OnboardingViewModel = viewModel(),
    onPairingDone: () -> Unit,
) {
    val state by vm.state.collectAsStateWithLifecycle()

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
    }
}
