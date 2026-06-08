package com.shomer.client.parent

import android.util.Log
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.shomer.client.data.ChildDigestOut
import com.shomer.client.data.ParentApi
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import javax.inject.Inject

data class DigestUiState(
    val selectedDate: String = "",
    val digests: List<ChildDigestOut> = emptyList(),
    val isLoading: Boolean = false,
    val error: String? = null,
    val is404: Boolean = false,  // true when server returns 404 (no digests for that date)
)

/**
 * ViewModel for DigestScreen.
 *
 * Loads GET /v1/parent/digests/{date} for the selected date.
 * Default date is today. The UI provides a date picker to navigate.
 *
 * 404 from the server (no digests built for that date yet) is treated as an
 * informational state (is404=true), not an error requiring retry.
 */
@HiltViewModel
class DigestViewModel @Inject constructor(
    private val parentApi: ParentApi,
) : ViewModel() {

    private val _state = MutableStateFlow(DigestUiState())
    val state: StateFlow<DigestUiState> = _state

    init {
        _state.update { it.copy(selectedDate = todayDate()) }
        loadDigests()
    }

    fun setDate(date: String) {
        _state.update { it.copy(selectedDate = date) }
        loadDigests()
    }

    fun loadDigests() {
        val date = _state.value.selectedDate
        _state.update { it.copy(isLoading = true, error = null, is404 = false) }
        viewModelScope.launch {
            try {
                val digests = parentApi.getDigests(date)
                _state.update { it.copy(isLoading = false, digests = digests) }
                Log.d(TAG, "Loaded ${digests.size} digest(s) for $date")
            } catch (e: retrofit2.HttpException) {
                if (e.code() == 404) {
                    _state.update { it.copy(isLoading = false, digests = emptyList(), is404 = true) }
                } else {
                    val msg = "Server error: ${e.code()}"
                    _state.update { it.copy(isLoading = false, error = msg) }
                    Log.e(TAG, "getDigests HTTP error: ${e.code()}", e)
                }
            } catch (e: Exception) {
                _state.update { it.copy(isLoading = false, error = "Cannot reach server: ${e.message}") }
                Log.e(TAG, "getDigests network error", e)
            }
        }
    }

    companion object {
        private const val TAG = "DigestViewModel"

        private val dateFormat = SimpleDateFormat("yyyy-MM-dd", Locale.getDefault())
        fun todayDate(): String = dateFormat.format(Date())
    }
}
