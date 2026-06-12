package com.shomer.client.di

import android.content.Context
import com.shomer.client.capture.EventDao
import com.shomer.client.capture.EventDatabase
import com.shomer.client.capture.PreFilter
import com.shomer.client.data.ApiService
import com.shomer.client.data.AuthInterceptor
import com.shomer.client.data.BaseUrlInterceptor
import com.shomer.client.data.MonitorApi
import com.shomer.client.data.PairingApi
import com.shomer.client.data.SettingsRepository
import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.moshi.MoshiConverterFactory
import java.util.concurrent.TimeUnit
import javax.inject.Singleton

/**
 * Hilt module providing all network, database, and repository singletons.
 *
 * LAN networking notes:
 *   - Emulator default: http://10.0.2.2:8000/ (10.0.2.2 = host from inside the AVD)
 *   - Physical phone:   http://<PC-LAN-IP>:8000/ (user configures in Settings)
 *   - Cleartext permitted by network_security_config.xml (dev only; HTTPS for prod)
 *
 * Base URL limitation: Retrofit is constructed once at Hilt SingletonComponent init
 * with the stored server URL. Changing the URL in Settings takes effect on next cold
 * start. A dynamic URL interceptor is the production solution (deferred to A6).
 */
@Module
@InstallIn(SingletonComponent::class)
object NetworkModule {

    @Provides
    @Singleton
    fun provideMoshi(): Moshi = Moshi.Builder()
        .add(KotlinJsonAdapterFactory())
        .build()

    @Provides
    @Singleton
    fun provideOkHttpClient(
        authInterceptor: AuthInterceptor,
        baseUrlInterceptor: BaseUrlInterceptor,
    ): OkHttpClient {
        val logging = HttpLoggingInterceptor().apply {
            // BODY-level logging for the MVP. Set Level.NONE in production to avoid
            // logging captured message text to logcat.
            level = HttpLoggingInterceptor.Level.BODY
        }
        return OkHttpClient.Builder()
            // baseUrlInterceptor first: it rewrites host/port to the live setting,
            // so a URL change in Settings/onboarding applies without an app restart.
            .addInterceptor(baseUrlInterceptor)
            .addInterceptor(logging)
            .addInterceptor(authInterceptor)
            .connectTimeout(30, TimeUnit.SECONDS)
            .readTimeout(60, TimeUnit.SECONDS)
            .writeTimeout(30, TimeUnit.SECONDS)
            .build()
    }

    @Provides
    @Singleton
    fun provideRetrofit(
        okHttpClient: OkHttpClient,
        moshi: Moshi,
        settingsRepository: SettingsRepository,
    ): Retrofit {
        // Read the stored base URL once at Hilt init time (SingletonComponent).
        // runBlocking here is safe: this executes during app startup on the main
        // thread before any UI is shown, and DataStore reads are fast (in-memory
        // after first access).
        val rawUrl = runBlocking { settingsRepository.serverUrl.first() }
        val baseUrl = if (rawUrl.endsWith("/")) rawUrl else "$rawUrl/"
        return Retrofit.Builder()
            .baseUrl(baseUrl)
            .client(okHttpClient)
            .addConverterFactory(MoshiConverterFactory.create(moshi))
            .build()
    }

    @Provides
    @Singleton
    fun provideMonitorApi(retrofit: Retrofit): MonitorApi =
        retrofit.create(MonitorApi::class.java)

    @Provides
    @Singleton
    fun providePairingApi(retrofit: Retrofit): PairingApi =
        retrofit.create(PairingApi::class.java)

    @Provides
    @Singleton
    fun provideApiService(retrofit: Retrofit): ApiService =
        retrofit.create(ApiService::class.java)

    @Provides
    @Singleton
    fun provideEventDatabase(@ApplicationContext context: Context): EventDatabase =
        EventDatabase.getInstance(context)

    @Provides
    @Singleton
    fun provideEventDao(database: EventDatabase): EventDao =
        database.eventDao()

    @Provides
    @Singleton
    fun providePreFilter(): PreFilter = PreFilter()
}
