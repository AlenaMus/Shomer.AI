package com.shomer.client.parent

import android.util.Log
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.shomer.client.data.ChildInfo
import com.shomer.client.data.FlaggedEventOut
import com.shomer.client.data.ParentApi
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

/** Filter chips shown above the alert list. */
enum class AlertFilter(val label: String, val serverStatus: String?) {
    ALL("All", null),
    REVIEW("Needs Review", "review_needed"),
    ALERTED("Alerted", "alerted"),
    ACKNOWLEDGED("Done", null),  // includes acknowledged + labeled; use include_acked=true
}

data class AlertListUiState(
    val alerts: List<FlaggedEventOut> = emptyList(),
    val children: List<ChildInfo> = emptyList(),
    val selectedChildId: String? = null,
    val activeFilter: AlertFilter = AlertFilter.REVIEW,  // default: review_needed queue
    val isLoading: Boolean = false,
    val error: String? = null,
)

/**
 * ViewModel for AlertListScreen.
 *
 * Loads alerts via GET /v1/parent/alerts with poll-on-refresh semantics
 * (no FCM required for the review UI to function).
 *
 * Also loads children via GET /v1/parent/children for the optional child filter.
 *
 * Polling: the UI triggers refreshAlerts() manually (pull-to-refresh) + on resume.
 * Automatic polling is NOT wired here — the parent opens the app to review,
 * FCM is the push mechanism (additive, not required).
 */
@HiltViewModel
class AlertListViewModel @Inject constructor(
    private val parentApi: ParentApi,
) : ViewModel() {

    private val _state = MutableStateFlow(AlertListUiState())
    val state: StateFlow<AlertListUiState> = _state

    init {
        loadChildren()
        refreshAlerts()
    }

    fun setFilter(filter: AlertFilter) {
        _state.update { it.copy(activeFilter = filter) }
        refreshAlerts()
    }

    fun setChildFilter(childId: String?) {
        _state.update { it.copy(selectedChildId = childId) }
        refreshAlerts()
    }

    fun refreshAlerts() {
        val filter = _state.value.activeFilter
        val childId = _state.value.selectedChildId

        _state.update { it.copy(isLoading = true, error = null) }
        viewModelScope.launch {
            try {
                val includeAcked = filter == AlertFilter.ACKNOWLEDGED
                val statusParam = if (filter == AlertFilter.ACKNOWLEDGED) null else filter.serverStatus
                val alerts = parentApi.listAlerts(
                    childId = childId,
                    status = statusParam,
                    includeAcked = includeAcked,
                    limit = 100,
                )
                _state.update { it.copy(isLoading = false, alerts = alerts, error = null) }
                Log.d(TAG, "Loaded ${alerts.size} alerts (filter=${filter.name})")
            } catch (e: retrofit2.HttpException) {
                val msg = if (e.code() == 401 || e.code() == 403) {
                    "Authentication failed — check your parent token in settings"
                } else {
                    "Server error: ${e.code()}"
                }
                _state.update { it.copy(isLoading = false, error = msg) }
                Log.e(TAG, "listAlerts HTTP error: ${e.code()}", e)
            } catch (e: Exception) {
                _state.update { it.copy(isLoading = false, error = "Cannot reach server: ${e.message}") }
                Log.e(TAG, "listAlerts network error", e)
            }
        }
    }

    private fun loadChildren() {
        viewModelScope.launch {
            try {
                val children = parentApi.listChildren()
                _state.update { it.copy(children = children) }
            } catch (e: Exception) {
                // Non-fatal: child filter chips just won't appear
                Log.w(TAG, "listChildren failed: ${e.message}")
            }
        }
    }

    companion object {
        private const val TAG = "AlertListViewModel"
    }
}
