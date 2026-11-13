# Install the Ostium Windows client. Run from an elevated PowerShell.
param(
    [string]$InstallDir = "$env:ProgramFiles\Ostium",
    [string]$DataDir = "$env:ProgramData\Ostium",
    [string]$CoreDataDir = "$env:ProgramData\OstiumCore",
    [switch]$RunAsSystem
)

$ErrorActionPreference = "Stop"
if ($env:OS -ne "Windows_NT") { throw "Run this script on Windows." }
if (-not ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this script as Administrator."
}

$Source = Split-Path -Parent $MyInvocation.MyCommand.Path
$ServiceDir = Join-Path $InstallDir "service"
$CoreDir = Join-Path $InstallDir "core"
New-Item -ItemType Directory -Force -Path $InstallDir, $ServiceDir, $CoreDir, $DataDir, "$DataDir\runtime", "$DataDir\logs", $CoreDataDir, "$CoreDataDir\runtime", "$CoreDataDir\logs" | Out-Null
# The service runs as LocalSystem.  Keep its token, last-good config and
# database out of the user-writable ProgramData\Ostium tree; only
# Administrators and SYSTEM may write there.
icacls $CoreDataDir /inheritance:r /grant:r "SYSTEM:(OI)(CI)F" "Administrators:(OI)(CI)F" | Out-Null
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
$coreDataToml = $CoreDataDir.Replace('\', '/')
$engineToml = (Join-Path $CoreDir "sing-box.exe").Replace('\', '/')
$coreConfig = Join-Path $ServiceDir "core.toml"
$coreToml = @"
role = "client"
data_dir = "$coreDataToml"
config_dir = "$coreDataToml"
log_level = "info"
engine_version = "1.14.4-ostium.1"
engine_path = "$engineToml"
core_url = "http://127.0.0.1:8788"
"@
# File.WriteAllText emits UTF-8 without a BOM.  Windows PowerShell 5.1's
# `Set-Content -Encoding utf8` adds a BOM, which tomllib rejects.
[IO.File]::WriteAllText($coreConfig, $coreToml)

# The UI keeps its own user-writable configuration.  Keep the service's
# configuration separate so a local user cannot change engine_path.
$uiConfig = "$DataDir\config.toml"
if (-not (Test-Path $uiConfig)) {
    $uiToml = @"
role = "client"
host = "127.0.0.1"
port = 8787
data_dir = "$dataToml"
config_dir = "$dataToml"
log_level = "info"
engine_version = "1.14.4-ostium.1"
engine_path = "$engineToml"
core_url = "http://127.0.0.1:8788"
core_token_file = "$coreDataToml/runtime/core.token"
mode = "system_proxy"
"@
    [IO.File]::WriteAllText($uiConfig, $uiToml)
}

# All client platforms use the same first-run wizard; do not create an
# administrator or a plaintext password file during installation.
$env:OSTIUM_ROLE = "client"
$env:OSTIUM_DATA_DIR = $DataDir
$env:OSTIUM_CONFIG_FILE = "$DataDir\config.toml"

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
# Re-running the installer must be idempotent.  Remove the old service
# registration before installing the new one; user data lives outside the
# service definition and is preserved.
if (Get-Service -Name OstiumCore -ErrorAction SilentlyContinue) {
    Stop-Service OstiumCore -ErrorAction SilentlyContinue
    & $serviceExe remove
}
& $serviceExe --startup auto install
Start-Service OstiumCore -ErrorAction Stop

# The unprivileged UI may read the core token, but must never be able to
# overwrite it (that would let a local user hijack the privileged API).
$tokenPath = Join-Path $CoreDataDir "runtime\core.token"
for ($i = 0; $i -lt 30 -and -not (Test-Path $tokenPath); $i++) { Start-Sleep -Seconds 1 }
icacls $CoreDataDir /grant "Users:(X)" | Out-Null
icacls "$CoreDataDir\runtime" /grant "Users:(RX)" | Out-Null
if (Test-Path $tokenPath) {
    icacls $tokenPath /inheritance:r /grant:r "SYSTEM:R" "Administrators:F" "Users:R" | Out-Null
} else {
    Write-Warning "Core token not created yet; the UI may fail to authenticate until it is."
}

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
