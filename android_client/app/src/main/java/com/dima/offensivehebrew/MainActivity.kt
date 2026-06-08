@file:Suppress("PackageName")
package com.dima.offensivehebrew

// This package is intentionally kept as a placeholder.
//
// Package rename: com.dima.offensivehebrew → com.shomer.client
//
// FLAVOR STRATEGY:
//   The Gradle product flavors poc + client share the same source tree rooted at
//   com.shomer.client (the build.gradle.kts namespace). The applicationId differs:
//     poc    → applicationId "com.dima.offensivehebrew"  (legacy APK identity)
//     client → applicationId "com.shomer.client"         (real app identity)
//
//   The manifest entry android:name=".MainActivity" is resolved using the namespace
//   (com.shomer.client), NOT the applicationId. So both flavors run
//   com.shomer.client.MainActivity as the launch activity regardless of which
//   applicationId the APK is signed with. This is the standard Android behavior
//   for apps that have been renamed while keeping side-by-side install capability.
//
// DEVICE UPGRADE PATH (mandatory — communicate to the user):
//   If the old POC APK (pre-flavors, applicationId = com.dima.offensivehebrew) is
//   installed on the device, it MUST be uninstalled before installing the poc flavor:
//     adb uninstall com.dima.offensivehebrew
//   Failure to uninstall produces INSTALL_FAILED_UPDATE_INCOMPATIBLE because the
//   signing certificate or source stamp changed.
//
//   After uninstall, install poc flavor:   ./gradlew installPocDebug
//   Or client flavor:                      ./gradlew installClientDebug
//
// This file contains no code — its only purpose is to document the package rename
// and flavor strategy in the location where the old POC entry point lived.
