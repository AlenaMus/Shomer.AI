package com.shomer.client.ui

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.PhotoCamera
import androidx.compose.material.icons.filled.PhotoLibrary
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.Saver
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.core.content.FileProvider
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import coil.compose.AsyncImage
import com.shomer.client.data.ClassifyImageResponse
import com.shomer.client.data.ClassifyResponse
import com.shomer.client.viewmodel.ClassifyUiState
import com.shomer.client.viewmodel.ClassifyViewModel
import java.io.File

enum class InputMode { Text, Image }

/**
 * Debug classify screen — migrated from the POC. Available in both poc and client
 * flavors as a server connectivity / classification test aid.
 *
 * Kept functionally identical to the POC version; only the package imports changed.
 * Uses the new ClassifyViewModel (Hilt-injected) with SettingsRepository.
 */
@Composable
fun ClassifyScreen(
    modifier: Modifier = Modifier,
    onOpenSettings: () -> Unit,
    vm: ClassifyViewModel = hiltViewModel(),
) {
    val state by vm.state.collectAsStateWithLifecycle()
    val context = LocalContext.current

    var mode by rememberSaveable { mutableStateOf(InputMode.Text) }
    var text by rememberSaveable { mutableStateOf("") }
    var imageUri by rememberSaveable(stateSaver = UriSaver) { mutableStateOf<Uri?>(null) }
    var pendingCaptureUri by remember { mutableStateOf<Uri?>(null) }

    val pickMedia = rememberLauncherForActivityResult(ActivityResultContracts.PickVisualMedia()) { uri ->
        if (uri != null) imageUri = uri
    }

    val cameraLauncher = rememberLauncherForActivityResult(ActivityResultContracts.TakePicture()) { success ->
        if (success) imageUri = pendingCaptureUri
    }

    val cameraPermissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { granted ->
        if (granted) {
            val uri = newCaptureUri(context)
            pendingCaptureUri = uri
            cameraLauncher.launch(uri)
        }
    }

    Column(
        modifier = modifier
            .fillMaxSize()
            .padding(16.dp)
            .verticalScroll(rememberScrollState()),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Text(
                "Debug: Classify",
                style = MaterialTheme.typography.titleLarge,
                fontWeight = FontWeight.SemiBold,
            )
            IconButton(onClick = onOpenSettings) {
                Icon(Icons.Default.Settings, contentDescription = "Settings")
            }
        }
        Spacer(Modifier.height(16.dp))

        SingleChoiceSegmentedButtonRow(modifier = Modifier.fillMaxWidth()) {
            SegmentedButton(
                selected = mode == InputMode.Text,
                onClick = { if (mode != InputMode.Text) { mode = InputMode.Text; vm.reset() } },
                shape = SegmentedButtonDefaults.itemShape(index = 0, count = 2),
            ) { Text("Text") }
            SegmentedButton(
                selected = mode == InputMode.Image,
                onClick = { if (mode != InputMode.Image) { mode = InputMode.Image; vm.reset() } },
                shape = SegmentedButtonDefaults.itemShape(index = 1, count = 2),
            ) { Text("Image") }
        }
        Spacer(Modifier.height(16.dp))

        when (mode) {
            InputMode.Text -> {
                CompositionLocalProvider(LocalLayoutDirection provides LayoutDirection.Rtl) {
                    OutlinedTextField(
                        value = text,
                        onValueChange = { text = it },
                        label = { Text("טקסט בעברית") },
                        placeholder = { Text("הכנס טקסט לסיווג…") },
                        modifier = Modifier.fillMaxWidth().height(160.dp),
                        keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.None),
                    )
                }
                Spacer(Modifier.height(12.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    Button(onClick = { vm.classifyText(text) }, enabled = state !is ClassifyUiState.Loading) {
                        Text(if (state is ClassifyUiState.Loading) "Classifying…" else "Classify")
                    }
                    Button(onClick = { text = ""; vm.reset() }) { Text("Clear") }
                }
            }
            InputMode.Image -> {
                Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    OutlinedButton(
                        onClick = { pickMedia.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)) },
                        modifier = Modifier.weight(1f),
                    ) {
                        Icon(Icons.Default.PhotoLibrary, null)
                        Spacer(Modifier.width(8.dp))
                        Text("Pick")
                    }
                    OutlinedButton(
                        onClick = {
                            val granted = ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED
                            if (granted) {
                                val uri = newCaptureUri(context)
                                pendingCaptureUri = uri
                                cameraLauncher.launch(uri)
                            } else {
                                cameraPermissionLauncher.launch(Manifest.permission.CAMERA)
                            }
                        },
                        modifier = Modifier.weight(1f),
                    ) {
                        Icon(Icons.Default.PhotoCamera, null)
                        Spacer(Modifier.width(8.dp))
                        Text("Camera")
                    }
                }
                imageUri?.let { uri ->
                    Spacer(Modifier.height(12.dp))
                    AsyncImage(
                        model = uri,
                        contentDescription = "Selected image",
                        modifier = Modifier.fillMaxWidth().height(220.dp)
                            .background(MaterialTheme.colorScheme.surfaceVariant, RoundedCornerShape(12.dp)),
                    )
                }
                Spacer(Modifier.height(12.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    Button(
                        onClick = { imageUri?.let(vm::classifyImage) },
                        enabled = state !is ClassifyUiState.Loading && imageUri != null,
                    ) { Text(if (state is ClassifyUiState.Loading) "Classifying…" else "Classify") }
                    Button(onClick = { imageUri = null; vm.reset() }) { Text("Clear") }
                }
            }
        }

        Spacer(Modifier.height(20.dp))
        HorizontalDivider()
        Spacer(Modifier.height(20.dp))

        when (val s = state) {
            ClassifyUiState.Idle -> Text(
                if (mode == InputMode.Text) "Type Hebrew text above and tap Classify."
                else "Pick an image or take a photo, then tap Classify.",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            ClassifyUiState.Loading -> Row(verticalAlignment = Alignment.CenterVertically) {
                CircularProgressIndicator()
                Spacer(Modifier.width(12.dp))
                Text("Talking to the model…")
            }
            is ClassifyUiState.SuccessText -> ResultCard(s.result)
            is ClassifyUiState.SuccessImage -> ResultCardImage(s.result)
            is ClassifyUiState.Error -> Text(
                "Error: ${s.message}",
                color = MaterialTheme.colorScheme.error,
            )
        }
    }
}

@Composable
private fun ResultCard(result: ClassifyResponse) {
    val bg = if (result.isOffensive) Color(0xFFFFE5E5) else Color(0xFFE5F7E8)
    val fg = if (result.isOffensive) Color(0xFFB00020) else Color(0xFF1B5E20)
    val pct = (result.confidence * 100).toInt()
    Column(
        modifier = Modifier.fillMaxWidth().background(bg, RoundedCornerShape(12.dp)).padding(16.dp),
    ) {
        Text(
            if (result.isOffensive) "OFFENSIVE" else "NOT OFFENSIVE",
            color = fg,
            fontWeight = FontWeight.Bold,
            style = MaterialTheme.typography.titleMedium,
        )
        Spacer(Modifier.height(6.dp))
        Text("Category: ${result.category}")
        Text("Confidence: $pct%")
        Spacer(Modifier.height(8.dp))
        Text(
            "model=${result.model} • ${result.latencyMs} ms",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun ResultCardImage(result: ClassifyImageResponse) {
    Column {
        val bg = if (result.isOffensive) Color(0xFFFFE5E5) else Color(0xFFE5F7E8)
        val fg = if (result.isOffensive) Color(0xFFB00020) else Color(0xFF1B5E20)
        val pct = (result.confidence * 100).toInt()
        Column(modifier = Modifier.fillMaxWidth().background(bg, RoundedCornerShape(12.dp)).padding(16.dp)) {
            Text(
                if (result.isOffensive) "OFFENSIVE" else "NOT OFFENSIVE",
                color = fg, fontWeight = FontWeight.Bold, style = MaterialTheme.typography.titleMedium,
            )
            Spacer(Modifier.height(6.dp))
            Text("Category: ${result.category}")
            Text("Confidence: $pct%")
            Spacer(Modifier.height(8.dp))
            Text(
                "backend=${result.backend} • strategy=${result.strategy} • ${result.latencyMs} ms",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        if (result.extractedText.isNotBlank()) {
            Spacer(Modifier.height(8.dp))
            Text(
                "Extracted text: ${result.extractedText}",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

private fun newCaptureUri(context: Context): Uri {
    val dir = File(context.filesDir, "captures").apply { mkdirs() }
    val file = File(dir, "IMG_${System.currentTimeMillis()}.jpg")
    return FileProvider.getUriForFile(context, "${context.packageName}.fileprovider", file)
}

private val UriSaver = Saver<Uri?, String>(
    save = { it?.toString().orEmpty() },
    restore = { if (it.isEmpty()) null else Uri.parse(it) },
)
