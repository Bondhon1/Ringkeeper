package com.ringkeeper.app.service

import android.app.Notification
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import android.util.Log
import com.ringkeeper.app.data.CallEntity
import com.ringkeeper.app.data.CallRepository
import com.ringkeeper.app.data.CallTypes
import com.ringkeeper.app.sync.SyncScheduler
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch

/**
 * Captures WhatsApp calls, which never appear in the system CallLog and so are
 * invisible to [CallMonitorService]'s ContentObserver. WhatsApp instead surfaces
 * calls as notifications, and — once the user grants "Notification access" — this
 * service is bound by the system and sees every one.
 *
 * It recognises two events:
 *   - a **missed** WhatsApp call ("Missed voice call" / "Missed video call"), and
 *   - an **incoming** (ringing) WhatsApp call — a call-category notification.
 * Both are written straight to the local DB (offline-first, same as CallLog
 * captures) and then a sync is nudged.
 *
 * WhatsApp re-posts the same notification repeatedly while a call rings and as it
 * updates a duration counter, so dedupe is essential: the [CallEntity.clientUid]
 * is made stable per call (caller + the second it started + type) and a unique
 * index collapses the repeats to a single row.
 *
 * The text WhatsApp shows is localized, so detection leans first on the
 * notification *category* (which is stable) and falls back to keyword matching
 * for the missed-call case. Extend [MISSED_KEYWORDS] for non-English phones.
 */
class WhatsAppCallListener : NotificationListenerService() {

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val repo by lazy { CallRepository(applicationContext) }

    override fun onNotificationPosted(sbn: StatusBarNotification) {
        if (sbn.packageName !in WHATSAPP_PACKAGES) return
        // Paused via the shared off-switch → capture nothing.
        if (!repo.isMonitoringEnabled()) return

        val n = sbn.notification ?: return
        // Skip the "checking for new messages" foreground/service notification and
        // the group summary — neither is a call or a message we want.
        if (n.flags and Notification.FLAG_GROUP_SUMMARY != 0) return
        if (n.category == Notification.CATEGORY_SERVICE) return

        val extras = n.extras
        val title = extras?.getCharSequence(Notification.EXTRA_TITLE)?.toString()?.trim()
        val text = extras?.getCharSequence(Notification.EXTRA_TEXT)?.toString()?.trim().orEmpty()
        // Every call/message notification names the sender in the title; without
        // it we can't attribute anything, so there's nothing useful to relay.
        if (title.isNullOrBlank()) return

        val callType = classify(n.category, text)
        if (callType != null) {
            recordCall(callType, title, n, sbn)
        } else if (isMessage(n.category, extras, text)) {
            relayMessage(title, text, n, sbn)
        }
    }

    private fun recordCall(
        callType: String,
        title: String,
        n: Notification,
        sbn: StatusBarNotification,
    ) {
        // WhatsApp notifications carry no phone number, only the contact's name.
        val callTime = if (n.`when` > 0L) n.`when` else sbn.postTime
        // Stable per call: repeated posts of the same ring (or the same missed
        // entry) share a name, second, and type, so they collapse to one row.
        val clientUid = "wa-${repo.deviceId()}-$callType-${sanitize(title)}-${callTime / 1000}"

        scope.launch {
            val inserted = repo.recordExternalCall(
                callType = callType,
                callerName = title,
                number = NUMBER_LABEL,
                callTimeMillis = callTime,
                clientUid = clientUid,
                source = CallEntity.SOURCE_WHATSAPP,
            )
            if (inserted) {
                Log.d(TAG, "WhatsApp $callType from $title")
                SyncScheduler.syncNow(applicationContext)
            }
        }
    }

    /**
     * Relay a new WhatsApp message to the PC as an ephemeral entry (not stored on
     * the phone). Deduped on sender + message text so WhatsApp re-posting the same
     * conversation notification doesn't fire it twice; a genuinely new message has
     * new text and relays once.
     */
    private fun relayMessage(
        title: String,
        text: String,
        n: Notification,
        sbn: StatusBarNotification,
    ) {
        if (text.isBlank()) return
        val whenMs = if (n.`when` > 0L) n.`when` else sbn.postTime
        val clientUid =
            "wamsg-${repo.deviceId()}-${sanitize(title)}-${text.hashCode()}-${whenMs / 1000}"
        scope.launch {
            if (repo.relayWhatsAppMessage(sender = title, preview = text, clientUid = clientUid)) {
                Log.d(TAG, "WhatsApp message from $title relayed")
            }
        }
    }

    /**
     * Decide whether a WhatsApp notification represents a call, and which kind.
     * Returns null for anything that isn't a call (messages, etc.).
     */
    private fun classify(category: String?, text: String): String? {
        val lower = text.lowercase()
        val mentionsCall = CALL_KEYWORDS.any { it in lower }

        // A missed call: WhatsApp uses CATEGORY_MISSED_CALL on newer versions and
        // otherwise a plain notification whose text says so.
        if (category == CATEGORY_MISSED_CALL ||
            (MISSED_KEYWORDS.any { it in lower } && mentionsCall)
        ) {
            return CallTypes.WHATSAPP_MISSED
        }

        // A ringing/incoming call: a call-category notification (with a
        // full-screen intent). Guard the keyword-only path so a chat message
        // that merely mentions "call" isn't mistaken for one.
        if (category == Notification.CATEGORY_CALL) {
            return CallTypes.WHATSAPP_INCOMING
        }
        return null
    }

    /**
     * Whether a non-call WhatsApp notification is an actual chat message (as
     * opposed to backup/"web is active"/etc.). Relies on the messaging category
     * or a MessagingStyle payload (EXTRA_MESSAGES), and ignores WhatsApp's
     * generic aggregate notification titled just "WhatsApp".
     */
    private fun isMessage(category: String?, extras: android.os.Bundle?, text: String): Boolean {
        if (text.isBlank()) return false
        val hasMessagingStyle = extras?.containsKey(Notification.EXTRA_MESSAGES) == true
        return category == Notification.CATEGORY_MESSAGE || hasMessagingStyle
    }

    /** Keep clientUids index- and log-friendly regardless of the contact's name. */
    private fun sanitize(s: String): String =
        s.lowercase().replace(Regex("[^a-z0-9]+"), "-").trim('-').take(40)

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    companion object {
        private const val TAG = "WhatsAppCallListener"

        private val WHATSAPP_PACKAGES = setOf("com.whatsapp", "com.whatsapp.w4b")

        // Notification.CATEGORY_MISSED_CALL is API 33+; hardcode its value so the
        // check also compiles/works against our minSdk 26.
        private const val CATEGORY_MISSED_CALL = "missed_call"

        // Shown in the "number" slot — WhatsApp gives us no phone number, and
        // this makes it obvious in the list/popup that the call came via WhatsApp.
        private const val NUMBER_LABEL = "WhatsApp"

        // Localized text lives in the notification; these English defaults cover
        // the stock strings. Add your language's words to capture calls there too.
        private val MISSED_KEYWORDS = listOf("missed")
        private val CALL_KEYWORDS = listOf("call", "voice", "video")
    }
}
