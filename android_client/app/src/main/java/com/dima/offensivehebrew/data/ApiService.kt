package com.dima.offensivehebrew.data

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.moshi.MoshiConverterFactory
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.Multipart
import retrofit2.http.POST
import retrofit2.http.Part
import retrofit2.http.Query
import java.util.concurrent.TimeUnit

interface ApiService {
    @GET("health")
    suspend fun health(): HealthResponse

    @POST("classify")
    suspend fun classify(@Body request: ClassifyRequest): ClassifyResponse

    /**
     * Phase 1: upload an image as multipart/form-data. The form-field name
     * ("image") must match the FastAPI parameter name. `strategy` is wired
     * for Phase 2's backend router; Phase 1 server ignores it.
     */
    @Multipart
    @POST("classify-image")
    suspend fun classifyImage(
        @Part image: MultipartBody.Part,
        @Query("strategy") strategy: String? = null,
    ): ClassifyImageResponse
}

object ApiFactory {
    fun create(baseUrl: String): ApiService {
        val moshi = Moshi.Builder().add(KotlinJsonAdapterFactory()).build()
        val logging = HttpLoggingInterceptor().apply { level = HttpLoggingInterceptor.Level.BODY }
        val client = OkHttpClient.Builder()
            .addInterceptor(logging)
            .connectTimeout(10, TimeUnit.SECONDS)
            .readTimeout(60, TimeUnit.SECONDS)
            .build()
        return Retrofit.Builder()
            .baseUrl(baseUrl.normalizedBaseUrl())
            .client(client)
            .addConverterFactory(MoshiConverterFactory.create(moshi))
            .build()
            .create(ApiService::class.java)
    }

    private fun String.normalizedBaseUrl(): String =
        if (endsWith("/")) this else "$this/"
}
