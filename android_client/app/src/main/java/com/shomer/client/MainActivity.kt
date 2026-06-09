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
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import com.shomer.client.capture.CaptureCoordinator
import com.shomer.client.data.SettingsRepository
import com.shomer.client.data.TokenStore
import com.shomer.client.onboarding.ConsentScreen
import com.shomer.client.onboarding.MonitorActivityScreen
import com.shomer.client.onboarding.OnboardingViewModel
import com.shomer.client.onboarding.PairingScreen
import com.shomer.client.onboarding.PermissionFlowScreen
import com.shomer.client.onboarding.StatusScreen
import com.shomer.client.parent.AlertDetailScreen
import com.shomer.client.parent.AlertListScreen
import com.shomer.client.parent.DigestScreen
import com.shomer.client.parent.ParentAuthScreen
import com.shomer.client.parent.RoleChooserScreen
import com.shomer.client.ui.theme.AppTheme
import dagger.hilt.android.AndroidEntryPoint
import javax.inject.Inject

// ---------------------------------------------------------------------------
// Navigation route constants
// ---------------------------------------------------------------------------
private object Routes {
    // Shared / startup
    const val ROLE_CHOOSER = "role_chooser"

    // Child-mode flow
    const val CONSENT = "consent"
    const val PAIRING = "pairing"
    const val PERMISSIONS = "permissions"
    const val STATUS = "status"
    const val SETTINGS = "settings"
    const val MONITOR_ACTIVITY = "monitor_activity"
    const val DEBUG_CLASSIFY = "debug_classify"

    // Parent-mode flow
    const val PARENT_AUTH = "parent_auth"
    const val ALERT_LIST = "alert_list"
    const val ALERT_DETAIL = "alert_detail/{flag_id}"
    const val DIGEST = "digest"

    fun alertDetail(flagId: String) = "alert_detail/$flagId"
}

/**
 * Single-Activity host. Compose Navigation handles all screen routing.
 *
 * Routing logic on startup:
 *
 *   First launch (no role stored):
 *     → ROLE_CHOOSER (user picks "I am a Parent" or "This is my child's device")
 *
 *   Child-mode (role=="child" or legacy: consented + not paired):
 *     Not consented  → CONSENT → PAIRING → PERMISSIONS → STATUS
 *     Not paired     → PAIRING → PERMISSIONS → STATUS
 *     Paired         → STATUS (home)
 *
 *   Parent-mode (role=="parent"):
 *     Not paired (no token) → PARENT_AUTH → ALERT_LIST
 *     Paired (has token)    → ALERT_LIST (home)
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

        // If this device is already paired, make sure the recurring upload loop is
        // running — it's otherwise only started right after pairing / on reboot, so a
        // plain app reopen would leave buffered events un-flushed until the next capture.
        if (tokenStore.isPaired()) {
            com.shomer.client.monitor.MonitorUploader.startUploadLoop(this)
        }

        val role = tokenStore.getRole()
        val startDest = when {
            role == null -> Routes.ROLE_CHOOSER      // fresh install — pick role
            role == TokenStore.ROLE_PARENT -> {
                if (tokenStore.isPaired()) Routes.ALERT_LIST else Routes.PARENT_AUTH
            }
            else -> {
                // child role (or legacy unset-role state)
                when {
                    !tokenStore.hasConsented() -> Routes.CONSENT
                    !tokenStore.isPaired() -> Routes.PAIRING
                    else -> Routes.STATUS
                }
            }
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
        // Shared: role chooser (shown on first launch when role is not set)
        // -----------------------------------------------------------------------
        composable(Routes.ROLE_CHOOSER) {
            RoleChooserScreen(
                onChooseChild = {
                    navController.navigate(Routes.CONSENT) {
                        popUpTo(Routes.ROLE_CHOOSER) { inclusive = true }
                    }
                },
                onChooseParent = {
                    navController.navigate(Routes.PARENT_AUTH) {
                        popUpTo(Routes.ROLE_CHOOSER) { inclusive = true }
                    }
                },
            )
        }

        // -----------------------------------------------------------------------
        // Child-mode flow
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

        // -----------------------------------------------------------------------
        // Parent-mode flow
        // -----------------------------------------------------------------------
        composable(Routes.PARENT_AUTH) {
            ParentAuthScreen(
                onAuthDone = {
                    navController.navigate(Routes.ALERT_LIST) {
                        popUpTo(Routes.PARENT_AUTH) { inclusive = true }
                    }
                },
            )
        }

        composable(Routes.ALERT_LIST) {
            AlertListScreen(
                onAlertClick = { flagId ->
                    navController.navigate(Routes.alertDetail(flagId))
                },
                onOpenDigest = {
                    navController.navigate(Routes.DIGEST)
                },
            )
        }

        composable(
            route = Routes.ALERT_DETAIL,
            arguments = listOf(navArgument("flag_id") { type = NavType.StringType }),
        ) { backStackEntry ->
            val flagId = backStackEntry.arguments?.getString("flag_id") ?: return@composable
            AlertDetailScreen(
                flagId = flagId,
                onBack = { navController.popBackStack() },
            )
        }

        composable(Routes.DIGEST) {
            DigestScreen(
                onBack = { navController.popBackStack() },
            )
        }
    }
}
