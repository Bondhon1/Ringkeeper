package com.ringkeeper.app.data

import android.annotation.SuppressLint
import android.content.Context
import android.content.pm.PackageManager
import android.provider.CallLog
import android.provider.Settings as AndroidSettings
import android.util.Log
import androidx.core.content.ContextCompat
import com.ringkeeper.app.net.PostResult
import com.ringkeeper.app.net.SupabaseClient

/**
 * Ties together the CallLog, the local Room DB, and the server.
 *
 *  - [scanCallLog] reads any new CallLog rows and writes them into Room. This is
 *    the "store locally first / network-independent" half: it works fully offline.
 *  - [syncPending] pushes unsynced rows to the server, one at a time, marking
 *    each synced only once the server has accepted it.
 */
class CallRepository(private val context: Context) {

    private val dao = AppDatabase.get(context).callDao()
    private val settings = Settings.get(context)

    fun hasCallLogPermission(): Boolean =
        ContextCompat.checkSelfPermission(context, android.Manifest.permission.READ_CALL_LOG) ==
            PackageManager.PERMISSION_GRANTED

    @SuppressLint("HardwareIds")
    private fun deviceId(): String =
        AndroidSettings.Secure.getString(context.contentResolver, AndroidSettings.Secure.ANDROID_ID)
            ?: "unknown-device"

    /**
     * Read CallLog rows newer than the highest one we've already stored, and
     * insert them into Room. Returns the number of new calls captured.
     */
    suspend fun scanCallLog(): Int {
        if (!hasCallLogPermission()) {
            Log.w(TAG, "scanCallLog skipped: READ_CALL_LOG not granted")
            return 0
        }
        val lastId = dao.maxCallLogId() ?: -1L
        val device = deviceId()

        val projection = arrayOf(
            CallLog.Calls._ID,
            CallLog.Calls.NUMBER,
            CallLog.Calls.CACHED_NAME,
            CallLog.Calls.TYPE,
            CallLog.Calls.DATE,
        )
        // Only rows with a newer _ID than we've seen; oldest-first so inserts
        // stay in chronological order.
        val selection = "${CallLog.Calls._ID} > ?"
        val args = arrayOf(lastId.toString())

        var captured = 0
        context.contentResolver.query(
            CallLog.Calls.CONTENT_URI,
            projection,
            selection,
            args,
            "${CallLog.Calls._ID} ASC",
        )?.use { cursor ->
            val idCol = cursor.getColumnIndexOrThrow(CallLog.Calls._ID)
            val numberCol = cursor.getColumnIndexOrThrow(CallLog.Calls.NUMBER)
            val nameCol = cursor.getColumnIndexOrThrow(CallLog.Calls.CACHED_NAME)
            val typeCol = cursor.getColumnIndexOrThrow(CallLog.Calls.TYPE)
            val dateCol = cursor.getColumnIndexOrThrow(CallLog.Calls.DATE)

            while (cursor.moveToNext()) {
                val callLogId = cursor.getLong(idCol)
                val number = cursor.getString(numberCol)?.takeIf { it.isNotBlank() } ?: "unknown"
                val name = cursor.getString(nameCol)
                val type = CallTypes.fromCallLogType(cursor.getInt(typeCol))
                val date = cursor.getLong(dateCol)

                val entity = CallEntity(
                    callLogId = callLogId,
                    callerName = name,
                    number = number,
                    callType = type,
                    callTimeMillis = date,
                    clientUid = "$device-$callLogId-$date",
                )
                val rowId = dao.insertIgnore(entity)
                if (rowId != -1L) captured++
            }
        }
        if (captured > 0) Log.i(TAG, "Captured $captured new call(s) into local DB")
        return captured
    }

    /**
     * Push unsynced rows to the server. Returns true if everything pending is
     * now synced; false if something needs a retry (caller should reschedule).
     */
    suspend fun syncPending(): Boolean {
        if (!settings.isConfigured) {
            Log.w(TAG, "syncPending skipped: server not configured")
            return false
        }
        val api = SupabaseClient(context)
        var allDone = true
        val pending = dao.unsynced(limit = 200)
        for (call in pending) {
            when (val result = api.insertCall(call)) {
                is PostResult.Accepted -> dao.markSynced(call.id)
                is PostResult.Drop -> {
                    // Permanent error — mark synced so it stops blocking the queue.
                    Log.w(TAG, "Dropping call ${call.id}: ${result.reason}")
                    dao.markSynced(call.id)
                }
                is PostResult.Retry -> {
                    Log.i(TAG, "Retry needed for call ${call.id}: ${result.reason}")
                    allDone = false
                    break // stop on first transient failure; WorkManager retries later
                }
            }
        }
        return allDone
    }

    suspend fun unsyncedCount(): Int = dao.unsyncedCount()
    suspend fun totalCount(): Int = dao.total()

    companion object {
        private const val TAG = "CallRepository"
    }
}
