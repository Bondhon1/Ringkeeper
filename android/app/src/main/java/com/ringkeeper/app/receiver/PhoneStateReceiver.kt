package com.ringkeeper.app.receiver

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.telephony.TelephonyManager
import android.util.Log
import com.ringkeeper.app.sync.SyncScheduler

/**
 * Fast trigger: when a call ends (state returns to IDLE) we kick a scan+sync so
 * the just-ended call is picked up promptly. The CallMonitorService's
 * ContentObserver is the primary, more reliable mechanism; this just shortens
 * latency and covers the case where the observer missed a beat.
 *
 * State is tracked in a companion field because a fresh receiver instance is
 * created for every broadcast.
 */
class PhoneStateReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != TelephonyManager.ACTION_PHONE_STATE_CHANGED) return
        val state = intent.getStringExtra(TelephonyManager.EXTRA_STATE) ?: return

        val wasActive = lastState == TelephonyManager.EXTRA_STATE_RINGING ||
            lastState == TelephonyManager.EXTRA_STATE_OFFHOOK
        if (state == TelephonyManager.EXTRA_STATE_IDLE && wasActive) {
            Log.d(TAG, "Call ended → scheduling scan+sync")
            // WorkManager's few-second latency usually gives the CallLog row
            // time to be written before SyncWorker scans.
            SyncScheduler.syncNow(context)
        }
        lastState = state
    }

    companion object {
        private const val TAG = "PhoneStateReceiver"
        private var lastState: String? = null
    }
}
