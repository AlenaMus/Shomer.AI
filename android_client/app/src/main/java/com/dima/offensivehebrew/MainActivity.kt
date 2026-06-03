package com.dima.offensivehebrew

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Scaffold
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import com.dima.offensivehebrew.ui.ClassifyScreen
import com.dima.offensivehebrew.ui.SettingsScreen
import com.dima.offensivehebrew.ui.theme.AppTheme

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            AppTheme {
                var showSettings by remember { mutableStateOf(false) }
                Scaffold { padding ->
                    if (showSettings) {
                        SettingsScreen(
                            modifier = Modifier.padding(padding),
                            onBack = { showSettings = false },
                        )
                    } else {
                        ClassifyScreen(
                            modifier = Modifier.padding(padding),
                            onOpenSettings = { showSettings = true },
                        )
                    }
                }
            }
        }
    }
}
