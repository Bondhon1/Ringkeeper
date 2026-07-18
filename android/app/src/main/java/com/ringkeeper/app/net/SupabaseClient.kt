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

    private fun send(
        url: String,
        body: okhttp3.RequestBody,
        token: String,
        prefer: String = "resolution=ignore-duplicates,return=minimal",
    ): PostResult {
        val request = Request.Builder()
            .url(url)
            .addHeader("apikey", settings.anonKey)
            .addHeader("Authorization", "Bearer $token")
            .addHeader("Content-Type", "application/json")
            .addHeader("Prefer", prefer)
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

    // --- shared control + heartbeat + message relay --------------------------

    /**
     * Result of a control/state call. Booleans model "did it work"; the flag
     * fetch returns the value or null when unknown (network/first run).
     */

    /**
     * Upsert the phone's heartbeat (`phone_last_seen = now`). Creates the
     * app_state row on first run (monitoring defaults to enabled) and only
     * touches phone_last_seen thereafter, so it never clobbers the flag.
     */
    fun sendHeartbeat(): Boolean {
        val row = JSONObject().put("phone_last_seen", iso.format(Date()))
        return upsert("app_state", "user_id", row) is PostResult.Accepted
    }

    /**
     * Read the shared monitoring flag from the server. Returns null if it can't
     * be determined (no row yet, or a network error) so callers can leave the
     * local value untouched.
     */
    fun fetchMonitoringEnabled(): Boolean? {
        val token = try {
            auth.accessToken()
        } catch (e: AuthException) {
            return null
        }
        val request = Request.Builder()
            .url("${settings.restUrl()}/app_state?select=monitoring_enabled&limit=1")
            .addHeader("apikey", settings.anonKey)
            .addHeader("Authorization", "Bearer $token")
            .get()
            .build()
        return try {
            client.newCall(request).execute().use { resp ->
                if (!resp.isSuccessful) return null
                val arr = JSONArray(resp.body?.string().orEmpty())
                if (arr.length() == 0) null else arr.getJSONObject(0).optBoolean("monitoring_enabled")
            }
        } catch (e: Exception) {
            null
        }
    }

    /** Flip the shared monitoring flag (source = "phone" when the user taps it). */
    fun pushMonitoringEnabled(enabled: Boolean, source: String): Boolean {
        val row = JSONObject()
            .put("monitoring_enabled", enabled)
            .put("control_source", source)
            .put("control_updated_at", iso.format(Date()))
        return upsert("app_state", "user_id", row) is PostResult.Accepted
    }

    /**
     * Relay one WhatsApp message to the PC as an ephemeral row (the PC shows it,
     * then deletes it). Best-effort and un-queued by design — messages are not
     * stored, so if we're offline it's simply dropped.
     */
    fun relayMessage(sender: String, preview: String?, clientUid: String): Boolean {
        val row = JSONObject()
            .put("sender", sender)
            .put("preview", preview ?: JSONObject.NULL)
            .put("client_uid", clientUid)
        return upsert("messages", "client_uid", row) is PostResult.Accepted
    }

    /** Generic upsert used by the control/message helpers above. */
    private fun upsert(table: String, onConflict: String, row: JSONObject): PostResult {
        val body = JSONArray().put(row).toString().toRequestBody(JSON)
        val url = "${settings.restUrl()}/$table?on_conflict=$onConflict"
        val token = try {
            auth.accessToken()
        } catch (e: AuthException) {
            return PostResult.Retry("auth: ${e.message}")
        }
        val prefer = "resolution=merge-duplicates,return=minimal"
        val result = send(url, body, token, prefer)
        if (result is PostResult.Retry && result.reason.startsWith("401")) {
            return try {
                send(url, body, auth.forceSignIn(), prefer)
            } catch (e: AuthException) {
                PostResult.Retry("auth: ${e.message}")
            }
        }
        return result
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
