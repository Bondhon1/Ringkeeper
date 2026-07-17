package com.ringkeeper.app.net

import android.content.Context
import android.util.Log
import com.ringkeeper.app.data.Settings
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.util.concurrent.TimeUnit

class AuthException(message: String, val httpCode: Int? = null) : Exception(message)

/**
 * Supabase Auth (GoTrue) token manager. Signs in the single shared account with
 * email + password and keeps a valid JWT cached in EncryptedSharedPreferences,
 * refreshing before expiry. Synchronized because the sync worker may call it
 * from multiple coroutines.
 */
class SupabaseAuth(context: Context) {

    private val settings = Settings.get(context)
    private val client = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(15, TimeUnit.SECONDS)
        .build()

    /** Return a valid access token, refreshing or re-signing-in as needed. */
    @Synchronized
    fun accessToken(): String {
        val now = System.currentTimeMillis() / 1000
        val cached = settings.accessToken
        if (cached.isNotEmpty() && now < settings.expiresAt - EXPIRY_SKEW) {
            return cached
        }
        val refresh = settings.refreshToken
        if (refresh.isNotEmpty()) {
            try {
                store(tokenRequest("refresh_token", JSONObject().put("refresh_token", refresh)))
                return settings.accessToken
            } catch (e: AuthException) {
                Log.w(TAG, "Refresh failed (${e.message}); doing full sign-in")
            }
        }
        return signInInternal()
    }

    /** Force a fresh password sign-in (used after a 401). */
    @Synchronized
    fun forceSignIn(): String = signInInternal()

    private fun signInInternal(): String {
        val body = JSONObject()
            .put("email", settings.email)
            .put("password", settings.password)
        store(tokenRequest("password", body))
        Log.i(TAG, "Signed in to Supabase as ${settings.email}")
        return settings.accessToken
    }

    private fun tokenRequest(grantType: String, body: JSONObject): JSONObject {
        val url = "${settings.authUrl()}/token?grant_type=$grantType"
        val request = Request.Builder()
            .url(url)
            .addHeader("apikey", settings.anonKey)
            .post(body.toString().toRequestBody(JSON))
            .build()
        try {
            client.newCall(request).execute().use { resp ->
                val text = resp.body?.string().orEmpty()
                if (!resp.isSuccessful) {
                    throw AuthException("${resp.code}: ${text.take(200)}", resp.code)
                }
                return JSONObject(text)
            }
        } catch (e: AuthException) {
            throw e
        } catch (e: Exception) {
            throw AuthException("network error: ${e.message}")
        }
    }

    private fun store(json: JSONObject) {
        val access = json.optString("access_token")
        if (access.isEmpty()) throw AuthException("no access_token in response")
        settings.accessToken = access
        json.optString("refresh_token").takeIf { it.isNotEmpty() }?.let {
            settings.refreshToken = it
        }
        val now = System.currentTimeMillis() / 1000
        settings.expiresAt = when {
            json.has("expires_at") -> json.getLong("expires_at")
            else -> now + json.optLong("expires_in", 3600)
        }
    }

    companion object {
        private const val TAG = "SupabaseAuth"
        private const val EXPIRY_SKEW = 60 // seconds
        private val JSON = "application/json; charset=utf-8".toMediaType()
    }
}
