package com.ringkeeper.app.data

import android.provider.CallLog

/**
 * Maps Android's [CallLog.Calls] TYPE constants onto RingKeeper's canonical
 * string types (which must match the server's CALL_TYPES set).
 */
object CallTypes {
    const val MISSED = "missed"
    const val INCOMING = "incoming"
    const val OUTGOING = "outgoing"
    const val REJECTED = "rejected"
    const val BLOCKED = "blocked"
    const val VOICEMAIL = "voicemail"
    const val UNKNOWN = "unknown"

    fun fromCallLogType(type: Int): String = when (type) {
        CallLog.Calls.INCOMING_TYPE -> INCOMING
        CallLog.Calls.OUTGOING_TYPE -> OUTGOING
        CallLog.Calls.MISSED_TYPE -> MISSED
        CallLog.Calls.VOICEMAIL_TYPE -> VOICEMAIL
        CallLog.Calls.REJECTED_TYPE -> REJECTED
        CallLog.Calls.BLOCKED_TYPE -> BLOCKED
        // A call answered on another device (e.g. a paired watch) — treat as incoming.
        CallLog.Calls.ANSWERED_EXTERNALLY_TYPE -> INCOMING
        else -> UNKNOWN
    }
}
