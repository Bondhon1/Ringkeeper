package com.ringkeeper.app.ui

import android.Manifest
import android.annotation.SuppressLint
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.PowerManager
import android.provider.Settings as AndroidSettings
import android.widget.ImageView
import android.widget.TextView
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.app.NotificationManagerCompat
import androidx.lifecycle.lifecycleScope
import com.ringkeeper.app.R
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

        binding.rowConn.setOnClickListener {
            startActivity(Intent(this, SettingsActivity::class.java))
        }
        binding.rowPerm.setOnClickListener { requestPermissions() }
        binding.rowBattery.setOnClickListener { requestIgnoreBatteryOptimizations() }
        binding.rowWhatsApp.setOnClickListener { openNotificationAccessSettings() }
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
        if (!settings.monitoringEnabled) {
            lifecycleScope.launch {
                withContext(Dispatchers.IO) { repo.setMonitoring(true, source = "phone") }
                CallMonitorService.start(this@MainActivity)
                refreshStatus()
            }
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
        val configured = settings.isConfigured
        val whatsAppOn = hasNotificationAccess()
        val monitoringOn = settings.monitoringEnabled

        setStep(
            binding.icoPerm, binding.txtPerm, hasPerms,
            doneText = "Granted", todoText = "Tap to grant",
        )
        setStep(
            binding.icoConn, binding.txtConn, configured,
            doneText = settings.supabaseUrl, todoText = "Tap to configure",
        )
        setStep(
            binding.icoBattery, binding.txtBattery, batteryOk,
            doneText = "Disabled", todoText = "Recommended to disable",
        )
        setStep(
            binding.icoWhatsApp, binding.txtWhatsApp, whatsAppOn,
            doneText = "On", todoText = "Optional · off",
        )

        // Hero: overall state.
        val setupDone = hasPerms && configured
        when {
            !setupDone -> setHero(
                "Setup needed", R.color.rk_warning,
                "Finish the required steps below to start relaying calls.",
            )
            monitoringOn -> setHero(
                "Active", R.color.rk_success,
                "RingKeeper is watching and relaying calls to your PC.",
            )
            else -> setHero(
                "Paused", R.color.rk_warning,
                "Monitoring is turned off on both this phone and your PC.",
            )
        }

        binding.btnStart.text = if (setupDone && monitoringOn) "Restart monitoring" else "Start monitoring"
        binding.btnToggle.text =
            if (monitoringOn) "Turn off (pause both devices)" else "Turn on (resume both devices)"

        lifecycleScope.launch {
            val (total, pending) = withContext(Dispatchers.IO) {
                repo.totalCount() to repo.unsyncedCount()
            }
            binding.txtStatStored.text = total.toString()
            binding.txtStatPending.text = pending.toString()
        }
    }

    private fun setHero(title: String, colorRes: Int, sub: String) {
        val color = ContextCompat.getColor(this, colorRes)
        binding.txtHeroStatus.text = title
        binding.txtHeroSub.text = sub
        binding.dotStatus.background?.mutate()?.setTint(color)
    }

    /** Flip one checklist row between the "done" (green check) and "todo" states. */
    private fun setStep(
        icon: ImageView,
        status: TextView,
        done: Boolean,
        doneText: String,
        todoText: String,
    ) {
        if (done) {
            icon.setImageResource(R.drawable.ic_check_circle)
            icon.setColorFilter(ContextCompat.getColor(this, R.color.rk_success))
            status.text = doneText
        } else {
            icon.setImageResource(R.drawable.ic_circle_outline)
            icon.setColorFilter(ContextCompat.getColor(this, R.color.rk_text_muted))
            status.text = todoText
        }
    }
}
