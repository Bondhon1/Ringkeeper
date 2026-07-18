package com.ringkeeper.app.data

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase

@Database(entities = [CallEntity::class], version = 2, exportSchema = false)
abstract class AppDatabase : RoomDatabase() {
    abstract fun callDao(): CallDao

    companion object {
        @Volatile
        private var instance: AppDatabase? = null

        /**
         * v1 → v2: a second capture source (WhatsApp) means calls no longer all
         * come from the CallLog, so [CallEntity.callLogId] becomes nullable and a
         * [CallEntity.source] column is added. SQLite can't drop a NOT NULL
         * constraint in place, so the table is recreated. A unique index on
         * clientUid now carries dedupe for *all* sources (WhatsApp notifications
         * can be re-posted for a single call).
         */
        private val MIGRATION_1_2 = object : Migration(1, 2) {
            override fun migrate(db: SupportSQLiteDatabase) {
                db.execSQL(
                    """
                    CREATE TABLE calls_new (
                        id INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
                        callLogId INTEGER,
                        callerName TEXT,
                        number TEXT NOT NULL,
                        callType TEXT NOT NULL,
                        callTimeMillis INTEGER NOT NULL,
                        clientUid TEXT NOT NULL,
                        source TEXT NOT NULL,
                        synced INTEGER NOT NULL,
                        createdAt INTEGER NOT NULL
                    )
                    """.trimIndent(),
                )
                db.execSQL(
                    """
                    INSERT INTO calls_new (
                        id, callLogId, callerName, number, callType,
                        callTimeMillis, clientUid, source, synced, createdAt
                    )
                    SELECT id, callLogId, callerName, number, callType,
                        callTimeMillis, clientUid, 'system', synced, createdAt
                    FROM calls
                    """.trimIndent(),
                )
                db.execSQL("DROP TABLE calls")
                db.execSQL("ALTER TABLE calls_new RENAME TO calls")
                db.execSQL(
                    "CREATE UNIQUE INDEX IF NOT EXISTS index_calls_callLogId ON calls (callLogId)",
                )
                db.execSQL(
                    "CREATE UNIQUE INDEX IF NOT EXISTS index_calls_clientUid ON calls (clientUid)",
                )
                db.execSQL(
                    "CREATE INDEX IF NOT EXISTS index_calls_synced ON calls (synced)",
                )
            }
        }

        fun get(context: Context): AppDatabase =
            instance ?: synchronized(this) {
                instance ?: Room.databaseBuilder(
                    context.applicationContext,
                    AppDatabase::class.java,
                    "ringkeeper.db",
                ).addMigrations(MIGRATION_1_2).build().also { instance = it }
            }
    }
}
