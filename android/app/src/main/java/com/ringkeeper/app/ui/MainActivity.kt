package com.ringkeeper.app.ui

import android.Manifest
import android.annotation.SuppressLint
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.PowerManager
import android.provider.Settings as AndroidSettings
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.NotificationManagerCompat
import androidx.lifecycle.lifecycleScope
import com.ringkeeper.app.data.CallRepository
import com.ringkeeper.app.data.Settings
import com.ringkeeper.app.databinding.ActivityMainBinding
import com.ringkeeper.app.service.CallMonitorService
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private lateinit var settings: Settings
    private lateinit var repo: CallRepository

    private val permissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions(),
    ) { _ -> refreshStatus() }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        settings = Settings.get(this)
        repo = CallRepository(this)

        binding.btnSettings.setOnClickListener {
            startActivity(Intent(this, SettingsActivity::class.java))
        }
        binding.btnGrantPermissions.setOnClickListener { requestPermissions() }
        binding.btnBattery.setOnClickListener { requestIgnoreBatteryOptimizations() }
        binding.btnWhatsApp.setOnClickListener { openNotificationAccessSettings() }
        binding.btnStart.setOnClickListener { startMonitoring() }
        binding.btnToggle.setOnClickListener { toggleMonitoring() }
    }

    override fun onResume() {
        super.onResume()
        refreshStatus()
    }

    private fun requestPermissions() {
        val perms = mutableListOf(
            Manifest.permission.READ_CALL_LOG,
            Manifest.permission.READ_PHONE_STATE,
        )
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            perms += Manifest.permission.POST_NOTIFICATIONS
        }
        permissionLauncher.launch(perms.toTypedArray())
    }

    private fun startMonitoring() {
        if (!settings.isConfigured) {
            startActivity(Intent(this, SettingsActivity::class.java))
            return
        }
        CallMonitorService.start(this)
        refreshStatus()
    }

    /**
     * Flip the shared on/off instruction. This pauses/resumes capture on the
     * phone AND popups on the PC (via the app_state row). Turning back on keeps
     * the service running so the change can propagate either way.
     */
    private fun toggleMonitoring() {
        val newEnabled = !settings.monitoringEnabled
        lifecycleScope.launch {
            withContext(Dispatchers.IO) { repo.setMonitoring(newEnabled, source = "phone") }
            if (newEnabled) CallMonitorService.start(this@MainActivity)
            refreshStatus()
        }
    }

    /**
     * WhatsApp calls are captured via a NotificationListenerService, which needs
     * the special "Notification access" grant — there's no runtime-permission
     * dialog for it, so send the user to the system settings screen.
     */
    private fun openNotificationAccessSettings() {
        val intent = Intent(AndroidSettings.ACTION_NOTIFICATION_LISTENER_SETTINGS)
        startActivity(intent)
    }

    private fun hasNotificationAccess(): Boolean =
        NotificationManagerCompat.getEnabledListenerPackages(this).contains(packageName)

    @SuppressLint("BatteryLife")
    private fun requestIgnoreBatteryOptimizations() {
        val pm = getSystemService(POWER_SERVICE) as PowerManager
        if (!pm.isIgnoringBatteryOptimizations(packageName)) {
            startActivity(
                Intent(
                    AndroidSettings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,
                    Uri.parse("package:$packageName"),
                ),
            )
        }
    }

    private fun refreshStatus() {
        val pm = getSystemService(POWER_SERVICE) as PowerManager
        val batteryOk = pm.isIgnoringBatteryOptimizations(packageName)
        val hasPerms = repo.hasCallLogPermission()

        binding.txtConfigured.text =
            if (settings.isConfigured) "Supabase: ${settings.supabaseUrl}" else "Supabase: not configured"
        binding.txtPermissions.text =
            if (hasPerms) "Call log permission: granted" else "Call log permission: NOT granted"
        binding.txtBattery.text =
            if (batteryOk) "Battery optimization: disabled ✓" else "Battery optimization: ON (recommend disabling)"
        binding.txtWhatsApp.text =
            if (hasNotificationAccess()) "WhatsApp call capture: on ✓" else "WhatsApp call capture: off (optional)"

        val enabled = settings.monitoringEnabled
        binding.btnToggle.text =
            if (enabled) "Turn off (pause both devices)" else "Turn on (resume both devices)"

        lifecycleScope.launch {
            val (total, pending) = withContext(Dispatchers.IO) {
                repo.totalCount() to repo.unsyncedCount()
            }
            binding.txtStats.text = "Calls stored locally: $total  •  Pending sync: $pending"
        }
    }
}
