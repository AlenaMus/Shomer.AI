package com.shomer.client.onboarding

import android.app.Application
import android.content.ComponentName
import android.content.Context
import android.os.Build
import android.provider.Settings
import android.util.Log
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.shomer.client.capture.CaptureForegroundService
import com.shomer.client.data.PairingApi
import com.shomer.client.data.PairRequest
import com.shomer.client.data.SettingsRepository
import com.shomer.client.data.TokenStore
import com.shomer.client.monitor.MonitorActivityLog
import com.shomer.client.monitor.MonitorUploader
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import java.util.concurrent.TimeUnit
import javax.inject.Inject

data class OnboardingUiState(
    // Consent step
    val guardianChecked: Boolean = false,
    val childChecked: Boolean = false,
    val consentDone: Boolean = false,

    // Pairing step
    val pairingCode: String = "",
    val isPairing: Boolean = false,
    val pairingError: String? = null,
    val pairingDone: Boolean = false,
    val pairedChildId: String? = null,

    // Permission step
    val notificationPermissionGranted: Boolean = false,
    val accessibilityEnabled: Boolean = false,
    val batteryOptimizationExempt: Boolean = false,
)

@HiltViewModel
class OnboardingViewModel @Inject constructor(
    app: Application,
    private val pairingApi: PairingApi,
    private val tokenStore: TokenStore,
    private val settings: SettingsRepository,
    private val activityLog: MonitorActivityLog,
) : AndroidViewModel(app) {

    private val _state = MutableStateFlow(OnboardingUiState())
    val state: StateFlow<OnboardingUiState> = _state

    /** Device-side log of recent captured messages + their server-upload status. */
    val monitorActivity: StateFlow<List<MonitorActivityLog.Entry>> = activityLog.entries

    /** Live server URL (for the connection editor on the pairing screen). */
    val serverUrl: StateFlow<String> = settings.serverUrl
        .stateIn(viewModelScope, SharingStarted.Eagerly, SettingsRepository.DEFAULT_SERVER_URL)

    /** Persist a new server URL. Takes effect immediately (BaseUrlInterceptor reads it live). */
    fun saveServerUrl(url: String) {
        viewModelScope.launch { settings.setServerUrl(url.trim()) }
    }

    /**
     * Test reachability of [rawUrl] by hitting its /health endpoint with a short
     * timeout. Returns a human-readable status. Does not change the stored URL.
     */
    suspend fun testConnection(rawUrl: String): String = withContext(Dispatchers.IO) {
        val base = rawUrl.trim().let { if (it.endsWith("/")) it else "$it/" }
        val client = OkHttpClient.Builder()
            .connectTimeout(5, TimeUnit.SECONDS)
            .readTimeout(5, TimeUnit.SECONDS)
            .build()
        try {
            val req = Request.Builder().url("${base}health").get().build()
            client.newCall(req).execute().use { resp ->
                if (resp.isSuccessful) "✓ Connected — server is reachable (HTTP ${resp.code})"
                else "Reached $base but got HTTP ${resp.code}"
            }
        } catch (e: IllegalArgumentException) {
            "Invalid URL: ${e.message}"
        } catch (e: Exception) {
            "✗ Cannot reach $base — ${e.message ?: e.javaClass.simpleName}"
        }
    }

    init {
        // If already consented + paired, skip to the status screen (handled in MainActivity).
        _state.update {
            it.copy(
                consentDone = tokenStore.hasConsented(),
                pairingDone = tokenStore.isPaired(),
                pairedChildId = tokenStore.getChildId(),
            )
        }
        refreshPermissionStatus()
    }

    // -------------------------------------------------------------------------
    // Consent step
    // -------------------------------------------------------------------------

    fun setGuardianChecked(checked: Boolean) =
        _state.update { it.copy(guardianChecked = checked) }

    fun setChildChecked(checked: Boolean) =
        _state.update { it.copy(childChecked = checked) }

    fun confirmConsent() {
        if (_state.value.guardianChecked && _state.value.childChecked) {
            tokenStore.setConsented(true)
            _state.update { it.copy(consentDone = true) }
        }
    }

    // -------------------------------------------------------------------------
    // Pairing step
    // -------------------------------------------------------------------------

    fun setPairingCode(code: String) = _state.update { it.copy(pairingCode = code, pairingError = null) }

    fun pair() {
        val code = _state.value.pairingCode.trim()
        if (code.length !in 6..8 || !code.all { it.isDigit() }) {
            _state.update { it.copy(pairingError = "Enter a 6-8 digit pairing code") }
            return
        }
        _state.update { it.copy(isPairing = true, pairingError = null) }
        viewModelScope.launch {
            try {
                val fingerprint = getDeviceFingerprint()
                val response = pairingApi.pair(PairRequest(code = code, deviceFingerprint = fingerprint))
                tokenStore.savePairingResult(
                    deviceToken = response.deviceToken,
                    childId = response.childId,
                    role = response.role,
                )
                // Start the recurring upload loop now that we have a token.
                MonitorUploader.startUploadLoop(getApplication())
                _state.update {
                    it.copy(
                        isPairing = false,
                        pairingDone = true,
                        pairedChildId = response.childId,
                        pairingError = null,
                    )
                }
                Log.i(TAG, "Pairing successful: child_id=${response.childId} role=${response.role}")
            } catch (e: retrofit2.HttpException) {
                val msg = when (e.code()) {
                    404 -> "Pairing code not found or expired"
                    410 -> "Pairing code already used — request a new one"
                    else -> "Server error: ${e.code()}"
                }
                _state.update { it.copy(isPairing = false, pairingError = msg) }
            } catch (e: Exception) {
                _state.update {
                    it.copy(
                        isPairing = false,
                        pairingError = "Cannot reach server: ${e.message}",
                    )
                }
            }
        }
    }

    // -------------------------------------------------------------------------
    // Permission step
    // -------------------------------------------------------------------------

    fun refreshPermissionStatus() {
        val ctx = getApplication<Application>()
        _state.update {
            it.copy(
                accessibilityEnabled = isAccessibilityEnabled(ctx),
                batteryOptimizationExempt = isBatteryOptimizationExempt(ctx),
            )
        }
    }

    private fun isAccessibilityEnabled(context: Context): Boolean {
        // Android stores the fully-qualified flattened component name, e.g.
        //   com.shomer.client/com.shomer.client.accessibility.ShomerAccessibilityService
        // Build the same form via ComponentName and compare by unflattening each entry
        // (string compare against a short "/.accessibility.X" form silently fails).
        val expected = ComponentName(
            context.packageName,
            "com.shomer.client.accessibility.ShomerAccessibilityService",
        )
        val enabled = Settings.Secure.getString(
            context.contentResolver,
            Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES,
        ) ?: return false
        return enabled.split(':').any { ComponentName.unflattenFromString(it) == expected }
    }

    private fun isBatteryOptimizationExempt(context: Context): Boolean {
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            val pm = context.getSystemService(android.os.PowerManager::class.java)
            pm?.isIgnoringBatteryOptimizations(context.packageName) == true
        } else {
            true // Below API 23, Doze doesn't apply the same way
        }
    }

    // -------------------------------------------------------------------------
    // Foreground service start
    // -------------------------------------------------------------------------

    fun startCapture() {
        val ctx = getApplication<Application>()
        val intent = android.content.Intent(ctx, CaptureForegroundService::class.java).apply {
            action = CaptureForegroundService.ACTION_START
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            ctx.startForegroundService(intent)
        } else {
            ctx.startService(intent)
        }
    }

    // -------------------------------------------------------------------------
    // Helpers
    // -------------------------------------------------------------------------

    /**
     * Returns a stable device fingerprint that does not contain PII.
     * Uses the Android ID (unique per app install, resets on factory reset).
     * This value is sent to POST /v1/pair as device_fingerprint — it is used
     * server-side for device dedup, not for user identification.
     */
    private fun getDeviceFingerprint(): String {
        val ctx = getApplication<Application>()
        val androidId = Settings.Secure.getString(ctx.contentResolver, Settings.Secure.ANDROID_ID)
        return androidId ?: java.util.UUID.randomUUID().toString()
    }

    companion object {
        private const val TAG = "OnboardingViewModel"
    }
}
