package com.ringkeeper.app.data

import androidx.room.Entity
import androidx.room.Index
import androidx.room.PrimaryKey

/**
 * One captured call. Room is the local source of truth: every call is written
 * here first (so nothing is lost while offline), then synced to the server.
 *
 * [callLogId] is the CallLog row _ID — a unique index on it makes re-scans of
 * the system call log idempotent so we never double-insert the same call. It is
 * null for calls that don't come from the CallLog at all (e.g. WhatsApp calls,
 * which are captured from notifications — see [WhatsAppCallListener]).
 *
 * [clientUid] is the stable dedupe key the server uses to make retries
 * idempotent, and — via a unique index — also dedupes captures from *any*
 * source locally (a WhatsApp notification can be re-posted several times for one
 * call). [source] records where the row came from ("system" | "whatsapp").
 */
@Entity(
    tableName = "calls",
    indices = [
        Index(value = ["callLogId"], unique = true),
        Index(value = ["clientUid"], unique = true),
        Index(value = ["synced"]),
    ],
)
data class CallEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val callLogId: Long?,
    val callerName: String?,
    val number: String,
    val callType: String,
    val callTimeMillis: Long,
    val clientUid: String,
    val source: String = SOURCE_SYSTEM,
    val synced: Boolean = false,
    val createdAt: Long = System.currentTimeMillis(),
) {
    companion object {
        /** Captured from the Android system call log via a ContentObserver. */
        const val SOURCE_SYSTEM = "system"

        /** Captured from a WhatsApp call notification. */
        const val SOURCE_WHATSAPP = "whatsapp"
    }
}
