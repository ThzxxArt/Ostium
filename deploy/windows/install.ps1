# Install the Ostium Windows client. Run from an elevated PowerShell.
param(
    [string]$InstallDir = "$env:ProgramFiles\Ostium",
    [string]$DataDir = "$env:ProgramData\Ostium",
    [string]$CoreDataDir = "$env:ProgramData\OstiumCore",
    [switch]$RunAsSystem,
    [switch]$SkipPathUpdate
)

$ErrorActionPreference = "Stop"
if ($env:OS -ne "Windows_NT") { throw "Run this script on Windows." }
if (-not ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this script as Administrator."
}

function Update-MachineEnvironment {
    # Explorer and new shells cache the machine environment.  Broadcast the
    # documented WM_SETTINGCHANGE message so a freshly opened terminal can
    # resolve `ostium` without requiring a reboot or sign-out.
    if (-not ([System.Management.Automation.PSTypeName]'Ostium.NativeEnvironment').Type) {
        Add-Type -Namespace Ostium -Name NativeEnvironment -MemberDefinition @'
[DllImport("user32.dll", SetLastError = true, CharSet = CharSet.Auto)]
public static extern IntPtr SendMessageTimeout(IntPtr hWnd, uint Msg, UIntPtr wParam, string lParam, uint fuFlags, uint uTimeout, out UIntPtr lpdwResult);
'@
    }
    $result = [UIntPtr]::Zero
    [void][Ostium.NativeEnvironment]::SendMessageTimeout(
        [IntPtr]0xffff, 0x1A, [UIntPtr]::Zero, 'Environment', 2, 5000, [ref]$result
    )
}

function Add-MachinePathEntry {
    param([Parameter(Mandatory = $true)][string]$Directory)
    $key = [Microsoft.Win32.Registry]::LocalMachine.OpenSubKey(
        'SYSTEM\CurrentControlSet\Control\Session Manager\Environment', $true
    )
    if (-not $key) { throw "Could not open the machine PATH registry key" }
    try {
        $current = [string]$key.GetValue(
            'Path', '', [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames
        )
        $entry = $Directory.TrimEnd([char[]]'\')
        $parts = @($current -split ';' | Where-Object { $_ -and $_.Trim() })
        $present = $false
        foreach ($part in $parts) {
            if ($part.Trim().TrimEnd([char[]]'\') -ieq $entry) { $present = $true; break }
        }
        if (-not $present) {
            $parts += $entry
            $kind = $key.GetValueKind('Path')
            $key.SetValue('Path', ($parts -join ';'), $kind)
        }
    } finally {
        $key.Close()
    }
    $pathParts = @($env:Path -split ';' | Where-Object { $_ -and $_.Trim() })
    if (-not ($pathParts | Where-Object { $_.Trim().TrimEnd([char[]]'\') -ieq $Directory.TrimEnd([char[]]'\') })) {
        $env:Path = "$($env:Path);$Directory"
    }
    Update-MachineEnvironment
}

$Source = Split-Path -Parent $MyInvocation.MyCommand.Path
$ServiceDir = Join-Path $InstallDir "service"
$CoreDir = Join-Path $InstallDir "core"
New-Item -ItemType Directory -Force -Path $InstallDir, $ServiceDir, $CoreDir, $DataDir, "$DataDir\runtime", "$DataDir\logs", $CoreDataDir, "$CoreDataDir\runtime", "$CoreDataDir\logs" | Out-Null
# The service runs as LocalSystem.  Keep its token, last-good config and
# database out of the user-writable ProgramData\Ostium tree; only
# Administrators and SYSTEM may write there.
icacls $CoreDataDir /inheritance:r /grant:r "*S-1-5-18:(OI)(CI)F" "*S-1-5-32-544:(OI)(CI)F" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Could not lock down $CoreDataDir" }
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

# The UI runs as a normal user (or SYSTEM with -RunAsSystem). The wrappers
# make the machine-wide ProgramData layout explicit.  Keep a log next to the
# database: a scheduled task has no visible console, so a startup failure was
# previously indistinguishable from the server simply not being installed.
$uiCmd = "$InstallDir\ostium-ui.cmd"
$uiScript = "$InstallDir\ostium-ui.ps1"
$uiLog = "$DataDir\logs\ui.log"
$uiCmdContent = @"
@echo off
set "OSTIUM_ROLE=client"
set "OSTIUM_DATA_DIR=$DataDir"
set "OSTIUM_CONFIG_FILE=$DataDir\config.toml"
set "OSTIUM_ENGINE_PATH=$CoreDir\sing-box.exe"
echo [%DATE% %TIME%] starting Ostium UI>> "$uiLog"
"$InstallDir\ostium.exe" serve >> "$uiLog" 2>&1
echo [%DATE% %TIME%] Ostium UI exited with code %ERRORLEVEL%>> "$uiLog"
"@
Set-Content -LiteralPath $uiCmd -Value $uiCmdContent -Encoding ascii

# Task Scheduler must launch the UI through a real executable.  A .cmd file is
# not a valid CreateProcess image on every Windows version, which left the
# task registered but never started the server.  PowerShell also keeps the
# console window hidden for a logon task.
$uiScriptTemplate = @'
$ErrorActionPreference = "Stop"
$env:OSTIUM_ROLE = "client"
$env:OSTIUM_DATA_DIR = "__DATA_DIR__"
$env:OSTIUM_CONFIG_FILE = "__DATA_DIR__\config.toml"
$env:OSTIUM_ENGINE_PATH = "__INSTALL_DIR__\core\sing-box.exe"
$log = "__DATA_DIR__\logs\ui.log"
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $log) | Out-Null
"[$(Get-Date -Format o)] starting Ostium UI" | Out-File -LiteralPath $log -Append -Encoding utf8
try {
    & "__INSTALL_DIR__\ostium.exe" serve *>> $log
    $code = $LASTEXITCODE
} catch {
    $_ | Out-String | Out-File -LiteralPath $log -Append -Encoding utf8
    $code = 1
}
"[$(Get-Date -Format o)] Ostium UI exited with code $code" | Out-File -LiteralPath $log -Append -Encoding utf8
exit $code
'@
$uiScriptContent = $uiScriptTemplate.Replace('__DATA_DIR__', $DataDir).Replace('__INSTALL_DIR__', $InstallDir)
[IO.File]::WriteAllText($uiScript, $uiScriptContent, (New-Object System.Text.UTF8Encoding($false)))

if (-not $SkipPathUpdate) {
    try {
        Add-MachinePathEntry -Directory $InstallDir
    } catch {
        # PATH is a convenience; do not fail an otherwise working UI install
        # because a locked-down registry policy rejected the update.
        Write-Warning "Could not add $InstallDir to the machine PATH: $_"
    }
}

# Allow only SYSTEM, Administrators and the interactive user to read/write the
# shared client data.  Without /inheritance:r ProgramData's default inherited
# read ACE lets every local account read ostium.db and master.key.
$userAccount = if ($env:USERDOMAIN) { "$env:USERDOMAIN\$env:USERNAME" } else { $env:USERNAME }
if (-not $userAccount) { throw "Could not determine the interactive user account for the core token ACL" }
icacls $DataDir /inheritance:r /grant:r `
    "*S-1-5-18:(OI)(CI)F" `
    "*S-1-5-32-544:(OI)(CI)F" `
    "${userAccount}:(OI)(CI)M" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Could not lock down $DataDir" }

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
    if ($LASTEXITCODE -ne 0) { throw "Could not remove the previous OstiumCore service" }
}
& $serviceExe --startup auto install
if ($LASTEXITCODE -ne 0) { throw "Could not install the OstiumCore service" }
Start-Service OstiumCore -ErrorAction Stop

# The unprivileged UI may read the core token, but must never be able to
# overwrite it (that would let a local user hijack the privileged API).
$tokenPath = Join-Path $CoreDataDir "runtime\core.token"
for ($i = 0; $i -lt 30 -and -not (Test-Path $tokenPath); $i++) { Start-Sleep -Seconds 1 }
# Only the installing interactive user gets access.  Granting the built-in
# Users group would let every local account read the bearer token and control
# the LocalSystem core.
icacls $CoreDataDir /grant "${userAccount}:(X)" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Could not grant $userAccount traverse access to $CoreDataDir" }
icacls "$CoreDataDir\runtime" /grant "${userAccount}:(RX)" | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Could not grant $userAccount read access to the core runtime" }
if (Test-Path $tokenPath) {
    icacls $tokenPath /inheritance:r /grant:r "*S-1-5-18:R" "*S-1-5-32-544:F" "${userAccount}:R" | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Could not secure the core token ACL" }
} else {
    Write-Warning "Core token not created yet; the UI may fail to authenticate until it is."
}

# Start the console at logon (default) or at boot as SYSTEM.
if ($RunAsSystem) {
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
}
else {
    $trigger = New-ScheduledTaskTrigger -AtLogOn
    $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
}
$powerShell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
$action = New-ScheduledTaskAction `
    -Execute $powerShell `
    -Argument "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$uiScript`"" `
    -WorkingDirectory $InstallDir
Unregister-ScheduledTask -TaskName "Ostium" -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName "Ostium" -Action $action -Trigger $trigger -Principal $principal -Force | Out-Null
Start-ScheduledTask -TaskName "Ostium"

# Do not report success before the UI actually answers.  The old installer
# returned immediately, so a broken scheduled task or a missing web bundle
# looked like a successful install and the browser showed a connection error.
$healthUrl = "http://127.0.0.1:8787/healthz"
$ready = $false
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 1
    try {
        # Bypass any stale system proxy: a previous install may have pointed
        # WinINET at a core that is currently stopped, which would make the
        # loopback health check fail through no fault of the new UI.
        $request = [System.Net.WebRequest]::Create($healthUrl)
        $request.Proxy = $null
        $request.Timeout = 2000
        $response = [System.Net.HttpWebResponse]$request.GetResponse()
        try {
            $ready = $response.StatusCode -eq [System.Net.HttpStatusCode]::OK
        } finally {
            $response.Close()
        }
        if ($ready) { break }
    } catch {
        # The task may still be starting; retry until the deadline.
    }
}
if (-not $ready) {
    $task = Get-ScheduledTask -TaskName "Ostium" -ErrorAction SilentlyContinue
    $info = Get-ScheduledTaskInfo -TaskName "Ostium" -ErrorAction SilentlyContinue
    $tail = ""
    if (Test-Path $uiLog) {
        $lines = Get-Content -LiteralPath $uiLog -Tail 20 -ErrorAction SilentlyContinue
        if ($lines) { $tail = $lines -join [Environment]::NewLine }
    }
    throw "Ostium UI did not become ready at $healthUrl. Task state: $($task.State); last result: $($info.LastTaskResult). Log: $uiLog`n$tail"
}

Write-Host "Ostium installed. Open http://127.0.0.1:8787" -ForegroundColor Green
Write-Host "CLI: ostium (open a new terminal so PATH picks up $InstallDir)" -ForegroundColor Green
Write-Host "Startup log: $uiLog" -ForegroundColor Green
