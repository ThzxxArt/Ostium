# Install the Ostium Windows client. Run from an elevated PowerShell.
param(
    [string]$InstallDir = "$env:ProgramFiles\Ostium",
    [string]$DataDir = "$env:ProgramData\Ostium",
    [string]$CoreDataDir = "$env:ProgramData\OstiumCore",
    [string]$ExpectedVersion = "",
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
$installLog = "$DataDir\logs\install.log"

function Read-ExpectedVersion {
    if ($ExpectedVersion) { return $ExpectedVersion.TrimStart("v") }
    $versionFile = Join-Path $InstallDir "VERSION"
    if (Test-Path $versionFile) {
        $value = (Get-Content -LiteralPath $versionFile -TotalCount 1).Trim()
        if ($value) { return $value.TrimStart("v") }
    }
    return ""
}

function Get-ConfiguredUiPort {
    $config = Join-Path $DataDir "config.toml"
    if (Test-Path $config) {
        foreach ($line in Get-Content -LiteralPath $config) {
            if ($line -match '^\s*port\s*=\s*(\d{1,5})\s*$') {
                return [int]$Matches[1]
            }
        }
    }
    return 8787
}

function Get-PortOwner([int]$Port) {
    $connection = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $connection) { return $null }
    $process = Get-Process -Id $connection.OwningProcess -ErrorAction SilentlyContinue
    return [pscustomobject]@{
        Port = $Port
        Pid = [int]$connection.OwningProcess
        Name = if ($process) { $process.ProcessName } else { "" }
        Path = if ($process) { $process.Path } else { "" }
        StartTime = if ($process) { $process.StartTime } else { $null }
    }
}

function Test-OstiumOwnedProcess($Owner) {
    if (-not $Owner) { return $false }
    $knownNames = @("ostium", "ostium-service", "ostium-service.exe", "sing-box", "sing-box.exe")
    if ($knownNames -contains $Owner.Name) { return $true }
    if (-not $Owner.Path) { return $false }
    $roots = @(
        [IO.Path]::GetFullPath($InstallDir),
        [IO.Path]::GetFullPath($DataDir),
        [IO.Path]::GetFullPath($CoreDataDir),
        [IO.Path]::GetFullPath("$env:ProgramFiles\Ostium"),
        [IO.Path]::GetFullPath("$env:ProgramData\Ostium"),
        [IO.Path]::GetFullPath("$env:ProgramData\OstiumCore")
    )
    $candidate = [IO.Path]::GetFullPath($Owner.Path)
    foreach ($root in $roots) {
        if ($candidate.StartsWith($root.TrimEnd([char[]]('\', '/')) + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
            return $true
        }
    }
    return $false
}

function Stop-PreviousOstium([int]$Port) {
    $owner = Get-PortOwner $Port
    if (-not $owner) { return }
    if (-not (Test-OstiumOwnedProcess $owner)) {
        throw ("Port {0} is already owned by pid {1} ({2} at {3}). Refusing to install over an unknown process; stop it or change the UI port." -f `
            $owner.Port, $owner.Pid, $owner.Name, $owner.Path)
    }
    Write-InstallLog ("stopping previous Ostium listener pid={0} path={1} on port {2}" -f $owner.Pid, $owner.Path, $owner.Port)
    Stop-Process -Id $owner.Pid -Force -ErrorAction SilentlyContinue
    for ($i = 0; $i -lt 15; $i++) {
        Start-Sleep -Milliseconds 400
        if (-not (Get-PortOwner $Port)) { return }
    }
    throw "Previous Ostium process did not release port $Port"
}
function Write-InstallLog {
    param([string]$Message)
    # Interactive installs run this script in a visible console; keep the same
    # lines on screen so the service step is not a black box.  Silent installs
    # run the script hidden and still get the file log.
    Write-Host "[Ostium] $Message"
    try {
        "[$(Get-Date -Format o)] $Message" |
            Out-File -LiteralPath $installLog -Append -Encoding utf8
    } catch {
        # Diagnostics are best-effort and must not fail the install.
    }
}
Write-InstallLog "install.ps1 started for $InstallDir"

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

$ExpectedVersion = Read-ExpectedVersion
if (-not $ExpectedVersion) {
    throw "The installer bundle does not contain a VERSION file and -ExpectedVersion was not provided; refusing to report success without a version assertion."
}
$UiPort = Get-ConfiguredUiPort
Write-InstallLog "expected version $ExpectedVersion; UI port $UiPort"

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
# Native tools write progress to stderr.  With ErrorActionPreference=Stop,
# PowerShell turns uvicorn's normal INFO lines into a terminating error and
# kills the UI child.  Keep Continue here; the exit code is checked below.
$ErrorActionPreference = "Continue"
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
$serviceStarted = $false
if (Get-Service -Name OstiumCore -ErrorAction SilentlyContinue) {
    Stop-Service OstiumCore -ErrorAction SilentlyContinue
    & $serviceExe remove
    if ($LASTEXITCODE -ne 0) {
        Write-InstallLog "Could not remove the previous OstiumCore service (exit $LASTEXITCODE)"
        Write-Warning "Could not remove the previous OstiumCore service; continuing with the UI install."
    }
}
# A failed uninstall can leave the old service or its sing-box child running;
# it would keep port 8788 occupied and make the new service exit immediately.
Get-Process ostium-service, sing-box -ErrorAction SilentlyContinue |
    Stop-Process -Force -ErrorAction SilentlyContinue
# Image-name cleanup misses `python.exe -m ostium serve`, which is exactly the
# process that made an old release keep answering /healthz after an upgrade.
Stop-PreviousOstium $UiPort
if ($UiPort -ne 8788) { Stop-PreviousOstium 8788 }
Write-InstallLog "installing OstiumCore service"
& $serviceExe --startup auto install
if ($LASTEXITCODE -ne 0) {
    Write-InstallLog "Could not install the OstiumCore service (exit $LASTEXITCODE)"
    Write-Warning "Could not install the OstiumCore service; the UI will still be installed."
} else {
    try {
        Start-Service OstiumCore -ErrorAction Stop
        $serviceStarted = $true
        Write-InstallLog "OstiumCore service running"
    } catch {
        # The UI is still useful without TUN: it can show first-run setup and
        # diagnostics.  Do not abort before registering the UI task, otherwise
        # the browser gets a generic connection-refused error with no way to
        # inspect the failure.
        $failure = $_.Exception.Message
        Write-InstallLog "OstiumCore failed to start: $failure"
        try {
            $service = Get-Service -Name OstiumCore -ErrorAction SilentlyContinue
            Write-InstallLog "OstiumCore state: $($service.Status)"
        } catch {}
        try {
            $serviceConfig = & sc.exe qc OstiumCore 2>&1 | Out-String
            Write-InstallLog "sc qc OstiumCore: $serviceConfig"
        } catch {}
        $serviceLog = Join-Path $CoreDataDir "logs\service.log"
        if (Test-Path $serviceLog) {
            try {
                $serviceTail = (Get-Content -LiteralPath $serviceLog -Tail 40) -join [Environment]::NewLine
                Write-InstallLog "service.log tail:`n$serviceTail"
            } catch {}
        }
        Write-Warning "OstiumCore service did not start; the UI will still be installed. See $installLog"
    }
}

# The unprivileged UI may read the core token, but must never be able to
# overwrite it (that would let a local user hijack the privileged API).
$tokenPath = Join-Path $CoreDataDir "runtime\core.token"
$tokenWait = if ($serviceStarted) { 30 } else { 2 }
for ($i = 0; $i -lt $tokenWait -and -not (Test-Path $tokenPath); $i++) { Start-Sleep -Seconds 1 }
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

# Do not report success before the UI actually answers with the expected
# version.  A stale process returning HTTP 200 used to make the installer
# declare success while the browser kept showing the previous release.
$healthUrl = "http://127.0.0.1:$UiPort/healthz"
$ready = $false
$lastHealth = ""
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
            $statusCode = $response.StatusCode
            $reader = New-Object System.IO.StreamReader($response.GetResponseStream())
            $lastHealth = $reader.ReadToEnd()
            $reader.Dispose()
        } finally {
            $response.Close()
        }
        if ($statusCode -eq [System.Net.HttpStatusCode]::OK) {
            $health = $lastHealth | ConvertFrom-Json
            if ([string]$health.version -eq $ExpectedVersion) {
                $ready = $true
                break
            }
            Write-InstallLog ("health check reported version {0}, expected {1}" -f $health.version, $ExpectedVersion)
        }
    } catch {
        # The task may still be starting; retry until the deadline.
    }
}
if (-not $ready) {
    Write-InstallLog "UI health/version check failed at $healthUrl (last body: $lastHealth)"
    $owner = Get-PortOwner $UiPort
    if ($owner) {
        Write-InstallLog ("port owner: pid={0} name={1} path={2} started={3}" -f $owner.Pid, $owner.Name, $owner.Path, $owner.StartTime)
    }
    $task = Get-ScheduledTask -TaskName "Ostium" -ErrorAction SilentlyContinue
    $info = Get-ScheduledTaskInfo -TaskName "Ostium" -ErrorAction SilentlyContinue
    $tail = ""
    if (Test-Path $uiLog) {
        $lines = Get-Content -LiteralPath $uiLog -Tail 20 -ErrorAction SilentlyContinue
        if ($lines) { $tail = $lines -join [Environment]::NewLine }
    }
    throw "Ostium UI did not report version $ExpectedVersion at $healthUrl. Task state: $($task.State); last result: $($info.LastTaskResult). Log: $uiLog`n$tail"
}
Write-InstallLog "UI health/version check passed"

$cliVersion = (& "$InstallDir\ostium.exe" version | Out-String)
if ($LASTEXITCODE -ne 0 -or $cliVersion -notmatch [Regex]::Escape("Ostium $ExpectedVersion")) {
    throw "Installed CLI reports a different version:`n$cliVersion"
}
Write-InstallLog "CLI version check passed"

# A UI 200 is not enough when the core already has a configuration: the proxy
# may be down while the console is perfectly reachable.
$coreConfig = Join-Path $CoreDataDir "runtime\last-good.json"
if ($serviceStarted -and (Test-Path $coreConfig)) {
    $coreReady = $false
    for ($i = 0; $i -lt 30; $i++) {
        try {
            $coreRequest = [System.Net.WebRequest]::Create("http://127.0.0.1:8788/v1/health")
            $coreRequest.Proxy = $null
            $coreRequest.Timeout = 2000
            $coreResponse = [System.Net.HttpWebResponse]$coreRequest.GetResponse()
            try {
                $coreReader = New-Object System.IO.StreamReader($coreResponse.GetResponseStream())
                $coreHealth = $coreReader.ReadToEnd() | ConvertFrom-Json
            } finally {
                $coreResponse.Close()
            }
            if ($coreHealth.running -eq $true) { $coreReady = $true; break }
        } catch {
            Start-Sleep -Seconds 1
        }
    }
    if (-not $coreReady) {
        throw "OstiumCore is not running a configuration after install; see $CoreDataDir\logs\core.log"
    }
}

Write-Host "Ostium installed. Open http://127.0.0.1:$UiPort" -ForegroundColor Green
Write-Host "CLI: ostium (open a new terminal so PATH picks up $InstallDir)" -ForegroundColor Green
Write-Host "Startup log: $uiLog" -ForegroundColor Green
Write-Host "Install log: $installLog" -ForegroundColor Green
if (-not $serviceStarted) {
    Write-Host "Warning: OstiumCore is not running; TUN/core features are unavailable. See $installLog" -ForegroundColor Yellow
}
