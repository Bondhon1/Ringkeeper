package com.ringkeeper.app.ui

import android.os.Bundle
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import com.ringkeeper.app.data.Settings
import com.ringkeeper.app.databinding.ActivitySettingsBinding
import com.ringkeeper.app.net.PostResult
import com.ringkeeper.app.net.SupabaseClient
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
        binding.toolbar.setNavigationOnClickListener { finish() }

        settings = Settings.get(this)
        binding.editUrl.setText(settings.supabaseUrl)
        binding.editAnonKey.setText(settings.anonKey)
        binding.editEmail.setText(settings.email)
        binding.editPassword.setText(settings.password)

        binding.btnSave.setOnClickListener { save() }
        binding.btnTest.setOnClickListener { testConnection() }
    }

    private fun readFields(): Boolean {
        val url = binding.editUrl.text.toString().trim()
        val anon = binding.editAnonKey.text.toString().trim()
        val email = binding.editEmail.text.toString().trim()
        val password = binding.editPassword.text.toString()
        if (url.isEmpty() || anon.isEmpty() || email.isEmpty() || password.isEmpty()) {
            Toast.makeText(this, "All fields are required", Toast.LENGTH_SHORT).show()
            return false
        }
        if (!url.startsWith("https://") && !url.startsWith("http://")) {
            Toast.makeText(this, "URL must start with https://", Toast.LENGTH_LONG).show()
            return false
        }
        // Persist first so the auth manager and client read fresh values.
        settings.supabaseUrl = url
        settings.anonKey = anon
        settings.email = email
        settings.password = password
        settings.clearTokens() // creds changed → drop any cached JWT
        return true
    }

    private fun save() {
        if (!readFields()) return
        CallMonitorService.start(this)
        Toast.makeText(this, "Saved. Monitoring started.", Toast.LENGTH_SHORT).show()
        finish()
    }

    private fun testConnection() {
        if (!readFields()) return
        binding.btnTest.isEnabled = false
        lifecycleScope.launch {
            val result = withContext(Dispatchers.IO) { SupabaseClient(this@SettingsActivity).testConnection() }
            binding.btnTest.isEnabled = true
            val msg = when (result) {
                is PostResult.Accepted -> "Connection OK ✓ (signed in)"
                is PostResult.Retry -> "Failed: ${result.reason}"
                is PostResult.Drop -> "Rejected: ${result.reason}"
            }
            Toast.makeText(this@SettingsActivity, msg, Toast.LENGTH_LONG).show()
        }
    }

    override fun onSupportNavigateUp(): Boolean {
        finish()
        return true
    }
}
