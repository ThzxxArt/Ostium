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
$ServiceDir = Join-Path $InstallDir "service"
$CoreDir = Join-Path $InstallDir "core"
New-Item -ItemType Directory -Force -Path $InstallDir, $ServiceDir, $CoreDir, $DataDir, "$DataDir\runtime", "$DataDir\logs" | Out-Null
# Inno Setup already copied the bundle into $InstallDir before running this
# script.  Copying a directory onto itself makes PowerShell fail, so only do
# the copy for the portable/zip workflow where source and destination differ.
$sourceFull = [IO.Path]::GetFullPath($Source).TrimEnd([char[]]('\', '/'))
$installFull = [IO.Path]::GetFullPath($InstallDir).TrimEnd([char[]]('\', '/'))
if ($sourceFull -ne $installFull) {
    Copy-Item "$Source\*" $InstallDir -Recurse -Force
}

# Core binaries live under the admin-only Program Files tree.  The privileged
# service must never execute a binary from a directory the interactive user can
# modify.
$dataToml = $DataDir.Replace('\', '/')
$engineToml = (Join-Path $CoreDir "sing-box.exe").Replace('\', '/')
$coreConfig = Join-Path $ServiceDir "core.toml"
@"
role = "client"
data_dir = "$dataToml"
config_dir = "$dataToml"
log_level = "info"
engine_version = "1.14.4-ostium.1"
engine_path = "$engineToml"
core_url = "http://127.0.0.1:8788"
"@ | Set-Content -LiteralPath $coreConfig -Encoding utf8

# The UI keeps its own user-writable configuration.  Keep the service's
# configuration separate so a local user cannot change engine_path.
$uiConfig = "$DataDir\config.toml"
if (-not (Test-Path $uiConfig)) {
    @"
role = "client"
host = "127.0.0.1"
port = 8787
data_dir = "$dataToml"
config_dir = "$dataToml"
log_level = "info"
engine_version = "1.14.4-ostium.1"
engine_path = "$engineToml"
core_url = "http://127.0.0.1:8788"
mode = "system_proxy"
"@ | Set-Content -LiteralPath $uiConfig -Encoding utf8
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
set "OSTIUM_ROLE=client"
set "OSTIUM_DATA_DIR=$DataDir"
set "OSTIUM_CONFIG_FILE=$DataDir\config.toml"
set "OSTIUM_ENGINE_PATH=$CoreDir\sing-box.exe"
"$InstallDir\ostium.exe" serve
"@ | Set-Content -LiteralPath $uiCmd -Encoding ascii

# Allow the interactive user to read/write the shared client data.
$userAccount = if ($env:USERDOMAIN) { "$env:USERDOMAIN\$env:USERNAME" } else { $env:USERNAME }
icacls $DataDir /grant "${userAccount}:(OI)(CI)M" | Out-Null

# Register the privileged TUN core as a Windows service (LocalSystem).
$serviceExe = Join-Path $ServiceDir "ostium-service.exe"
if (-not (Test-Path $serviceExe)) {
    throw "Ostium service executable is missing: $serviceExe"
}
& $serviceExe --startup auto install
Start-Service OstiumCore -ErrorAction Stop

# Start the console at logon (default) or at boot as SYSTEM.
if ($RunAsSystem) {
    $action = New-ScheduledTaskAction -Execute $uiCmd
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
}
else {
    $action = New-ScheduledTaskAction -Execute $uiCmd
    $trigger = New-ScheduledTaskTrigger -AtLogOn
    $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
}
Unregister-ScheduledTask -TaskName "Ostium" -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName "Ostium" -Action $action -Trigger $trigger -Principal $principal -Force | Out-Null
Start-ScheduledTask -TaskName "Ostium"

Write-Host "Ostium installed. Open http://127.0.0.1:8787" -ForegroundColor Green
