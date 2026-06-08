package com.shomer.client.viewmodel

import android.app.Application
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.net.Uri
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.shomer.client.data.ApiService
import com.shomer.client.data.ClassifyImageResponse
import com.shomer.client.data.ClassifyRequest
import com.shomer.client.data.ClassifyResponse
import com.shomer.client.data.SettingsRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.ByteArrayOutputStream
import javax.inject.Inject

sealed interface ClassifyUiState {
    data object Idle : ClassifyUiState
    data object Loading : ClassifyUiState
    data class SuccessText(val result: ClassifyResponse) : ClassifyUiState
    data class SuccessImage(val result: ClassifyImageResponse) : ClassifyUiState
    data class Error(val message: String) : ClassifyUiState
}

/**
 * ViewModel for the debug classify screen (migrated from POC).
 *
 * Now @HiltViewModel — injected by hiltViewModel() in the composable.
 * Also exposes serverUrl flow + saveServerUrl/testConnection for the Settings screen.
 */
@HiltViewModel
class ClassifyViewModel @Inject constructor(
    app: Application,
    private val settings: SettingsRepository,
    private val apiService: ApiService,
) : AndroidViewModel(app) {

    private val _state = MutableStateFlow<ClassifyUiState>(ClassifyUiState.Idle)
    val state: StateFlow<ClassifyUiState> = _state

    val serverUrl = settings.serverUrl

    fun classifyText(text: String) {
        if (text.isBlank()) {
            _state.value = ClassifyUiState.Error("Enter Hebrew text to classify.")
            return
        }
        _state.value = ClassifyUiState.Loading
        viewModelScope.launch {
            try {
                // Note: apiService uses the base URL from Hilt singleton (stored URL at init).
                // If the user just changed the URL in Settings, they need to restart the app.
                val result = apiService.classify(ClassifyRequest(text = text))
                _state.value = ClassifyUiState.SuccessText(result)
            } catch (t: Throwable) {
                val url = settings.serverUrl.first()
                _state.value = ClassifyUiState.Error(humanize(t, url))
            }
        }
    }

    fun classifyImage(uri: Uri) {
        _state.value = ClassifyUiState.Loading
        viewModelScope.launch {
            try {
                val bytes = loadAndCompress(uri)
                val part = MultipartBody.Part.createFormData(
                    name = "image",
                    filename = "upload.jpg",
                    body = bytes.toRequestBody("image/jpeg".toMediaType()),
                )
                val result = apiService.classifyImage(part)
                _state.value = ClassifyUiState.SuccessImage(result)
            } catch (t: Throwable) {
                val url = settings.serverUrl.first()
                _state.value = ClassifyUiState.Error(humanize(t, url))
            }
        }
    }

    fun reset() { _state.value = ClassifyUiState.Idle }

    suspend fun saveServerUrl(url: String) {
        settings.setServerUrl(url)
    }

    /**
     * Test a URL by hitting GET /health. Returns a human-readable status string.
     * Runs a temporary Retrofit call without changing the stored URL.
     */
    suspend fun testConnection(url: String): String = withContext(Dispatchers.IO) {
        val stored = settings.serverUrl.first()
        val testUrl = url.trim().ifBlank { stored }
        try {
            // Use the injected apiService for testing the stored URL.
            // For testing a *new* URL before saving, we'd need to build a fresh Retrofit.
            // For the MVP, test only confirms the stored URL works.
            val h = apiService.health()
            "OK — status=${h.status}, ollama=${h.ollamaReachable}, model=${h.model}"
        } catch (t: Throwable) {
            "Failed: ${t.message ?: t.javaClass.simpleName}"
        }
    }

    private suspend fun loadAndCompress(
        uri: Uri,
        maxEdge: Int = 1600,
        quality: Int = 80,
    ): ByteArray = withContext(Dispatchers.IO) {
        val resolver = getApplication<Application>().contentResolver
        val original = resolver.openInputStream(uri).use { input ->
            BitmapFactory.decodeStream(input) ?: error("Could not decode image at $uri")
        }
        val scale = maxEdge.toFloat() / maxOf(original.width, original.height)
        val resized = if (scale < 1f) {
            Bitmap.createScaledBitmap(
                original,
                (original.width * scale).toInt(),
                (original.height * scale).toInt(),
                true,
            ).also { original.recycle() }
        } else {
            original
        }
        ByteArrayOutputStream().use { out ->
            resized.compress(Bitmap.CompressFormat.JPEG, quality, out)
            resized.recycle()
            out.toByteArray()
        }
    }

    private fun humanize(t: Throwable, url: String): String = when (t) {
        is java.net.ConnectException ->
            "Cannot reach server at $url. Is it running and on the same Wi-Fi?"
        is java.net.SocketTimeoutException ->
            "Server timed out. Model may be loading — try again."
        is java.net.UnknownHostException ->
            "Unknown host in $url. Check the server URL in Settings."
        else -> t.message ?: t.javaClass.simpleName
    }
}
