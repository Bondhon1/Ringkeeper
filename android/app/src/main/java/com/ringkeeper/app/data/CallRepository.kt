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
    fun deviceId(): String =
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
     * Record a call captured outside the CallLog — currently WhatsApp calls seen
     * by [com.ringkeeper.app.service.WhatsAppCallListener]. These have no CallLog
     * _ID, so [CallEntity.callLogId] is null and dedupe rides entirely on the
     * unique [clientUid]: WhatsApp re-posts the same notification several times
     * for one call, so the caller passes a [clientUid] that's stable per call
     * (name + which second it happened + type). Returns true if a new row was
     * inserted (false if it was a duplicate we've already stored).
     */
    suspend fun recordExternalCall(
        callType: String,
        callerName: String?,
        number: String,
        callTimeMillis: Long,
        clientUid: String,
        source: String,
    ): Boolean {
        val entity = CallEntity(
            callLogId = null,
            callerName = callerName,
            number = number,
            callType = callType,
            callTimeMillis = callTimeMillis,
            clientUid = clientUid,
            source = source,
        )
        val inserted = dao.insertIgnore(entity) != -1L
        if (inserted) Log.i(TAG, "Captured $callType call from $source into local DB")
        return inserted
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

    // --- shared on/off control + heartbeat + WhatsApp message relay ----------

    /** The local mirror of the shared monitoring flag; gates all capture. */
    fun isMonitoringEnabled(): Boolean = settings.monitoringEnabled

    /**
     * One control cycle, run periodically by [com.ringkeeper.app.service.CallMonitorService]:
     *  - adopt the server's monitoring flag (the PC may have flipped it), and
     *  - write the phone's heartbeat so the PC can tell "off" from "gone".
     * Best-effort; leaves local state untouched on any network hiccup.
     */
    suspend fun syncControlAndHeartbeat() {
        if (!settings.isConfigured) return
        val api = SupabaseClient(context)
        api.fetchMonitoringEnabled()?.let { remote ->
            if (remote != settings.monitoringEnabled) {
                Log.i(TAG, "Monitoring flag adopted from server: $remote")
                settings.monitoringEnabled = remote
            }
        }
        api.sendHeartbeat()
    }

    /** Flip the shared flag (local first for instant UI, then push to server). */
    suspend fun setMonitoring(enabled: Boolean, source: String) {
        settings.monitoringEnabled = enabled
        if (settings.isConfigured) {
            SupabaseClient(context).pushMonitoringEnabled(enabled, source)
        }
    }

    /**
     * Relay a WhatsApp message to the PC — ephemeral and un-queued: not stored
     * locally, and simply dropped if we're off or offline. Returns true if the
     * server accepted it.
     */
    suspend fun relayWhatsAppMessage(sender: String, preview: String?, clientUid: String): Boolean {
        if (!settings.monitoringEnabled || !settings.isConfigured) return false
        return SupabaseClient(context).relayMessage(sender, preview, clientUid)
    }

    companion object {
        private const val TAG = "CallRepository"
    }
}
