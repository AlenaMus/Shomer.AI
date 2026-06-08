package com.shomer.client.data

import android.content.Context
import android.content.SharedPreferences
import android.util.Log
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import dagger.hilt.android.qualifiers.ApplicationContext
import javax.inject.Inject
import javax.inject.Singleton

/**
 * EncryptedSharedPreferences-backed store for sensitive pairing state.
 *
 * Stores:
 *   - device_token : String  — Bearer token for Authorization header on /v1/ calls
 *   - child_id     : String  — opaque child identifier, included in every MonitorBatch
 *   - role         : String  — "child" | "parent" (governs MainActivity routing)
 *   - consented    : Boolean — true once the guardian has completed the ConsentScreen
 *
 * EncryptedSharedPreferences uses AES256-GCM for value encryption and AES256-SIV for
 * key encryption backed by the Android Keystore. The MasterKey is created with
 * KEY_SCHEME_AES256_GCM.
 *
 * The device_token survives APK updates within the same applicationId — it is tied to
 * the KeyStore entry scoped to this app's signing certificate + packageName.
 */
@Singleton
class TokenStore @Inject constructor(
    @ApplicationContext private val context: Context,
) {
    private val prefs: SharedPreferences by lazy { buildPrefs() }

    private fun buildPrefs(): SharedPreferences {
        return try {
            val masterKey = MasterKey.Builder(context)
                .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
                .build()
            EncryptedSharedPreferences.create(
                context,
                PREFS_FILE_NAME,
                masterKey,
                EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
                EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
            )
        } catch (e: Exception) {
            // Fallback: if the Keystore is corrupted (common after factory reset on some
            // OEMs), clear the file and try again once. If it still fails, crash loudly —
            // a compromised Keystore is not a safe state to silently continue in.
            Log.e(TAG, "EncryptedSharedPreferences init failed; clearing and retrying", e)
            context.deleteSharedPreferences(PREFS_FILE_NAME)
            val masterKey = MasterKey.Builder(context)
                .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
                .build()
            EncryptedSharedPreferences.create(
                context,
                PREFS_FILE_NAME,
                masterKey,
                EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
                EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
            )
        }
    }

    // -------------------------------------------------------------------------
    // Token + identity (written at pairing)
    // -------------------------------------------------------------------------

    fun getDeviceToken(): String? = prefs.getString(KEY_DEVICE_TOKEN, null)

    fun getChildId(): String? = prefs.getString(KEY_CHILD_ID, null)

    fun getRole(): String? = prefs.getString(KEY_ROLE, null)

    fun savePairingResult(deviceToken: String, childId: String, role: String) {
        prefs.edit()
            .putString(KEY_DEVICE_TOKEN, deviceToken)
            .putString(KEY_CHILD_ID, childId)
            .putString(KEY_ROLE, role)
            .apply()
    }

    fun isPaired(): Boolean = getDeviceToken() != null

    fun clearPairing() {
        prefs.edit()
            .remove(KEY_DEVICE_TOKEN)
            .remove(KEY_CHILD_ID)
            .remove(KEY_ROLE)
            .apply()
    }

    // -------------------------------------------------------------------------
    // Parent-mode auth (parent token is separate from the child device token)
    // -------------------------------------------------------------------------

    /**
     * Save the parent token returned by POST /v1/parent/register.
     * The parent token is stored as the device token with role="parent"
     * so AuthInterceptor picks it up automatically for all /v1/ calls.
     */
    fun saveParentToken(parentToken: String, parentId: String) {
        prefs.edit()
            .putString(KEY_DEVICE_TOKEN, parentToken)
            .putString(KEY_CHILD_ID, parentId)   // parent_id stored in child_id slot
            .putString(KEY_ROLE, ROLE_PARENT)
            .apply()
    }

    fun getParentId(): String? {
        // parent_id is stored in the KEY_CHILD_ID slot for parent role devices
        return if (getRole() == ROLE_PARENT) prefs.getString(KEY_CHILD_ID, null) else null
    }

    // -------------------------------------------------------------------------
    // Consent flag (written after ConsentScreen)
    // -------------------------------------------------------------------------

    fun hasConsented(): Boolean = prefs.getBoolean(KEY_CONSENTED, false)

    fun setConsented(value: Boolean) {
        prefs.edit().putBoolean(KEY_CONSENTED, value).apply()
    }

    companion object {
        private const val TAG = "TokenStore"
        private const val PREFS_FILE_NAME = "shomer_secure_prefs"
        private const val KEY_DEVICE_TOKEN = "device_token"
        private const val KEY_CHILD_ID = "child_id"
        private const val KEY_ROLE = "role"
        private const val KEY_CONSENTED = "consented"

        const val ROLE_CHILD = "child"
        const val ROLE_PARENT = "parent"
    }
}
