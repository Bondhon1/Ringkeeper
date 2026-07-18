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

    // WhatsApp calls never appear in the CallLog, so they get their own canonical
    // types (kept distinct from system calls so the PC can label/filter/pop them
    // up separately). These must also be in the server's call_type CHECK set.
    const val WHATSAPP_MISSED = "whatsapp_missed"
    const val WHATSAPP_INCOMING = "whatsapp_incoming"

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
