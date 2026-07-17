package com.ringkeeper.app.net

import android.content.Context
import com.ringkeeper.app.data.CallEntity
import com.ringkeeper.app.data.Settings
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone
import java.util.concurrent.TimeUnit

/** Result of trying to push one call to Supabase. */
sealed class PostResult {
    /** Stored (or already present) → safe to mark synced locally. */
    object Accepted : PostResult()

    /** Transient failure (network/5xx/auth) → keep unsynced and retry later. */
    data class Retry(val reason: String) : PostResult()

    /** Permanent client error → drop it, retrying won't help. */
    data class Drop(val reason: String) : PostResult()
}

/**
 * Inserts calls into the Supabase `calls` table via PostgREST, authenticated
 * with the account JWT. Upserts on `client_uid` so retries are idempotent, and
 * `user_id` is filled server-side by the column's `default auth.uid()`.
 */
class SupabaseClient(context: Context) {

    private val settings = Settings.get(context)
    private val auth = SupabaseAuth(context)
    private val client = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .writeTimeout(15, TimeUnit.SECONDS)
        .readTimeout(15, TimeUnit.SECONDS)
        .build()

    private val iso = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS'Z'", Locale.US).apply {
        timeZone = TimeZone.getTimeZone("UTC")
    }

    fun insertCall(call: CallEntity): PostResult {
        val row = JSONObject().apply {
            put("caller_name", call.callerName ?: JSONObject.NULL)
            put("number", call.number)
            put("call_type", call.callType)
            put("call_time", iso.format(Date(call.callTimeMillis)))
            put("client_uid", call.clientUid)
        }
        val body = JSONArray().put(row).toString().toRequestBody(JSON)
        // Upsert: ignore rows that collide on the unique client_uid index.
        val url = "${settings.restUrl()}/calls?on_conflict=client_uid"

        val token = try {
            auth.accessToken()
        } catch (e: AuthException) {
            return PostResult.Retry("auth: ${e.message}")
        }

        val result = send(url, body, token)
        // A 401 can mean the cached token was revoked — re-auth once and retry.
        if (result is PostResult.Retry && result.reason.startsWith("401")) {
            return try {
                send(url, body, auth.forceSignIn())
            } catch (e: AuthException) {
                PostResult.Retry("auth: ${e.message}")
            }
        }
        return result
    }

    private fun send(url: String, body: okhttp3.RequestBody, token: String): PostResult {
        val request = Request.Builder()
            .url(url)
            .addHeader("apikey", settings.anonKey)
            .addHeader("Authorization", "Bearer $token")
            .addHeader("Content-Type", "application/json")
            .addHeader("Prefer", "resolution=ignore-duplicates,return=minimal")
            .post(body)
            .build()
        return try {
            client.newCall(request).execute().use { resp ->
                when {
                    resp.isSuccessful -> PostResult.Accepted           // 200/201/204
                    resp.code == 409 -> PostResult.Accepted            // duplicate → already stored
                    resp.code == 401 -> PostResult.Retry("401 unauthorized")
                    resp.code in 400..499 -> PostResult.Drop("http ${resp.code}")
                    else -> PostResult.Retry("http ${resp.code}")
                }
            }
        } catch (e: Exception) {
            PostResult.Retry(e.message ?: "network error")
        }
    }

    /** Used by the settings screen's "Test connection" button. */
    fun testConnection(): PostResult {
        val token = try {
            auth.forceSignIn()
        } catch (e: AuthException) {
            return if (e.httpCode != null && e.httpCode in 400..499) {
                PostResult.Drop("sign-in rejected: ${e.message}")
            } else {
                PostResult.Retry("auth: ${e.message}")
            }
        }
        val request = Request.Builder()
            .url("${settings.restUrl()}/calls?select=id&limit=1")
            .addHeader("apikey", settings.anonKey)
            .addHeader("Authorization", "Bearer $token")
            .get()
            .build()
        return try {
            client.newCall(request).execute().use { resp ->
                when {
                    resp.isSuccessful -> PostResult.Accepted
                    resp.code in 400..499 -> PostResult.Drop("http ${resp.code}: ${resp.body?.string()?.take(120)}")
                    else -> PostResult.Retry("http ${resp.code}")
                }
            }
        } catch (e: Exception) {
            PostResult.Retry(e.message ?: "network error")
        }
    }

    companion object {
        private val JSON = "application/json; charset=utf-8".toMediaType()
    }
}
