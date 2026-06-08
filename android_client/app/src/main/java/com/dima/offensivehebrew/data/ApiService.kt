@file:Suppress("PackageName")
package com.dima.offensivehebrew.data

// MIGRATED — this file is a package-rename tombstone.
//
// The POC classes ApiService, ApiFactory, and the Models/SettingsRepository
// have been moved to com.shomer.client.data.*
//
// These type aliases let any remaining code in com.dima.offensivehebrew.* compile
// without changes. New code must import from com.shomer.client.data directly.

typealias ApiService = com.shomer.client.data.ApiService
typealias MonitorApi = com.shomer.client.data.MonitorApi
typealias PairingApi = com.shomer.client.data.PairingApi
typealias ClassifyRequest = com.shomer.client.data.ClassifyRequest
typealias ClassifyResponse = com.shomer.client.data.ClassifyResponse
typealias HealthResponse = com.shomer.client.data.HealthResponse
typealias ClassifyImageResponse = com.shomer.client.data.ClassifyImageResponse
typealias SettingsRepository = com.shomer.client.data.SettingsRepository
