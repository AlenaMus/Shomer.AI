package com.shomer.client.parent

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp

/**
 * Top-level role chooser — shown once on first launch (no role stored in TokenStore).
 *
 * The user either installs this app on:
 *   (a) the child's device → "This is my child's device" → child onboarding flow
 *   (b) the parent's phone → "I am a Parent" → parent auth flow
 *
 * This choice sets the routing intent; the actual role is written to TokenStore after
 * the respective auth flow completes (pairing for child, register/token for parent).
 *
 * RTL: Hebrew text content uses TextAlign.Start (auto-mirrored by supportsRtl="true"
 * in Manifest). Layout direction follows the device locale.
 */
@Composable
fun RoleChooserScreen(
    onChooseParent: () -> Unit,
    onChooseChild: () -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(32.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Text(
            text = "Shomer.AI",
            style = MaterialTheme.typography.displaySmall,
            fontWeight = FontWeight.Bold,
            color = MaterialTheme.colorScheme.primary,
            textAlign = TextAlign.Center,
        )

        Spacer(Modifier.height(8.dp))

        Text(
            text = "Child Safety Monitoring",
            style = MaterialTheme.typography.titleMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            textAlign = TextAlign.Center,
        )

        Spacer(Modifier.height(48.dp))

        Text(
            text = "Who is setting up this device?",
            style = MaterialTheme.typography.headlineSmall,
            fontWeight = FontWeight.SemiBold,
            textAlign = TextAlign.Center,
        )

        Spacer(Modifier.height(8.dp))

        Text(
            text = "Install on the parent's phone to receive alerts.\nInstall on the child's device to monitor messages.",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            textAlign = TextAlign.Center,
        )

        Spacer(Modifier.height(40.dp))

        Button(
            onClick = onChooseParent,
            modifier = Modifier
                .fillMaxWidth()
                .height(56.dp),
        ) {
            Text(
                text = "I am a Parent",
                style = MaterialTheme.typography.titleMedium,
            )
        }

        Spacer(Modifier.height(16.dp))

        OutlinedButton(
            onClick = onChooseChild,
            modifier = Modifier
                .fillMaxWidth()
                .height(56.dp),
        ) {
            Text(
                text = "This is my child's device",
                style = MaterialTheme.typography.titleMedium,
            )
        }

        Spacer(Modifier.height(24.dp))

        Text(
            text = "You can only install Shomer.AI once per device.\nChoose the role that matches this phone.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            textAlign = TextAlign.Center,
        )
    }
}
