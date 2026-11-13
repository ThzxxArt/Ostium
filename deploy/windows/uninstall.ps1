# Uninstall the Ostium Windows client. Data is preserved unless -RemoveData is set.
param(
    [string]$InstallDir = "$env:ProgramFiles\Ostium",
    [string]$DataDir = "$env:ProgramData\Ostium",
    [switch]$RemoveData
)

$ErrorActionPreference = "SilentlyContinue"
$serviceExe = Join-Path $InstallDir "service\ostium-service.exe"
Stop-Service OstiumCore
if (Test-Path $serviceExe) {
    & $serviceExe remove
}
Unregister-ScheduledTask -TaskName "Ostium" -Confirm:$false
Get-Process ostium -ErrorAction SilentlyContinue | Stop-Process -Force
if ($RemoveData) {
    Remove-Item $DataDir -Recurse -Force
}
# Inno Setup removes its own installation directory and registry entry after
# [UninstallRun].  Only remove files here for the portable bundle.
if (-not (Test-Path (Join-Path $InstallDir "unins000.exe"))) {
    Remove-Item $InstallDir -Recurse -Force
}
Write-Host "Ostium removed. Network settings were restored by the core before shutdown."
