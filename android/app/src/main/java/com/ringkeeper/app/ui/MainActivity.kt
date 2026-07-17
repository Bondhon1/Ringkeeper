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
        binding.btnStart.setOnClickListener { startMonitoring() }
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

        lifecycleScope.launch {
            val (total, pending) = withContext(Dispatchers.IO) {
                repo.totalCount() to repo.unsyncedCount()
            }
            binding.txtStats.text = "Calls stored locally: $total  •  Pending sync: $pending"
        }
    }
}
