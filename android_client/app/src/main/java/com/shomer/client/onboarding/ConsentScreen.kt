package com.shomer.client.onboarding

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Checkbox
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.shomer.client.R

/**
 * Mandatory consent screen — dual disclosure to guardian + child acknowledgement.
 *
 * Both checkboxes must be ticked before the guardian can proceed. This implements
 * the privacy.decision.md D4 requirement for dual consent + explicit outbound-
 * message disclosure.
 *
 * This screen is shown only once (tokenStore.hasConsented() becomes true after
 * confirmation). On re-entry it is skipped by the MainActivity nav logic.
 */
@Composable
fun ConsentScreen(
    vm: OnboardingViewModel = viewModel(),
    onConsentDone: () -> Unit,
) {
    val state by vm.state.collectAsStateWithLifecycle()

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(24.dp)
            .verticalScroll(rememberScrollState()),
    ) {
        Text(
            text = stringResource(R.string.consent_title),
            style = MaterialTheme.typography.headlineMedium,
            fontWeight = FontWeight.Bold,
        )

        Spacer(Modifier.height(16.dp))

        Card(
            modifier = Modifier.fillMaxWidth(),
            colors = CardDefaults.cardColors(
                containerColor = MaterialTheme.colorScheme.surfaceVariant,
            ),
        ) {
            Text(
                text = stringResource(R.string.consent_body),
                modifier = Modifier.padding(16.dp),
                style = MaterialTheme.typography.bodyMedium,
            )
        }

        Spacer(Modifier.height(24.dp))

        ConsentCheckbox(
            text = stringResource(R.string.consent_guardian_checkbox),
            checked = state.guardianChecked,
            onChecked = vm::setGuardianChecked,
        )

        Spacer(Modifier.height(12.dp))

        ConsentCheckbox(
            text = stringResource(R.string.consent_child_checkbox),
            checked = state.childChecked,
            onChecked = vm::setChildChecked,
        )

        Spacer(Modifier.height(32.dp))

        Button(
            onClick = {
                vm.confirmConsent()
                if (state.guardianChecked && state.childChecked) onConsentDone()
            },
            enabled = state.guardianChecked && state.childChecked,
            modifier = Modifier.fillMaxWidth(),
        ) {
            Text(stringResource(R.string.consent_continue))
        }
    }
}

@Composable
private fun ConsentCheckbox(
    text: String,
    checked: Boolean,
    onChecked: (Boolean) -> Unit,
) {
    Row(
        verticalAlignment = Alignment.Top,
        modifier = Modifier.fillMaxWidth(),
    ) {
        Checkbox(
            checked = checked,
            onCheckedChange = onChecked,
        )
        Text(
            text = text,
            modifier = Modifier
                .padding(start = 8.dp, top = 12.dp)
                .weight(1f),
            style = MaterialTheme.typography.bodyMedium,
        )
    }
}
