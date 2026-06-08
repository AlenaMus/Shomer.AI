package com.shomer.client.parent

import android.util.Log
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.shomer.client.data.ParentApi
import com.shomer.client.data.ParentRegisterRequest
import com.shomer.client.data.TokenStore
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import javax.inject.Inject

data class ParentAuthUiState(
    val displayName: String = "",
    val existingToken: String = "",
    val isLoading: Boolean = false,
    val error: String? = null,
    val authDone: Boolean = false,
    // Controls which tab: true = create new account, false = paste existing token
    val isCreateMode: Boolean = true,
)

/**
 * ViewModel for ParentAuthScreen.
 *
 * Two paths:
 *   Create new account → POST /v1/parent/register {display_name}
 *     → store parent_token + role=parent in TokenStore → authDone=true
 *
 *   Use existing token → user pastes the opaque parent_token directly
 *     → store it + role=parent in TokenStore (no server call; token validity
 *       is verified lazily on the first authenticated request to /v1/parent/alerts)
 */
@HiltViewModel
class ParentAuthViewModel @Inject constructor(
    private val parentApi: ParentApi,
    private val tokenStore: TokenStore,
) : ViewModel() {

    private val _state = MutableStateFlow(ParentAuthUiState())
    val state: StateFlow<ParentAuthUiState> = _state

    fun setDisplayName(name: String) =
        _state.update { it.copy(displayName = name, error = null) }

    fun setExistingToken(token: String) =
        _state.update { it.copy(existingToken = token, error = null) }

    fun setCreateMode(isCreate: Boolean) =
        _state.update { it.copy(isCreateMode = isCreate, error = null) }

    fun createAccount() {
        _state.update { it.copy(isLoading = true, error = null) }
        viewModelScope.launch {
            try {
                val response = parentApi.registerParent(
                    ParentRegisterRequest(displayName = _state.value.displayName.trim()),
                )
                // Store the parent token as the device token with role=parent.
                // AuthInterceptor will pick this up automatically for all /v1/ calls.
                tokenStore.saveParentToken(
                    parentToken = response.parentToken,
                    parentId = response.parentId,
                )
                Log.i(TAG, "Parent registered: parent_id=${response.parentId}")
                _state.update { it.copy(isLoading = false, authDone = true) }
            } catch (e: retrofit2.HttpException) {
                val msg = "Server error: ${e.code()} ${e.message()}"
                _state.update { it.copy(isLoading = false, error = msg) }
                Log.e(TAG, "registerParent HTTP error", e)
            } catch (e: Exception) {
                _state.update { it.copy(isLoading = false, error = "Cannot reach server: ${e.message}") }
                Log.e(TAG, "registerParent network error", e)
            }
        }
    }

    fun useExistingToken() {
        val token = _state.value.existingToken.trim()
        if (token.length < 8) {
            _state.update { it.copy(error = "Token is too short — paste the full parent token") }
            return
        }
        // Store directly; role=parent. Token validity is verified lazily.
        tokenStore.saveParentToken(parentToken = token, parentId = "")
        _state.update { it.copy(authDone = true) }
        Log.i(TAG, "Parent token stored directly (length=${token.length})")
    }

    companion object {
        private const val TAG = "ParentAuthViewModel"
    }
}
