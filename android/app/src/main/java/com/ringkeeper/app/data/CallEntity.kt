package com.ringkeeper.app.data

import androidx.room.Entity
import androidx.room.Index
import androidx.room.PrimaryKey

/**
 * One captured call. Room is the local source of truth: every call is written
 * here first (so nothing is lost while offline), then synced to the server.
 *
 * [callLogId] is the CallLog row _ID — a unique index on it makes re-scans
 * idempotent so we never double-insert the same call. [clientUid] is the stable
 * dedupe key the server uses to make retries idempotent too.
 */
@Entity(
    tableName = "calls",
    indices = [
        Index(value = ["callLogId"], unique = true),
        Index(value = ["synced"]),
    ],
)
data class CallEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val callLogId: Long,
    val callerName: String?,
    val number: String,
    val callType: String,
    val callTimeMillis: Long,
    val clientUid: String,
    val synced: Boolean = false,
    val createdAt: Long = System.currentTimeMillis(),
)
