package com.dima.offensivehebrew.viewmodel

import android.app.Application
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.net.Uri
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.dima.offensivehebrew.data.ApiFactory
import com.dima.offensivehebrew.data.ClassifyImageResponse
import com.dima.offensivehebrew.data.ClassifyRequest
import com.dima.offensivehebrew.data.ClassifyResponse
import com.dima.offensivehebrew.data.SettingsRepository
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

/**
 * UI state for the classify screen. `Success` is split by input modality
 * because the image response carries extra diagnostic fields
 * (extracted_text, backend, strategy) the text response doesn't have.
 */
sealed interface UiState {
    data object Idle : UiState
    data object Loading : UiState
    data class SuccessText(val result: ClassifyResponse) : UiState
    data class SuccessImage(val result: ClassifyImageResponse) : UiState
    data class Error(val message: String) : UiState
}

class ClassifyViewModel(app: Application) : AndroidViewModel(app) {
    private val settings = SettingsRepository(app)

    private val _state = MutableStateFlow<UiState>(UiState.Idle)
    val state: StateFlow<UiState> = _state

    fun classifyText(text: String) {
        if (text.isBlank()) {
            _state.value = UiState.Error("Enter Hebrew text to classify.")
            return
        }
        _state.value = UiState.Loading
        viewModelScope.launch {
            val url = settings.serverUrl.first()
            try {
                val api = ApiFactory.create(url)
                val result = api.classify(ClassifyRequest(text))
                _state.value = UiState.SuccessText(result)
            } catch (t: Throwable) {
                _state.value = UiState.Error(humanize(t, url))
            }
        }
    }

    fun classifyImage(uri: Uri) {
        _state.value = UiState.Loading
        viewModelScope.launch {
            val url = settings.serverUrl.first()
            try {
                val bytes = loadAndCompress(uri)
                val part = MultipartBody.Part.createFormData(
                    name = "image",
                    filename = "upload.jpg",
                    body = bytes.toRequestBody("image/jpeg".toMediaType()),
                )
                val api = ApiFactory.create(url)
                val result = api.classifyImage(part)
                _state.value = UiState.SuccessImage(result)
            } catch (t: Throwable) {
                _state.value = UiState.Error(humanize(t, url))
            }
        }
    }

    fun reset() {
        _state.value = UiState.Idle
    }

    /**
     * Decode the image at [uri], scale so its longest edge ≤ [maxEdge], and
     * re-encode as JPEG at [quality]. Returns the encoded bytes ready to be
     * wrapped in a MultipartBody.Part.
     *
     * Why compress on-device: 4K phone photos are 3–8 MB. Sending them raw
     * over a LAN is slow and the LLM doesn't benefit from the extra pixels.
     * 1600 px / quality 80 typically yields ≤ 500 KB with no visible loss
     * for OCR/vision purposes.
     */
    private suspend fun loadAndCompress(
        uri: Uri,
        maxEdge: Int = 1600,
        quality: Int = 80,
    ): ByteArray = withContext(Dispatchers.IO) {
        val resolver = getApplication<Application>().contentResolver
        val original = resolver.openInputStream(uri).use { input ->
            BitmapFactory.decodeStream(input)
                ?: error("Could not decode image at $uri")
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
            "Server timed out. Ollama may be loading the model — try again."
        is java.net.UnknownHostException ->
            "Unknown host in $url. Check the server URL in Settings."
        else -> t.message ?: t.javaClass.simpleName
    }
}
