package com.shomer.client.capture

import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.PixelFormat
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.ImageReader
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.IBinder
import android.util.Log
import androidx.core.app.NotificationCompat
import com.shomer.client.MainActivity
import com.shomer.client.R
import com.shomer.client.ShomerApplication
import dagger.hilt.android.AndroidEntryPoint
import javax.inject.Inject

/**
 * Foreground service that holds a [MediaProjection] + [VirtualDisplay] and exposes
 * a way to grab the latest screen frame as a [Bitmap] on demand.
 *
 * Lifecycle:
 *   - Start: caller invokes [startWith] from the consent result via ACTION_START.
 *     The resultCode + data Intent from the MediaProjection consent dialog are passed
 *     as extras so this service can recreate the projection after process death.
 *   - Stop: ACTION_STOP — releases the VirtualDisplay and MediaProjection cleanly.
 *
 * The [ScreenshotCoordinator] calls [latestBitmap] to pull a frame; this is safe
 * on any thread but must be called while the service is running.
 *
 * Foreground service type: mediaProjection (declared in the Manifest). Required on
 * Android 10+ to use MediaProjection from a background context.
 */
@AndroidEntryPoint
class ScreenCaptureService : Service() {

    @Inject
    lateinit var screenshotCoordinator: ScreenshotCoordinator

    private var mediaProjection: MediaProjection? = null
    private var virtualDisplay: VirtualDisplay? = null
    private var imageReader: ImageReader? = null

    // Screen dimensions — populated from WindowManager when the service starts.
    private var screenWidth = 0
    private var screenHeight = 0
    private var screenDensity = 0

    // MediaProjection callback: resets capture state if the user revokes consent
    // (e.g. a competing screen-capture app takes over on API 34+).
    private val projectionCallback = object : MediaProjection.Callback() {
        override fun onStop() {
            Log.i(TAG, "MediaProjection stopped externally — releasing capture state")
            teardown()
        }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP -> {
                teardown()
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf()
                instance = null
                return START_NOT_STICKY
            }
            ACTION_START -> {
                val resultCode = intent.getIntExtra(EXTRA_RESULT_CODE, -1)
                val data: Intent? = if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.TIRAMISU) {
                    intent.getParcelableExtra(EXTRA_DATA, Intent::class.java)
                } else {
                    @Suppress("DEPRECATION")
                    intent.getParcelableExtra(EXTRA_DATA)
                }
                if (data == null) {
                    Log.e(TAG, "ACTION_START received without projection data — ignoring")
                    stopSelf()
                    return START_NOT_STICKY
                }
                startForeground(NOTIFICATION_ID, buildNotification())
                initCapture(resultCode, data)
                instance = this
            }
        }
        return START_NOT_STICKY   // Do not restart automatically; consent is required each time.
    }

    private fun initCapture(resultCode: Int, data: Intent) {
        val wm = getSystemService(WINDOW_SERVICE) as android.view.WindowManager
        val metrics = android.util.DisplayMetrics()

        if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.R) {
            val bounds = wm.currentWindowMetrics.bounds
            screenWidth = bounds.width()
            screenHeight = bounds.height()
            screenDensity = resources.displayMetrics.densityDpi
        } else {
            @Suppress("DEPRECATION")
            wm.defaultDisplay.getRealMetrics(metrics)
            screenWidth = metrics.widthPixels
            screenHeight = metrics.heightPixels
            screenDensity = metrics.densityDpi
        }

        val mpm = getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
        val projection = mpm.getMediaProjection(resultCode, data)
        if (projection == null) {
            Log.e(TAG, "Failed to obtain MediaProjection — stopping service")
            stopSelf()
            return
        }
        mediaProjection = projection
        projection.registerCallback(projectionCallback, null)

        // ImageReader with MAX_IMAGES=2: one in-flight + one reserve so the producer
        // is never blocked.  RGBA_8888 is the format VirtualDisplay outputs.
        val reader = ImageReader.newInstance(
            screenWidth, screenHeight, PixelFormat.RGBA_8888, /* maxImages= */ 2,
        )
        imageReader = reader

        virtualDisplay = projection.createVirtualDisplay(
            VIRTUAL_DISPLAY_NAME,
            screenWidth, screenHeight, screenDensity,
            DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
            reader.surface, null, null,
        )

        Log.i(TAG, "MediaProjection capture started: ${screenWidth}x${screenHeight} @ ${screenDensity}dpi")

        // Notify the ScreenshotCoordinator that projection is now live.
        screenshotCoordinator.onProjectionStarted(this)
    }

    /**
     * Acquire the latest available frame from the [ImageReader] and convert it to a
     * [Bitmap].  Returns null if no frame is available yet (e.g. the first call
     * immediately after starting the VirtualDisplay).
     *
     * The caller MUST recycle the returned bitmap after use.
     * This method is safe to call from any thread.
     */
    fun latestBitmap(): Bitmap? {
        val reader = imageReader ?: return null
        val image = try {
            reader.acquireLatestImage()
        } catch (e: Exception) {
            Log.w(TAG, "acquireLatestImage failed: ${e.message}")
            null
        } ?: return null

        return try {
            val plane = image.planes[0]
            val rowPadding = plane.rowStride - plane.pixelStride * screenWidth
            val bitmap = Bitmap.createBitmap(
                screenWidth + rowPadding / plane.pixelStride,
                screenHeight,
                Bitmap.Config.ARGB_8888,
            )
            bitmap.copyPixelsFromBuffer(plane.buffer)
            // If there's row padding, crop it out.
            if (rowPadding == 0) bitmap
            else Bitmap.createBitmap(bitmap, 0, 0, screenWidth, screenHeight)
        } catch (e: Exception) {
            Log.e(TAG, "Failed to convert Image to Bitmap", e)
            null
        } finally {
            image.close()
        }
    }

    private fun teardown() {
        screenshotCoordinator.onProjectionStopped()
        virtualDisplay?.release()
        virtualDisplay = null
        imageReader?.close()
        imageReader = null
        mediaProjection?.unregisterCallback(projectionCallback)
        mediaProjection?.stop()
        mediaProjection = null
        Log.i(TAG, "Capture released")
    }

    override fun onDestroy() {
        teardown()
        instance = null
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    private fun buildNotification() = NotificationCompat.Builder(this, ShomerApplication.CHANNEL_MONITORING)
        .setSmallIcon(android.R.drawable.ic_menu_camera)
        .setContentTitle("Screen capture active")
        .setContentText("Reading open-chat messages to detect harmful content")
        .setOngoing(true)
        .setShowWhen(false)
        .setPriority(NotificationCompat.PRIORITY_LOW)
        .setContentIntent(
            PendingIntent.getActivity(
                this, 0,
                Intent(this, MainActivity::class.java),
                PendingIntent.FLAG_IMMUTABLE,
            ),
        )
        .build()

    companion object {
        private const val TAG = "ScreenCaptureService"
        private const val NOTIFICATION_ID = 1002
        private const val VIRTUAL_DISPLAY_NAME = "ShomerScreenCapture"

        const val ACTION_START = "com.shomer.client.ACTION_START_SCREEN_CAPTURE"
        const val ACTION_STOP  = "com.shomer.client.ACTION_STOP_SCREEN_CAPTURE"
        const val EXTRA_RESULT_CODE = "result_code"
        const val EXTRA_DATA = "projection_data"

        // Singleton reference set by the service itself — used by ScreenshotCoordinator
        // to call latestBitmap() without a bound service connection.
        @Volatile
        var instance: ScreenCaptureService? = null
            private set

        fun startWith(context: Context, resultCode: Int, data: Intent) {
            val intent = Intent(context, ScreenCaptureService::class.java).apply {
                action = ACTION_START
                putExtra(EXTRA_RESULT_CODE, resultCode)
                putExtra(EXTRA_DATA, data)
            }
            if (android.os.Build.VERSION.SDK_INT >= android.os.Build.VERSION_CODES.O) {
                context.startForegroundService(intent)
            } else {
                context.startService(intent)
            }
        }

        fun stop(context: Context) {
            context.startService(Intent(context, ScreenCaptureService::class.java).apply {
                action = ACTION_STOP
            })
        }

        fun isRunning(): Boolean = instance != null
    }
}
