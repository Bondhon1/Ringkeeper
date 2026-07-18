package com.ringkeeper.app.service

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.database.ContentObserver
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkRequest
import android.os.Build
import android.os.Handler
import android.os.HandlerThread
import android.os.IBinder
import android.provider.CallLog
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import com.ringkeeper.app.R
import com.ringkeeper.app.data.CallRepository
import com.ringkeeper.app.sync.SyncScheduler
import com.ringkeeper.app.ui.MainActivity
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch

/**
 * Persistent foreground service. It:
 *   - registers a ContentObserver on the CallLog so every new call (of any
 *     type) is captured the moment it's written,
 *   - registers a network callback so the sync queue flushes on reconnect,
 *   - keeps the process alive under OEM battery restrictions.
 */
class CallMonitorService : Service() {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private lateinit var repo: CallRepository
    private lateinit var observerThread: HandlerThread
    private var callLogObserver: ContentObserver? = null
    private var networkCallback: ConnectivityManager.NetworkCallback? = null

    override fun onCreate() {
        super.onCreate()
        repo = CallRepository(applicationContext)
        createChannel()
        registerCallLogObserver()
        registerNetworkCallback()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        // specialUse on API 34+ (no runtime time limit); dataSync back to API 29.
        val type = when {
            Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE ->
                ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE
            Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q ->
                ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC
            else -> 0
        }
        try {
            ServiceCompat.startForeground(this, NOTIF_ID, buildNotification(), type)
        } catch (e: Exception) {
            // e.g. ForegroundServiceStartNotAllowedException if the OS refuses the
            // start. Never let that crash the app — bail out and let the boot
            // receiver / next call trigger bring monitoring back.
            Log.w(TAG, "startForeground refused: ${e.message}")
            stopSelf()
            return START_NOT_STICKY
        }
        SyncScheduler.ensurePeriodic(applicationContext)
        // Catch up on anything that happened while we weren't watching.
        scope.launch {
            repo.scanCallLog()
            SyncScheduler.syncNow(applicationContext)
        }
        return START_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun registerCallLogObserver() {
        observerThread = HandlerThread("calllog-observer").apply { start() }
        val handler = Handler(observerThread.looper)
        val observer = object : ContentObserver(handler) {
            override fun onChange(selfChange: Boolean) {
                Log.d(TAG, "CallLog changed → scanning")
                scope.launch {
                    val captured = repo.scanCallLog()
                    if (captured > 0) SyncScheduler.syncNow(applicationContext)
                }
            }
        }
        contentResolver.registerContentObserver(
            CallLog.Calls.CONTENT_URI, true, observer,
        )
        callLogObserver = observer
    }

    private fun registerNetworkCallback() {
        val cm = getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        val request = NetworkRequest.Builder()
            .addCapability(android.net.NetworkCapabilities.NET_CAPABILITY_INTERNET)
            .build()
        val callback = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) {
                Log.d(TAG, "Network available → flushing sync queue")
                SyncScheduler.syncNow(applicationContext)
            }
        }
        cm.registerNetworkCallback(request, callback)
        networkCallback = callback
    }

    private fun createChannel() {
        val mgr = getSystemService(NotificationManager::class.java)
        val channel = NotificationChannel(
            CHANNEL_ID,
            getString(R.string.channel_monitor),
            NotificationManager.IMPORTANCE_LOW, // silent, no sound/vibration
        ).apply { description = getString(R.string.channel_monitor_desc) }
        mgr.createNotificationChannel(channel)
    }

    private fun buildNotification(): Notification {
        val openIntent = PendingIntent.getActivity(
            this,
            0,
            Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle(getString(R.string.notif_title))
            .setContentText(getString(R.string.notif_text))
            .setSmallIcon(R.drawable.ic_notification)
            .setOngoing(true)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .setContentIntent(openIntent)
            .build()
    }

    override fun onDestroy() {
        callLogObserver?.let { contentResolver.unregisterContentObserver(it) }
        networkCallback?.let {
            val cm = getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
            runCatching { cm.unregisterNetworkCallback(it) }
        }
        if (this::observerThread.isInitialized) observerThread.quitSafely()
        scope.cancel()
        super.onDestroy()
    }

    companion object {
        private const val TAG = "CallMonitorService"
        private const val CHANNEL_ID = "ringkeeper_monitor"
        private const val NOTIF_ID = 1

        fun start(context: Context) {
            val intent = Intent(context, CallMonitorService::class.java)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(intent)
            } else {
                context.startService(intent)
            }
        }
    }
}
