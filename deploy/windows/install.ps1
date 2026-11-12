# Install the Ostium Windows client. Run from an elevated PowerShell.
param(
    [string]$InstallDir = "$env:ProgramFiles\Ostium",
    [string]$DataDir = "$env:ProgramData\Ostium"
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

if (-not (Test-Path "$DataDir\ostium.db")) {
    $password = -join ((48..57) + (65..90) + (97..122) | Get-Random -Count 24 | ForEach-Object { [char]$_ })
    & "$InstallDir\ostium.exe" init --role client --no-input --password $password
    Write-Host "Initial administrator password: $password" -ForegroundColor Yellow
    Write-Host "Store it now; it is not shown again."
}

# Register the privileged TUN core as a Windows service.
& "$InstallDir\ostium-service.exe" --startup auto install
Start-Service OstiumCore -ErrorAction SilentlyContinue

# Start the unprivileged console at logon for the current user.
$action = New-ScheduledTaskAction -Execute "$InstallDir\ostium.exe" -Argument "serve"
$trigger = New-ScheduledTaskTrigger -AtLogOn
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName "Ostium" -Action $action -Trigger $trigger -Principal $principal -Force | Out-Null
Start-Process "$InstallDir\ostium.exe" -ArgumentList "serve" -WindowStyle Hidden

Write-Host "Ostium installed. Open http://127.0.0.1:8787" -ForegroundColor Green
