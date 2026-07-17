package com.ringkeeper.app.net

import com.ringkeeper.app.data.CallEntity
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone
import java.util.concurrent.TimeUnit

/** Result of trying to POST one call to the server. */
sealed class PostResult {
    /** Stored (or already-present) on the server → safe to mark synced locally. */
    object Accepted : PostResult()

    /** Transient failure (network/5xx) → keep unsynced and retry later. */
    data class Retry(val reason: String) : PostResult()

    /** Permanent client error (4xx other than auth) → drop it, retrying won't help. */
    data class Drop(val reason: String) : PostResult()
}

class ApiClient(
    private val apiCallsUrl: String,
    private val token: String,
) {
    private val client = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .writeTimeout(15, TimeUnit.SECONDS)
        .readTimeout(15, TimeUnit.SECONDS)
        .build()

    private val iso = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS'Z'", Locale.US).apply {
        timeZone = TimeZone.getTimeZone("UTC")
    }

    fun postCall(call: CallEntity): PostResult {
        val json = JSONObject().apply {
            put("caller_name", call.callerName ?: JSONObject.NULL)
            put("number", call.number)
            put("call_type", call.callType)
            put("timestamp", iso.format(Date(call.callTimeMillis)))
            put("client_uid", call.clientUid)
        }
        val body = json.toString().toRequestBody(JSON)
        val request = Request.Builder()
            .url(apiCallsUrl)
            .addHeader("Authorization", "Bearer $token")
            .post(body)
            .build()

        return try {
            client.newCall(request).execute().use { resp ->
                when {
                    resp.isSuccessful -> PostResult.Accepted // 200 (dup) or 201 (new)
                    resp.code == 401 -> PostResult.Retry("unauthorized — check token")
                    resp.code in 400..499 -> PostResult.Drop("http ${resp.code}")
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
