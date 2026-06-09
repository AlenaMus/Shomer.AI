# Re-enables the Shomer.AI child-mode AccessibilityService over adb.
#
# Android disables the accessibility toggle every time the app is reinstalled
# (i.e. every Android Studio "Run"). Instead of digging through the buried
# Huawei/EMUI Accessibility menu each time, just run this script:
#
#     powershell -ExecutionPolicy Bypass -File android_client\enable-accessibility.ps1
#
# (or right-click -> Run with PowerShell). Then swipe the app closed from
# Recents and reopen it so the Status screen re-checks and goes green.

$ErrorActionPreference = "Stop"

$adb = "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe"
if (-not (Test-Path $adb)) {
    $cmd = Get-Command adb -ErrorAction SilentlyContinue
    if ($cmd) { $adb = $cmd.Source } else { Write-Host "adb not found. Install Android platform-tools or open Android Studio once." -ForegroundColor Red; exit 1 }
}

$svc = "com.shomer.client/com.shomer.client.accessibility.ShomerAccessibilityService"

# Pick the first attached device (works fine when only one phone is connected).
$devices = @(& $adb devices | Select-String "\tdevice$" | ForEach-Object { ($_ -split "\t")[0] })
if (-not $devices) { Write-Host "No device connected. Plug in the phone (USB debugging on) and retry." -ForegroundColor Red; exit 1 }
$serial = $devices[0]

& $adb -s $serial shell settings put secure enabled_accessibility_services $svc
& $adb -s $serial shell settings put secure accessibility_enabled 1
Start-Sleep -Seconds 1

$check = (& $adb -s $serial shell settings get secure enabled_accessibility_services).Trim()
if ($check -eq $svc) {
    Write-Host "Accessibility ENABLED on $serial." -ForegroundColor Green
    Write-Host "Now: swipe the app closed from Recents and reopen it -> Status goes green." -ForegroundColor Green
} else {
    Write-Host "Tried, but the value didn't stick (got: '$check'). Enable it manually under Settings -> Smart assistance -> Accessibility." -ForegroundColor Yellow
}
