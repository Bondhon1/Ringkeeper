package com.ringkeeper.app.data

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query

@Dao
interface CallDao {

    /** IGNORE conflicts on the unique callLogId → re-scanning is safe. */
    @Insert(onConflict = OnConflictStrategy.IGNORE)
    suspend fun insertIgnore(call: CallEntity): Long

    @Query("SELECT * FROM calls WHERE synced = 0 ORDER BY callTimeMillis ASC LIMIT :limit")
    suspend fun unsynced(limit: Int = 100): List<CallEntity>

    @Query("UPDATE calls SET synced = 1 WHERE id = :id")
    suspend fun markSynced(id: Long)

    @Query("SELECT MAX(callLogId) FROM calls")
    suspend fun maxCallLogId(): Long?

    @Query("SELECT COUNT(*) FROM calls WHERE synced = 0")
    suspend fun unsyncedCount(): Int

    @Query("SELECT * FROM calls ORDER BY callTimeMillis DESC LIMIT :limit")
    suspend fun recent(limit: Int = 100): List<CallEntity>

    @Query("SELECT COUNT(*) FROM calls")
    suspend fun total(): Int
}
