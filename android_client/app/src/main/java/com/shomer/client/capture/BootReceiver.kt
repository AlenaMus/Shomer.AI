package com.shomer.client.capture

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Build
import android.util.Log
import com.shomer.client.data.TokenStore
import com.shomer.client.monitor.MonitorUploader
import dagger.hilt.android.AndroidEntryPoint
import javax.inject.Inject

/**
 * Restarts CaptureForegroundService after device reboot.
 *
 * Only starts the service if the device has been paired (device_token present)
 * and the user has consented (hasConsented()), so an unpaired device doesn't
 * try to start monitoring on first boot.
 *
 * Requires RECEIVE_BOOT_COMPLETED permission (declared in the manifest).
 */
@AndroidEntryPoint
class BootReceiver : BroadcastReceiver() {

    @Inject
    lateinit var tokenStore: TokenStore

    override fun onReceive(context: Context, intent: Intent?) {
        if (intent?.action != Intent.ACTION_BOOT_COMPLETED) return

        if (!tokenStore.isPaired() || !tokenStore.hasConsented()) {
            Log.d(TAG, "Boot received but device not paired/consented — not starting capture")
            return
        }

        Log.i(TAG, "Boot completed — restarting CaptureForegroundService")
        val serviceIntent = Intent(context, CaptureForegroundService::class.java).apply {
            action = CaptureForegroundService.ACTION_START
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            context.startForegroundService(serviceIntent)
        } else {
            context.startService(serviceIntent)
        }

        // Restart the recurring upload loop (the one-time-work chain doesn't survive reboot).
        MonitorUploader.startUploadLoop(context)
    }

    companion object {
        private const val TAG = "BootReceiver"
    }
}
