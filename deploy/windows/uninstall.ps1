# Uninstall the Ostium Windows client. Data is preserved unless -RemoveData is set.
param(
    [string]$InstallDir = "$env:ProgramFiles\Ostium",
    [string]$DataDir = "$env:ProgramData\Ostium",
    [switch]$RemoveData,
    [switch]$SkipPathUpdate
)

$ErrorActionPreference = "SilentlyContinue"

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
    }
}

function Stop-OstiumListener([int]$Port) {
    $owner = Get-PortOwner $Port
    if (-not $owner) { return }
    $known = @("ostium", "ostium-service", "sing-box")
    $owned = $known -contains $owner.Name
    if (-not $owned -and $owner.Path) {
        $candidate = [IO.Path]::GetFullPath($owner.Path)
        foreach ($root in @($InstallDir, $DataDir, "$env:ProgramData\OstiumCore")) {
            $prefix = [IO.Path]::GetFullPath($root).TrimEnd([char[]]('\', '/')) + [IO.Path]::DirectorySeparatorChar
            if ($candidate.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) { $owned = $true }
        }
    }
    if (-not $owned) {
        Write-Warning "Port $Port is owned by pid $($owner.Pid) ($($owner.Name)); leaving it running."
        return
    }
    Stop-Process -Id $owner.Pid -Force -ErrorAction SilentlyContinue
}

function Remove-MachinePathEntry {
    param([Parameter(Mandatory = $true)][string]$Directory)
    try {
        $key = [Microsoft.Win32.Registry]::LocalMachine.OpenSubKey(
            'SYSTEM\CurrentControlSet\Control\Session Manager\Environment', $true
        )
        if (-not $key) { return }
        try {
            $current = [string]$key.GetValue(
                'Path', '', [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames
            )
            $entry = $Directory.TrimEnd([char[]]'\')
            $parts = @($current -split ';' | Where-Object { $_ -and $_.Trim() })
            $filtered = @($parts | Where-Object { $_.Trim().TrimEnd([char[]]'\') -ine $entry })
            if (($filtered -join ';') -ne ($parts -join ';')) {
                $kind = $key.GetValueKind('Path')
                $key.SetValue('Path', ($filtered -join ';'), $kind)
            }
        } finally {
            $key.Close()
        }
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
    } catch {
        Write-Warning "Could not remove $Directory from the machine PATH: $_"
    }
}

if (-not $SkipPathUpdate) {
    Remove-MachinePathEntry -Directory $InstallDir
}
$serviceExe = Join-Path $InstallDir "service\ostium-service.exe"

# Restore the desktop proxy before removing the CLI that knows the original
# WinINET values; stopping the service tears down the TUN adapter.
$env:OSTIUM_ROLE = "client"
$env:OSTIUM_DATA_DIR = $DataDir
$env:OSTIUM_CONFIG_FILE = "$DataDir\config.toml"
$ostiumExe = Join-Path $InstallDir "ostium.exe"
$proxyRestored = $false
if (Test-Path $ostiumExe) {
    & $ostiumExe proxy off | Out-Null
    $proxyRestored = ($LASTEXITCODE -eq 0)
}
if (-not $proxyRestored) {
    Write-Warning "Could not confirm the system proxy was restored; check Windows proxy settings."
}
Unregister-ScheduledTask -TaskName "Ostium" -Confirm:$false
Stop-OstiumListener 8787
Stop-Service OstiumCore
Stop-OstiumListener 8788
Get-Process ostium -ErrorAction SilentlyContinue | Stop-Process -Force
if (Test-Path $serviceExe) {
    & $serviceExe remove
}
if ($RemoveData) {
    Remove-Item $DataDir -Recurse -Force
    Remove-Item "$env:ProgramData\OstiumCore" -Recurse -Force
}
# Inno Setup removes its own installation directory and registry entry after
# [UninstallRun].  Only remove files here for the portable bundle.
if (-not (Test-Path (Join-Path $InstallDir "unins000.exe"))) {
    Remove-Item $InstallDir -Recurse -Force
}
Write-Host "Ostium removed. Network settings were restored by the core before shutdown."
