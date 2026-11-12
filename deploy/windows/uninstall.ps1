# Uninstall the Ostium Windows client. Data is preserved unless -RemoveData is set.
param(
    [string]$InstallDir = "$env:ProgramFiles\Ostium",
    [string]$DataDir = "$env:ProgramData\Ostium",
    [switch]$RemoveData
)

$ErrorActionPreference = "SilentlyContinue"
Stop-Service OstiumCore
& "$InstallDir\ostium-service.exe" remove
Unregister-ScheduledTask -TaskName "Ostium" -Confirm:$false
Get-Process ostium -ErrorAction SilentlyContinue | Stop-Process -Force
if ($RemoveData) {
    Remove-Item $DataDir -Recurse -Force
}
Remove-Item $InstallDir -Recurse -Force
Write-Host "Ostium removed. Network settings were restored by the core before shutdown."
