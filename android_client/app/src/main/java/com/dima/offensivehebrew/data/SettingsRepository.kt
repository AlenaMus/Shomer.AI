package com.dima.offensivehebrew.data

import android.content.Context
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

private val Context.dataStore by preferencesDataStore(name = "settings")

class SettingsRepository(private val context: Context) {

    private val keyServerUrl = stringPreferencesKey("server_url")

    val serverUrl: Flow<String> = context.dataStore.data.map { prefs: Preferences ->
        prefs[keyServerUrl] ?: DEFAULT_SERVER_URL
    }

    suspend fun setServerUrl(url: String) {
        context.dataStore.edit { it[keyServerUrl] = url }
    }

    companion object {
        // Emulator default — physical phone must update this in Settings.
        const val DEFAULT_SERVER_URL = "http://10.0.2.2:8000/"
    }
}
