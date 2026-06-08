package com.shomer.client.data

import android.content.Context
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map
import javax.inject.Inject
import javax.inject.Singleton

private val Context.dataStore by preferencesDataStore(name = "settings")

/**
 * DataStore-backed settings — persists the configurable server base URL.
 *
 * The default is the Android-emulator alias for the host machine (10.0.2.2).
 * For a physical phone on the same Wi-Fi, the user enters the PC's LAN IP
 * in the Settings screen (e.g. http://192.168.1.50:8000/).
 *
 * NEVER hardcode localhost or 127.0.0.1 — those loop back inside the
 * emulator VM, not to the host machine.
 */
@Singleton
class SettingsRepository @Inject constructor(
    @ApplicationContext private val context: Context,
) {
    private val keyServerUrl = stringPreferencesKey("server_url")

    val serverUrl: Flow<String> = context.dataStore.data.map { prefs: Preferences ->
        prefs[keyServerUrl] ?: DEFAULT_SERVER_URL
    }

    suspend fun setServerUrl(url: String) {
        context.dataStore.edit { it[keyServerUrl] = url }
    }

    companion object {
        // Emulator default. Physical phone must update this in Settings.
        const val DEFAULT_SERVER_URL = "http://10.0.2.2:8000/"
    }
}
