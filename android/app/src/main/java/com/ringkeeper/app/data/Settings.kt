package com.ringkeeper.app.data

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

/**
 * Server URL + shared token, stored in EncryptedSharedPreferences so the token
 * isn't sitting in plaintext prefs.
 */
class Settings private constructor(private val prefs: SharedPreferences) {

    var serverUrl: String
        get() = prefs.getString(KEY_SERVER_URL, "")!!.trim()
        set(value) = prefs.edit().putString(KEY_SERVER_URL, value.trim()).apply()

    var token: String
        get() = prefs.getString(KEY_TOKEN, "")!!.trim()
        set(value) = prefs.edit().putString(KEY_TOKEN, value.trim()).apply()

    val isConfigured: Boolean
        get() = serverUrl.isNotEmpty() && token.isNotEmpty()

    /** Normalized base like "https://host:3000" with no trailing slash. */
    fun apiCallsUrl(): String = serverUrl.trimEnd('/') + "/api/calls"

    companion object {
        private const val FILE = "ringkeeper_secure_prefs"
        private const val KEY_SERVER_URL = "server_url"
        private const val KEY_TOKEN = "token"

        fun get(context: Context): Settings {
            val masterKey = MasterKey.Builder(context)
                .setKeyScheme(MasterKey.KeyScheme.AES256_GCM)
                .build()
            val prefs = EncryptedSharedPreferences.create(
                context,
                FILE,
                masterKey,
                EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
                EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM,
            )
            return Settings(prefs)
        }
    }
}
