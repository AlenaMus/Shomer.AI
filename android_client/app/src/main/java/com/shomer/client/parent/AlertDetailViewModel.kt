package com.shomer.client.parent

import android.util.Log
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.shomer.client.data.FlaggedEventOut
import com.shomer.client.data.ParentApi
import com.shomer.client.data.ReactRequest
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

data class AlertDetailUiState(
    val alert: FlaggedEventOut? = null,
    val isLoading: Boolean = false,
    val isReacting: Boolean = false,
    val error: String? = null,
    val reactionError: String? = null,
    val reactionDone: Boolean = false,  // true after react succeeds → trigger pop
)

/**
 * ViewModel for AlertDetailScreen.
 *
 * Loads a single flagged event via GET /v1/parent/alerts/{flag_id}.
 * Dispatches parent reactions via POST /v1/parent/alerts/{flag_id}/react.
 *
 * Actions:
 *   acknowledge()              → ReactRequest(action="acknowledge")
 *   labelOffensive()           → ReactRequest(action="label", label="offensive")
 *   labelNotOffensive()        → ReactRequest(action="label", label="not_offensive")
 *   setSeverity(severity)      → ReactRequest(action="severity", severity=severity)
 */
@HiltViewModel
class AlertDetailViewModel @Inject constructor(
    savedStateHandle: SavedStateHandle,
    private val parentApi: ParentApi,
) : ViewModel() {

    // Navigation arg — injected by SavedStateHandle from the nav route "alert_detail/{flag_id}"
    private val flagId: String = checkNotNull(savedStateHandle["flag_id"])

    private val _state = MutableStateFlow(AlertDetailUiState())
    val state: StateFlow<AlertDetailUiState> = _state

    init {
        loadAlert()
    }

    fun loadAlert() {
        _state.update { it.copy(isLoading = true, error = null) }
        viewModelScope.launch {
            try {
                val alert = parentApi.getAlert(flagId)
                _state.update { it.copy(isLoading = false, alert = alert) }
            } catch (e: retrofit2.HttpException) {
                val msg = if (e.code() == 404) "Alert not found" else "Server error: ${e.code()}"
                _state.update { it.copy(isLoading = false, error = msg) }
                Log.e(TAG, "getAlert HTTP error: ${e.code()}", e)
            } catch (e: Exception) {
                _state.update { it.copy(isLoading = false, error = "Cannot reach server: ${e.message}") }
                Log.e(TAG, "getAlert network error", e)
            }
        }
    }

    fun acknowledge() = sendReact(ReactRequest(action = "acknowledge"))

    fun labelOffensive() = sendReact(ReactRequest(action = "label", label = "offensive"))

    fun labelNotOffensive() = sendReact(ReactRequest(action = "label", label = "not_offensive"))

    fun setSeverity(severity: String) = sendReact(ReactRequest(action = "severity", severity = severity))

    private fun sendReact(body: ReactRequest) {
        _state.update { it.copy(isReacting = true, reactionError = null) }
        viewModelScope.launch {
            try {
                val updated = parentApi.react(flagId, body)
                _state.update { it.copy(isReacting = false, alert = updated, reactionDone = true) }
                Log.i(TAG, "react success: action=${body.action} flagId=$flagId newStatus=${updated.status}")
            } catch (e: retrofit2.HttpException) {
                val msg = when (e.code()) {
                    422 -> "Invalid action — check label/severity field"
                    404 -> "Alert not found"
                    else -> "Server error: ${e.code()}"
                }
                _state.update { it.copy(isReacting = false, reactionError = msg) }
                Log.e(TAG, "react HTTP error: ${e.code()}", e)
            } catch (e: Exception) {
                _state.update { it.copy(isReacting = false, reactionError = "Cannot reach server: ${e.message}") }
                Log.e(TAG, "react network error", e)
            }
        }
    }

    companion object {
        private const val TAG = "AlertDetailViewModel"
    }
}
