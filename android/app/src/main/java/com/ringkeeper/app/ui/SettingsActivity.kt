package com.ringkeeper.app.ui

import android.os.Bundle
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import com.ringkeeper.app.data.CallEntity
import com.ringkeeper.app.data.Settings
import com.ringkeeper.app.databinding.ActivitySettingsBinding
import com.ringkeeper.app.net.ApiClient
import com.ringkeeper.app.net.PostResult
import com.ringkeeper.app.service.CallMonitorService
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class SettingsActivity : AppCompatActivity() {

    private lateinit var binding: ActivitySettingsBinding
    private lateinit var settings: Settings

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivitySettingsBinding.inflate(layoutInflater)
        setContentView(binding.root)
        supportActionBar?.setDisplayHomeAsUpEnabled(true)

        settings = Settings.get(this)
        binding.editServerUrl.setText(settings.serverUrl)
        binding.editToken.setText(settings.token)

        binding.btnSave.setOnClickListener { save() }
        binding.btnTest.setOnClickListener { testConnection() }
    }

    private fun save() {
        val url = binding.editServerUrl.text.toString().trim()
        val token = binding.editToken.text.toString().trim()
        if (url.isEmpty() || token.isEmpty()) {
            Toast.makeText(this, "Both fields are required", Toast.LENGTH_SHORT).show()
            return
        }
        if (!url.startsWith("http://") && !url.startsWith("https://")) {
            Toast.makeText(this, "URL must start with http:// or https://", Toast.LENGTH_LONG).show()
            return
        }
        settings.serverUrl = url
        settings.token = token
        // (Re)start monitoring now that we're configured.
        CallMonitorService.start(this)
        Toast.makeText(this, "Saved. Monitoring started.", Toast.LENGTH_SHORT).show()
        finish()
    }

    private fun testConnection() {
        val url = binding.editServerUrl.text.toString().trim()
        val token = binding.editToken.text.toString().trim()
        if (url.isEmpty() || token.isEmpty()) {
            Toast.makeText(this, "Enter URL and token first", Toast.LENGTH_SHORT).show()
            return
        }
        binding.btnTest.isEnabled = false
        lifecycleScope.launch {
            val result = withContext(Dispatchers.IO) {
                val api = ApiClient(url.trimEnd('/') + "/api/calls", token)
                // A harmless probe row the server accepts and de-dupes.
                api.postCall(
                    CallEntity(
                        callLogId = -1,
                        callerName = "RingKeeper test",
                        number = "test",
                        callType = "unknown",
                        callTimeMillis = System.currentTimeMillis(),
                        clientUid = "connection-test-probe",
                    ),
                )
            }
            binding.btnTest.isEnabled = true
            val msg = when (result) {
                is PostResult.Accepted -> "Connection OK ✓"
                is PostResult.Retry -> "Failed: ${result.reason}"
                is PostResult.Drop -> "Server rejected request: ${result.reason}"
            }
            Toast.makeText(this@SettingsActivity, msg, Toast.LENGTH_LONG).show()
        }
    }

    override fun onSupportNavigateUp(): Boolean {
        finish()
        return true
    }
}
