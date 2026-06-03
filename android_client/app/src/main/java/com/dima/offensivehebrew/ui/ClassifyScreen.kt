package com.dima.offensivehebrew.ui

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
import androidx.compose.runtime.collectAsState
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
import androidx.lifecycle.viewmodel.compose.viewModel
import coil.compose.AsyncImage
import com.dima.offensivehebrew.data.ClassifyImageResponse
import com.dima.offensivehebrew.data.ClassifyResponse
import com.dima.offensivehebrew.viewmodel.ClassifyViewModel
import com.dima.offensivehebrew.viewmodel.UiState
import java.io.File

enum class InputMode { Text, Image }

@Composable
fun ClassifyScreen(
    modifier: Modifier = Modifier,
    onOpenSettings: () -> Unit,
    vm: ClassifyViewModel = viewModel(),
) {
    val state by vm.state.collectAsState()
    val context = LocalContext.current

    var mode by rememberSaveable { mutableStateOf(InputMode.Text) }
    var text by rememberSaveable { mutableStateOf("") }
    var imageUri by rememberSaveable(stateSaver = UriSaver) { mutableStateOf<Uri?>(null) }
    // Holds the URI the camera intent is writing to between launch and result.
    // Not saveable: if the process dies mid-capture we won't get the photo back anyway.
    var pendingCaptureUri by remember { mutableStateOf<Uri?>(null) }

    val pickMedia = rememberLauncherForActivityResult(
        ActivityResultContracts.PickVisualMedia()
    ) { uri ->
        if (uri != null) imageUri = uri
    }

    val cameraLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.TakePicture()
    ) { success ->
        if (success) imageUri = pendingCaptureUri
    }

    val cameraPermissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        if (granted) {
            val uri = newCaptureUri(context)
            pendingCaptureUri = uri
            cameraLauncher.launch(uri)
        }
        // If denied, do nothing — the user can re-tap or pick from gallery.
        // Improving the denial UX (rationale + open-settings button) is Phase 2+.
    }

    Column(
        modifier = modifier
            .fillMaxSize()
            .padding(16.dp)
            .verticalScroll(rememberScrollState()),
    ) {
        Header(onOpenSettings = onOpenSettings)
        Spacer(Modifier.height(16.dp))

        SingleChoiceSegmentedButtonRow(modifier = Modifier.fillMaxWidth()) {
            SegmentedButton(
                selected = mode == InputMode.Text,
                onClick = {
                    if (mode != InputMode.Text) {
                        mode = InputMode.Text
                        vm.reset()
                    }
                },
                shape = SegmentedButtonDefaults.itemShape(index = 0, count = 2),
            ) { Text("Text") }
            SegmentedButton(
                selected = mode == InputMode.Image,
                onClick = {
                    if (mode != InputMode.Image) {
                        mode = InputMode.Image
                        vm.reset()
                    }
                },
                shape = SegmentedButtonDefaults.itemShape(index = 1, count = 2),
            ) { Text("Image") }
        }
        Spacer(Modifier.height(16.dp))

        when (mode) {
            InputMode.Text -> TextInputSection(
                text = text,
                onTextChange = { text = it },
                isLoading = state is UiState.Loading,
                onClassify = { vm.classifyText(text) },
                onClear = {
                    text = ""
                    vm.reset()
                },
                canClear = text.isNotEmpty() || state !is UiState.Idle,
            )
            InputMode.Image -> ImageInputSection(
                imageUri = imageUri,
                onPickImage = {
                    pickMedia.launch(
                        PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly)
                    )
                },
                onTakePhoto = {
                    val granted = ContextCompat.checkSelfPermission(
                        context, Manifest.permission.CAMERA
                    ) == PackageManager.PERMISSION_GRANTED
                    if (granted) {
                        val uri = newCaptureUri(context)
                        pendingCaptureUri = uri
                        cameraLauncher.launch(uri)
                    } else {
                        cameraPermissionLauncher.launch(Manifest.permission.CAMERA)
                    }
                },
                isLoading = state is UiState.Loading,
                onClassify = { imageUri?.let(vm::classifyImage) },
                onClear = {
                    imageUri = null
                    vm.reset()
                },
                canClear = imageUri != null || state !is UiState.Idle,
            )
        }

        Spacer(Modifier.height(20.dp))
        HorizontalDivider()
        Spacer(Modifier.height(20.dp))

        ResultArea(state = state, mode = mode)
    }
}

@Composable
private fun Header(onOpenSettings: () -> Unit) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceBetween,
    ) {
        Text(
            "Hebrew Offensive Classifier",
            style = MaterialTheme.typography.titleLarge,
            fontWeight = FontWeight.SemiBold,
        )
        IconButton(onClick = onOpenSettings) {
            Icon(Icons.Default.Settings, contentDescription = "Settings")
        }
    }
}

@Composable
private fun TextInputSection(
    text: String,
    onTextChange: (String) -> Unit,
    isLoading: Boolean,
    onClassify: () -> Unit,
    onClear: () -> Unit,
    canClear: Boolean,
) {
    CompositionLocalProvider(LocalLayoutDirection provides LayoutDirection.Rtl) {
        OutlinedTextField(
            value = text,
            onValueChange = onTextChange,
            label = { Text("טקסט בעברית") },
            placeholder = { Text("הכנס טקסט לסיווג…") },
            modifier = Modifier
                .fillMaxWidth()
                .height(160.dp),
            keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.None),
        )
    }
    Spacer(Modifier.height(12.dp))
    Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        Button(onClick = onClassify, enabled = !isLoading) {
            Text(if (isLoading) "Classifying…" else "Classify")
        }
        Button(onClick = onClear, enabled = !isLoading && canClear) { Text("Clear") }
    }
}

@Composable
private fun ImageInputSection(
    imageUri: Uri?,
    onPickImage: () -> Unit,
    onTakePhoto: () -> Unit,
    isLoading: Boolean,
    onClassify: () -> Unit,
    onClear: () -> Unit,
    canClear: Boolean,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        OutlinedButton(
            onClick = onPickImage,
            enabled = !isLoading,
            modifier = Modifier.weight(1f),
        ) {
            Icon(Icons.Default.PhotoLibrary, contentDescription = null)
            Spacer(Modifier.width(8.dp))
            Text("Pick")
        }
        OutlinedButton(
            onClick = onTakePhoto,
            enabled = !isLoading,
            modifier = Modifier.weight(1f),
        ) {
            Icon(Icons.Default.PhotoCamera, contentDescription = null)
            Spacer(Modifier.width(8.dp))
            Text("Camera")
        }
    }

    if (imageUri != null) {
        Spacer(Modifier.height(12.dp))
        AsyncImage(
            model = imageUri,
            contentDescription = "Selected image preview",
            modifier = Modifier
                .fillMaxWidth()
                .height(220.dp)
                .background(
                    MaterialTheme.colorScheme.surfaceVariant,
                    RoundedCornerShape(12.dp),
                ),
        )
    }

    Spacer(Modifier.height(12.dp))
    Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        Button(onClick = onClassify, enabled = !isLoading && imageUri != null) {
            Text(if (isLoading) "Classifying…" else "Classify")
        }
        Button(onClick = onClear, enabled = !isLoading && canClear) { Text("Clear") }
    }
}

@Composable
private fun ResultArea(state: UiState, mode: InputMode) {
    when (state) {
        UiState.Idle -> Text(
            if (mode == InputMode.Text)
                "Type Hebrew text above and tap Classify."
            else
                "Pick an image or take a photo, then tap Classify.",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        UiState.Loading -> Row(verticalAlignment = Alignment.CenterVertically) {
            CircularProgressIndicator()
            Spacer(Modifier.width(12.dp))
            Text("Talking to the model…")
        }
        is UiState.SuccessText -> ResultCardText(state.result)
        is UiState.SuccessImage -> ResultCardImage(state.result)
        is UiState.Error -> Text(
            "Error: ${state.message}",
            color = MaterialTheme.colorScheme.error,
        )
    }
}

@Composable
private fun ResultCardText(result: ClassifyResponse) {
    BaseResultCard(
        isOffensive = result.isOffensive,
        category = result.category,
        confidence = result.confidence,
        meta = "model=${result.model} • ${result.latencyMs} ms",
    )
}

@Composable
private fun ResultCardImage(result: ClassifyImageResponse) {
    Column {
        BaseResultCard(
            isOffensive = result.isOffensive,
            category = result.category,
            confidence = result.confidence,
            meta = "backend=${result.backend} • strategy=${result.strategy} • ${result.latencyMs} ms",
        )
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

@Composable
private fun BaseResultCard(
    isOffensive: Boolean,
    category: String,
    confidence: Double,
    meta: String,
) {
    val bg = if (isOffensive) Color(0xFFFFE5E5) else Color(0xFFE5F7E8)
    val fg = if (isOffensive) Color(0xFFB00020) else Color(0xFF1B5E20)
    val label = if (isOffensive) "OFFENSIVE" else "NOT OFFENSIVE"
    val pct = (confidence * 100).toInt()

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .background(bg, RoundedCornerShape(12.dp))
            .padding(16.dp),
    ) {
        Text(
            label,
            color = fg,
            fontWeight = FontWeight.Bold,
            style = MaterialTheme.typography.titleMedium,
        )
        Spacer(Modifier.height(6.dp))
        Text("Category: $category")
        Text("Confidence: ${pct}%")
        Spacer(Modifier.height(8.dp))
        Text(
            meta,
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

private fun newCaptureUri(context: Context): Uri {
    val dir = File(context.filesDir, "captures").apply { mkdirs() }
    val file = File(dir, "IMG_${System.currentTimeMillis()}.jpg")
    return FileProvider.getUriForFile(
        context,
        "${context.packageName}.fileprovider",
        file,
    )
}

// Lets rememberSaveable survive config changes for a Uri (which isn't directly saveable).
private val UriSaver = Saver<Uri?, String>(
    save = { it?.toString().orEmpty() },
    restore = { if (it.isEmpty()) null else Uri.parse(it) },
)
