plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
    id("com.google.devtools.ksp")
    id("com.google.dagger.hilt.android")
}

android {
    // The real client namespace; keeps the XML-generated R class under com.shomer.client.
    namespace = "com.shomer.client"
    compileSdk = 35

    defaultConfig {
        // Base applicationId for the 'client' flavor (no suffix).
        // IMPORTANT: switching applicationId on a device requires an APK uninstall first —
        // 'adb uninstall com.dima.offensivehebrew' before installing any flavor of this build.
        applicationId = "com.shomer.client"
        minSdk = 24
        targetSdk = 35
        versionCode = 1
        versionName = "1.0.0"
    }

    // -------------------------------------------------------------------------
    // Product flavors — two flavors share a single 'stage' dimension so the POC
    // and the real client can be installed side-by-side during transition.
    //
    //   poc    → applicationId "com.dima.offensivehebrew" (legacy POC artifact)
    //   client → applicationId "com.shomer.client"        (real monitoring app)
    //
    // Both flavors share all sources (no src/poc / src/client split needed for
    // now). The POC classify/settings screens remain available in both flavors
    // as a built-in debug / server-test aid.
    // -------------------------------------------------------------------------
    flavorDimensions += "stage"
    productFlavors {
        create("poc") {
            dimension = "stage"
            // Preserve the old artifact so the POC apk can coexist on the device.
            applicationId = "com.dima.offensivehebrew"
            versionNameSuffix = "-poc"
            resValue("string", "app_name", "Shomer POC")
        }
        create("client") {
            dimension = "stage"
            // Uses the base applicationId = "com.shomer.client" — no suffix.
            resValue("string", "app_name", "Shomer.AI")
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }

    buildFeatures {
        compose = true
        buildConfig = true
    }
    packaging {
        resources.excludes += "/META-INF/{AL2.0,LGPL2.1}"
    }
}

dependencies {
    val composeBom = platform("androidx.compose:compose-bom:2024.10.00")
    implementation(composeBom)
    androidTestImplementation(composeBom)

    // Core Android + Lifecycle
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.6")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.8.6")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.8.6")
    implementation("androidx.activity:activity-compose:1.9.3")

    // Compose UI + Material 3
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.material:material-icons-extended")
    debugImplementation("androidx.compose.ui:ui-tooling")

    // Navigation
    implementation("androidx.navigation:navigation-compose:2.8.3")

    // DataStore (settings / server URL)
    implementation("androidx.datastore:datastore-preferences:1.1.1")

    // Hilt DI
    implementation("com.google.dagger:hilt-android:2.51.1")
    ksp("com.google.dagger:hilt-android-compiler:2.51.1")
    implementation("androidx.hilt:hilt-navigation-compose:1.2.0")

    // WorkManager (MonitorUploader)
    implementation("androidx.work:work-runtime-ktx:2.9.1")
    implementation("androidx.hilt:hilt-work:1.2.0")
    ksp("androidx.hilt:hilt-compiler:1.2.0")

    // Room (EncryptedEventBuffer)
    implementation("androidx.room:room-runtime:2.6.1")
    implementation("androidx.room:room-ktx:2.6.1")
    ksp("androidx.room:room-compiler:2.6.1")

    // Encrypted storage (TokenStore — EncryptedSharedPreferences)
    implementation("androidx.security:security-crypto:1.1.0-alpha06")

    // Networking — Retrofit + OkHttp + Moshi (reused from POC)
    implementation("com.squareup.retrofit2:retrofit:2.11.0")
    implementation("com.squareup.retrofit2:converter-moshi:2.11.0")
    // moshi-kotlin provides the KotlinJsonAdapterFactory (reflection-based adapter).
    // We use reflection only — do NOT add moshi-kotlin-codegen KSP alongside it;
    // having both in the same build causes KSP codegen to fail on @JsonClass annotations.
    implementation("com.squareup.moshi:moshi-kotlin:1.15.1")
    implementation("com.squareup.okhttp3:logging-interceptor:4.12.0")

    // Image loading (Coil — kept from POC, used in debug classify screen)
    implementation("io.coil-kt:coil-compose:2.7.0")

    // Coroutines
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")

    // Testing
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.jetbrains.kotlinx:kotlinx-coroutines-test:1.9.0")
    androidTestImplementation("androidx.test.ext:junit:1.2.1")
    androidTestImplementation("androidx.compose.ui:ui-test-junit4")
}
