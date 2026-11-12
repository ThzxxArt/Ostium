# Install the Ostium Windows client. Run from an elevated PowerShell.
param(
    [string]$InstallDir = "$env:ProgramFiles\Ostium",
    [string]$DataDir = "$env:ProgramData\Ostium",
    [switch]$RunAsSystem
)

$ErrorActionPreference = "Stop"
if (-not ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this script as Administrator."
}

$Source = Split-Path -Parent $MyInvocation.MyCommand.Path
New-Item -ItemType Directory -Force -Path $InstallDir, $DataDir, "$DataDir\runtime", "$DataDir\logs", "$DataDir\core" | Out-Null
Copy-Item "$Source\*" $InstallDir -Recurse -Force

# Core binary and Wintun live beside the service executable.
if (Test-Path "$Source\core\sing-box.exe") {
    Copy-Item "$Source\core\sing-box.exe" "$DataDir\core\sing-box.exe" -Force
}
if (Test-Path "$Source\core\wintun.dll") {
    Copy-Item "$Source\core\wintun.dll" "$DataDir\core\wintun.dll" -Force
}

$env:OSTIUM_ROLE = "client"
$env:OSTIUM_DATA_DIR = $DataDir
$env:OSTIUM_CONFIG_FILE = "$DataDir\config.toml"

$passwordFile = "$DataDir\initial-password.txt"
if (-not (Test-Path "$DataDir\ostium.db")) {
    $password = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 24 | ForEach-Object { [char]$_ })
    & "$InstallDir\ostium.exe" init --role client --no-input --password $password
    Set-Content -LiteralPath $passwordFile -Value $password -NoNewline -Encoding ascii
    Write-Host "Initial administrator password: $password" -ForegroundColor Yellow
    Write-Host "Saved to: $passwordFile"
    Write-Host "Store it now; it is not shown again."
}

# The UI runs as a normal user (or SYSTEM with -RunAsSystem). The wrapper
# makes the machine-wide ProgramData layout explicit.
$uiCmd = "$InstallDir\ostium-ui.cmd"
@"
@echo off
set OSTIUM_ROLE=client
set OSTIUM_DATA_DIR=$DataDir
set OSTIUM_CONFIG_FILE=$DataDir\config.toml
"$InstallDir\ostium.exe" serve
"@ | Set-Content -LiteralPath $uiCmd -Encoding ascii

# Allow the interactive user to read/write the shared client data.
icacls $DataDir /grant "$($env:USERNAME):(OI)(CI)M" | Out-Null

# Register the privileged TUN core as a Windows service (LocalSystem).
& "$InstallDir\ostium-service.exe" --startup auto install
Start-Service OstiumCore -ErrorAction SilentlyContinue

# Start the console at logon (default) or at boot as SYSTEM.
if ($RunAsSystem) {
    $action = New-ScheduledTaskAction -Execute $uiCmd
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
}
else {
    $action = New-ScheduledTaskAction -Execute $uiCmd
    $trigger = New-ScheduledTaskTrigger -AtLogOn
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
}
Register-ScheduledTask -TaskName "Ostium" -Action $action -Trigger $trigger -Principal $principal -Force | Out-Null
Start-ScheduledTask -TaskName "Ostium"

Write-Host "Ostium installed. Open http://127.0.0.1:8787" -ForegroundColor Green
