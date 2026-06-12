package com.shomer.client

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Scaffold
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import com.shomer.client.capture.CaptureCoordinator
import com.shomer.client.data.SettingsRepository
import com.shomer.client.data.TokenStore
import com.shomer.client.onboarding.ConsentScreen
import com.shomer.client.onboarding.MonitorActivityScreen
import com.shomer.client.onboarding.PairingScreen
import com.shomer.client.onboarding.PermissionFlowScreen
import com.shomer.client.onboarding.StatusScreen
import com.shomer.client.ui.theme.AppTheme
import dagger.hilt.android.AndroidEntryPoint
import javax.inject.Inject

// ---------------------------------------------------------------------------
// Navigation route constants (child-mode only)
// ---------------------------------------------------------------------------
private object Routes {
    const val CONSENT = "consent"
    const val PAIRING = "pairing"
    const val PERMISSIONS = "permissions"
    const val STATUS = "status"
    const val SETTINGS = "settings"
    const val MONITOR_ACTIVITY = "monitor_activity"
    const val DEBUG_CLASSIFY = "debug_classify"
}

/**
 * Single-Activity host. Compose Navigation handles all screen routing.
 *
 * This app is CHILD-MODE ONLY. Parents use the web dashboard (dashboard/index.html)
 * and receive email notifications — there is no parent-mode UI on the Android client.
 * Decision: plan-docs/decisions/child-only-and-email-alerts.decision.md (D-CO-1).
 *
 * Routing logic on startup:
 *   Not consented  → CONSENT → PAIRING → PERMISSIONS → STATUS
 *   Consented + not paired → PAIRING → PERMISSIONS → STATUS
 *   Paired         → STATUS (home)
 */
@AndroidEntryPoint
class MainActivity : ComponentActivity() {

    @Inject
    lateinit var tokenStore: TokenStore

    @Inject
    lateinit var captureCoordinator: CaptureCoordinator

    @Inject
    lateinit var settingsRepository: SettingsRepository

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()

        // If already paired, ensure the recurring upload loop is running so buffered
        // events are flushed on a plain app reopen (not just after pairing / reboot).
        if (tokenStore.isPaired()) {
            com.shomer.client.monitor.MonitorUploader.startUploadLoop(this)
        }

        val startDest = when {
            !tokenStore.hasConsented() -> Routes.CONSENT
            !tokenStore.isPaired() -> Routes.PAIRING
            else -> Routes.STATUS
        }

        setContent {
            AppTheme {
                val navController = rememberNavController()
                Scaffold { padding ->
                    ShomerNavHost(
                        navController = navController,
                        startDestination = startDest,
                        captureCoordinator = captureCoordinator,
                        modifier = Modifier.padding(padding),
                    )
                }
            }
        }
    }
}

@Composable
private fun ShomerNavHost(
    navController: NavHostController,
    startDestination: String,
    captureCoordinator: CaptureCoordinator,
    modifier: Modifier = Modifier,
) {
    NavHost(
        navController = navController,
        startDestination = startDestination,
        modifier = modifier,
    ) {
        // -----------------------------------------------------------------------
        // Child-mode onboarding flow
        // -----------------------------------------------------------------------
        composable(Routes.CONSENT) {
            ConsentScreen(
                onConsentDone = {
                    navController.navigate(Routes.PAIRING) {
                        popUpTo(Routes.CONSENT) { inclusive = true }
                    }
                },
            )
        }

        composable(Routes.PAIRING) {
            PairingScreen(
                onPairingDone = {
                    navController.navigate(Routes.PERMISSIONS) {
                        popUpTo(Routes.PAIRING) { inclusive = true }
                    }
                },
            )
        }

        composable(Routes.PERMISSIONS) {
            PermissionFlowScreen(
                onPermissionsDone = {
                    navController.navigate(Routes.STATUS) {
                        popUpTo(Routes.PERMISSIONS) { inclusive = true }
                    }
                },
            )
        }

        composable(Routes.STATUS) {
            StatusScreen(
                captureCoordinator = captureCoordinator,
                onOpenSettings = {
                    navController.navigate(Routes.SETTINGS)
                },
                onOpenActivity = {
                    navController.navigate(Routes.MONITOR_ACTIVITY)
                },
            )
        }

        composable(Routes.SETTINGS) {
            com.shomer.client.ui.SettingsScreen(
                onBack = { navController.popBackStack() },
            )
        }

        composable(Routes.MONITOR_ACTIVITY) {
            MonitorActivityScreen(
                onBack = { navController.popBackStack() },
            )
        }

        composable(Routes.DEBUG_CLASSIFY) {
            com.shomer.client.ui.ClassifyScreen(
                onOpenSettings = { navController.navigate(Routes.SETTINGS) },
            )
        }
    }
}
