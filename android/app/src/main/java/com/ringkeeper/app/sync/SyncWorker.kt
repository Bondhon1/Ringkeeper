package com.ringkeeper.app.sync

import android.content.Context
import android.util.Log
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import com.ringkeeper.app.data.CallRepository

/**
 * Runs a scan + sync cycle. WorkManager only launches this when its network
 * constraint is satisfied, and reschedules with backoff when we return retry().
 * That is the whole offline story: no network → the job simply waits.
 */
class SyncWorker(
    context: Context,
    params: WorkerParameters,
) : CoroutineWorker(context, params) {

    override suspend fun doWork(): Result {
        val repo = CallRepository(applicationContext)
        return try {
            // Capture anything new locally first (works even if this run was
            // triggered while briefly offline between constraint checks).
            repo.scanCallLog()
            val done = repo.syncPending()
            if (done) {
                Log.i(TAG, "Sync complete")
                Result.success()
            } else {
                Log.i(TAG, "Sync incomplete — will retry with backoff")
                Result.retry()
            }
        } catch (e: Exception) {
            Log.e(TAG, "Sync failed", e)
            Result.retry()
        }
    }

    companion object {
        private const val TAG = "SyncWorker"
    }
}
