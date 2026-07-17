package com.ringkeeper.app.receiver

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log
import com.ringkeeper.app.data.Settings
import com.ringkeeper.app.service.CallMonitorService

/** Restart the monitor service after the device reboots. */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val action = intent.action
        if (action == Intent.ACTION_BOOT_COMPLETED ||
            action == "android.intent.action.QUICKBOOT_POWERON"
        ) {
            // Only start if the user has actually configured the server, else
            // the service would sit there unable to sync.
            if (Settings.get(context).isConfigured) {
                Log.i(TAG, "Boot completed → starting CallMonitorService")
                CallMonitorService.start(context)
            }
        }
    }

    companion object {
        private const val TAG = "BootReceiver"
    }
}
