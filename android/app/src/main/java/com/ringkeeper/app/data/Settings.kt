package com.ringkeeper.app.data

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

/**
 * Supabase connection settings + cached auth tokens, stored in
 * EncryptedSharedPreferences so nothing sensitive sits in plaintext.
 */
class Settings private constructor(private val prefs: SharedPreferences) {

    var supabaseUrl: String
        get() = prefs.getString(KEY_URL, "")!!.trim()
        set(value) = prefs.edit().putString(KEY_URL, value.trim()).apply()

    var anonKey: String
        get() = prefs.getString(KEY_ANON, "")!!.trim()
        set(value) = prefs.edit().putString(KEY_ANON, value.trim()).apply()

    var email: String
        get() = prefs.getString(KEY_EMAIL, "")!!.trim()
        set(value) = prefs.edit().putString(KEY_EMAIL, value.trim()).apply()

    var password: String
        get() = prefs.getString(KEY_PASSWORD, "")!!
        set(value) = prefs.edit().putString(KEY_PASSWORD, value).apply()

    val isConfigured: Boolean
        get() = supabaseUrl.isNotEmpty() && anonKey.isNotEmpty() &&
            email.isNotEmpty() && password.isNotEmpty()

    private fun base(): String = supabaseUrl.trimEnd('/')
    fun restUrl(): String = base() + "/rest/v1"
    fun authUrl(): String = base() + "/auth/v1"

    // --- cached auth tokens (managed by SupabaseAuth) --------------------
    var accessToken: String
        get() = prefs.getString(KEY_ACCESS, "")!!
        set(value) = prefs.edit().putString(KEY_ACCESS, value).apply()

    var refreshToken: String
        get() = prefs.getString(KEY_REFRESH, "")!!
        set(value) = prefs.edit().putString(KEY_REFRESH, value).apply()

    var expiresAt: Long
        get() = prefs.getLong(KEY_EXPIRES_AT, 0L)
        set(value) = prefs.edit().putLong(KEY_EXPIRES_AT, value).apply()

    fun clearTokens() {
        prefs.edit().remove(KEY_ACCESS).remove(KEY_REFRESH).remove(KEY_EXPIRES_AT).apply()
    }

    companion object {
        private const val FILE = "ringkeeper_secure_prefs"
        private const val KEY_URL = "supabase_url"
        private const val KEY_ANON = "anon_key"
        private const val KEY_EMAIL = "email"
        private const val KEY_PASSWORD = "password"
        private const val KEY_ACCESS = "access_token"
        private const val KEY_REFRESH = "refresh_token"
        private const val KEY_EXPIRES_AT = "expires_at"

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
