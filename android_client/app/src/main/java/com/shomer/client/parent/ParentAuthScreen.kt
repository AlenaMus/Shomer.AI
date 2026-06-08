package com.shomer.client.parent

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
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle

/**
 * Parent auth screen — two tabs:
 *   Tab 0: Create new account (POST /v1/parent/register)
 *   Tab 1: Use existing parent token (paste the opaque token)
 *
 * After successful auth, authDone triggers navigation to AlertListScreen.
 * The stored token is automatically sent by AuthInterceptor on all /v1/ calls.
 *
 * RTL: TextAlign is Start (auto-handled by android:supportsRtl="true").
 */
@Composable
fun ParentAuthScreen(
    vm: ParentAuthViewModel = hiltViewModel(),
    onAuthDone: () -> Unit,
) {
    val state by vm.state.collectAsStateWithLifecycle()

    LaunchedEffect(state.authDone) {
        if (state.authDone) onAuthDone()
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(horizontal = 24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Spacer(Modifier.height(32.dp))

        Text(
            text = "Parent Setup",
            style = MaterialTheme.typography.headlineMedium,
            fontWeight = FontWeight.Bold,
        )

        Spacer(Modifier.height(8.dp))

        Text(
            text = "Set up your parent account to receive alerts about your child's activity.",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )

        Spacer(Modifier.height(24.dp))

        TabRow(selectedTabIndex = if (state.isCreateMode) 0 else 1) {
            Tab(
                selected = state.isCreateMode,
                onClick = { vm.setCreateMode(true) },
                text = { Text("Create Account") },
            )
            Tab(
                selected = !state.isCreateMode,
                onClick = { vm.setCreateMode(false) },
                text = { Text("Existing Token") },
            )
        }

        Spacer(Modifier.height(24.dp))

        if (state.isCreateMode) {
            CreateAccountPanel(
                displayName = state.displayName,
                onDisplayNameChange = vm::setDisplayName,
                isLoading = state.isLoading,
                error = state.error,
                onCreateClick = vm::createAccount,
            )
        } else {
            ExistingTokenPanel(
                existingToken = state.existingToken,
                onTokenChange = vm::setExistingToken,
                error = state.error,
                onUseTokenClick = vm::useExistingToken,
            )
        }
    }
}

@Composable
private fun CreateAccountPanel(
    displayName: String,
    onDisplayNameChange: (String) -> Unit,
    isLoading: Boolean,
    error: String?,
    onCreateClick: () -> Unit,
) {
    OutlinedTextField(
        value = displayName,
        onValueChange = onDisplayNameChange,
        label = { Text("Your name (optional)") },
        singleLine = true,
        modifier = Modifier.fillMaxWidth(),
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Text),
    )

    Spacer(Modifier.height(8.dp))

    Text(
        text = "A parent account will be created on the server. " +
                "Your parent token will be saved securely on this device.",
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )

    Spacer(Modifier.height(16.dp))

    if (error != null) {
        Text(
            text = error,
            color = MaterialTheme.colorScheme.error,
            style = MaterialTheme.typography.bodySmall,
        )
        Spacer(Modifier.height(8.dp))
    }

    if (isLoading) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            CircularProgressIndicator()
            Spacer(Modifier.padding(start = 8.dp))
            Text("Creating account…", style = MaterialTheme.typography.bodyMedium)
        }
    } else {
        Button(
            onClick = onCreateClick,
            modifier = Modifier.fillMaxWidth(),
        ) {
            Text("Create Parent Account")
        }
    }
}

@Composable
private fun ExistingTokenPanel(
    existingToken: String,
    onTokenChange: (String) -> Unit,
    error: String?,
    onUseTokenClick: () -> Unit,
) {
    OutlinedTextField(
        value = existingToken,
        onValueChange = onTokenChange,
        label = { Text("Paste your parent token") },
        singleLine = false,
        minLines = 3,
        maxLines = 5,
        modifier = Modifier.fillMaxWidth(),
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Text),
        isError = error != null,
        supportingText = error?.let { { Text(it, color = MaterialTheme.colorScheme.error) } },
    )

    Spacer(Modifier.height(8.dp))

    Text(
        text = "Paste the parent_token you received when your account was created. " +
                "The token is stored locally — it never leaves this device except as " +
                "an Authorization header to the Shomer server.",
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )

    Spacer(Modifier.height(16.dp))

    Button(
        onClick = onUseTokenClick,
        modifier = Modifier.fillMaxWidth(),
        enabled = existingToken.isNotBlank(),
    ) {
        Text("Use This Token")
    }
}
