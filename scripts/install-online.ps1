<#
Ostium 一键在线安装器（Windows 客户端）。

用法（管理员 PowerShell）：
  irm https://raw.githubusercontent.com/ThzxxArt/Ostium/main/scripts/install-online.ps1 | iex

带参数：
  & ([scriptblock]::Create((irm .../install-online.ps1))) -Version latest -RunAsSystem

离线：
  .\install-online.ps1 -LocalDir D:\Ostium-release

卸载：
  .\install-online.ps1 -Uninstall [-Purge]
#>
[CmdletBinding()]
param(
    [string]$Version = "latest",
    [ValidateSet("client")]
    [string]$Role = "client",
    [string]$LocalDir = "",
    [switch]$Uninstall,
    [switch]$Purge,
    [switch]$RunAsSystem,
    [switch]$NoVerify,
    [switch]$NoStart
)

$ErrorActionPreference = "Stop"

function Write-Step([string]$Message) {
    Write-Host "[Ostium] $Message" -ForegroundColor Cyan
}

function Assert-Admin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "请以管理员身份运行 PowerShell，再执行安装命令。"
    }
}

function Resolve-Version {
    if ($Version -ne "latest") { return $Version.TrimStart("v") }
    $release = Invoke-RestMethod -UseBasicParsing `
        -Uri "https://api.github.com/repos/ThzxxArt/Ostium/releases/latest"
    if (-not $release.tag_name) { throw "无法解析最新版本，请用 -Version 指定。" }
    return $release.tag_name.TrimStart("v")
}

function Get-ExpectedHash([string]$SumsFile, [string]$AssetName) {
    $leaf = [IO.Path]::GetFileName($AssetName)
    foreach ($line in Get-Content -LiteralPath $SumsFile) {
        $parts = $line -split "\s+", 2
        if ($parts.Count -ne 2) { continue }
        $candidate = $parts[1].Trim().TrimStart("*")
        if ([IO.Path]::GetFileName($candidate) -eq $leaf) {
            return $parts[0]
        }
    }
    throw "SHA256SUMS 中找不到 $AssetName"
}

function Get-UiPort([string]$DataDir) {
    $config = Join-Path $DataDir "config.toml"
    if (Test-Path $config) {
        foreach ($line in Get-Content -LiteralPath $config) {
            if ($line -match '^\s*port\s*=\s*(\d{1,5})\s*$') { return [int]$Matches[1] }
        }
    }
    return 8787
}

function Assert-InstalledVersion([string]$InstallDir, [string]$ExpectedVersion) {
    $output = (& (Join-Path $InstallDir "ostium.exe") version | Out-String)
    if ($LASTEXITCODE -ne 0 -or $output -notmatch [Regex]::Escape("Ostium $ExpectedVersion")) {
        throw "已安装的 Ostium CLI 版本与预期 $ExpectedVersion 不一致：`n$output"
    }
}

function Wait-UiVersion([int]$Port, [string]$ExpectedVersion) {
    $url = "http://127.0.0.1:$Port/healthz"
    $last = ""
    for ($i = 0; $i -lt 60; $i++) {
        try {
            $request = [System.Net.WebRequest]::Create($url)
            $request.Proxy = $null
            $request.Timeout = 2000
            $response = [System.Net.HttpWebResponse]$request.GetResponse()
            try {
                $reader = New-Object System.IO.StreamReader($response.GetResponseStream())
                $last = $reader.ReadToEnd()
                $reader.Dispose()
            } finally {
                $response.Close()
            }
            $health = $last | ConvertFrom-Json
            if ([string]$health.version -eq $ExpectedVersion) { return $health }
        } catch {
            # The scheduled task may still be starting.
        }
        Start-Sleep -Seconds 1
    }
    throw "UI 未在 $url 报告版本 $ExpectedVersion（最后响应：$last）"
}

function Install-Ostium([string]$ResolvedVersion) {
    $asset = "Ostium-$ResolvedVersion-windows-x64-setup.exe"
    $temp = Join-Path $env:TEMP ("ostium-install-" + [Guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Force -Path $temp | Out-Null
    try {
        if ($LocalDir) {
            if (-not (Test-Path $LocalDir)) { throw "本地目录不存在：$LocalDir" }
            $setup = Get-ChildItem -LiteralPath $LocalDir -Recurse -Filter $asset |
                Select-Object -First 1 -ExpandProperty FullName
            $sums = Get-ChildItem -LiteralPath $LocalDir -Recurse -Filter "SHA256SUMS" |
                Select-Object -First 1 -ExpandProperty FullName
            if (-not $setup) { throw "找不到 Windows 安装包：$asset" }
            if (-not $sums) { throw "找不到 SHA256SUMS" }
        }
        else {
            $base = "https://github.com/ThzxxArt/Ostium/releases/download/v$ResolvedVersion"
            $setup = Join-Path $temp $asset
            $sums = Join-Path $temp "SHA256SUMS"
            Write-Step "下载 Ostium v$ResolvedVersion Windows 安装包"
            Invoke-WebRequest -UseBasicParsing -Uri "$base/$asset" -OutFile $setup
            Invoke-WebRequest -UseBasicParsing -Uri "$base/SHA256SUMS" -OutFile $sums
        }
        if (-not (Test-Path $setup)) { throw "找不到 Windows 安装包：$setup" }
        if (-not $NoVerify) {
            if (-not (Test-Path $sums)) { throw "缺少 SHA256SUMS：$sums" }
            $expected = Get-ExpectedHash $sums $asset
            $actual = (Get-FileHash -LiteralPath $setup -Algorithm SHA256).Hash.ToLowerInvariant()
            if ($actual -ne $expected.ToLowerInvariant()) {
                throw "SHA256 校验失败：`n期望 $expected`n实际 $actual"
            }
            Write-Step "SHA256 校验通过"
        }
        Write-Step "运行静默安装"
        $arguments = @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART")
        if ($NoStart) { $env:OSTIUM_NO_START = "1" }
        try {
            $process = Start-Process -FilePath $setup -ArgumentList $arguments -Wait -PassThru
        }
        finally {
            Remove-Item Env:OSTIUM_NO_START -ErrorAction SilentlyContinue
        }
        if ($process.ExitCode -ne 0) { throw "安装程序退出码：$($process.ExitCode)" }

        $installDir = Join-Path $env:ProgramFiles "Ostium"
        $service = Get-Service OstiumCore -ErrorAction SilentlyContinue
        if (-not $service -or $service.Status -ne "Running") {
            # The UI is deliberately installed even when the privileged core
            # fails, so the operator can open the console and read diagnostics.
            Write-Warning "OstiumCore 服务未运行；UI 仍已安装。请检查 $env:ProgramData\Ostium\logs\install.log 和 $env:ProgramData\OstiumCore\logs\service.log。"
        }

        if ($RunAsSystem) {
            Write-Step "将控制面也切换为 SYSTEM（取消用户级隔离）"
            Stop-ScheduledTask -TaskName "Ostium" -ErrorAction SilentlyContinue
            Unregister-ScheduledTask -TaskName "Ostium" -Confirm:$false -ErrorAction SilentlyContinue
            $uiScript = Join-Path $installDir "ostium-ui.ps1"
            $powerShell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
            $action = New-ScheduledTaskAction `
                -Execute $powerShell `
                -Argument "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$uiScript`"" `
                -WorkingDirectory $installDir
            $trigger = New-ScheduledTaskTrigger -AtStartup
            $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
            Register-ScheduledTask -TaskName "Ostium" -Action $action -Trigger $trigger -Principal $principal -Force | Out-Null
            if (-not $NoStart) { Start-ScheduledTask -TaskName "Ostium" }
        }
        if ($NoStart) {
            Stop-ScheduledTask -TaskName "Ostium" -ErrorAction SilentlyContinue
            Stop-Service OstiumCore -ErrorAction SilentlyContinue
            Assert-InstalledVersion $installDir $ResolvedVersion
        }
        else {
            Assert-InstalledVersion $installDir $ResolvedVersion
            $uiPort = Get-UiPort (Join-Path $env:ProgramData "Ostium")
            $health = Wait-UiVersion $uiPort $ResolvedVersion
            Write-Step "健康检查通过：Ostium $($health.version) on port $uiPort"
        }
        Write-Step "安装完成。打开 http://127.0.0.1:$(Get-UiPort (Join-Path $env:ProgramData 'Ostium'))"
    }
    finally {
        Remove-Item -Recurse -Force $temp -ErrorAction SilentlyContinue
    }
}

function Uninstall-Ostium {
    $installDir = Join-Path $env:ProgramFiles "Ostium"
    $inno = Join-Path $installDir "unins000.exe"
    if (Test-Path $inno) {
        Write-Step "运行 Inno Setup 卸载程序"
        $process = Start-Process -FilePath $inno `
            -ArgumentList @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART") -Wait -PassThru
        if ($process.ExitCode -ne 0) { throw "卸载程序退出码：$($process.ExitCode)" }
        if ($Purge) {
            Remove-Item -LiteralPath (Join-Path $env:ProgramData "Ostium") `
                -Recurse -Force -ErrorAction SilentlyContinue
            Remove-Item -LiteralPath (Join-Path $env:ProgramData "OstiumCore") `
                -Recurse -Force -ErrorAction SilentlyContinue
        }
        Write-Step "已卸载"
        return
    }
    $script = Join-Path $installDir "uninstall.ps1"
    if (Test-Path $script) {
        Write-Step "运行 Ostium 卸载脚本"
        $argLine = "-ExecutionPolicy Bypass -File `"$script`" -InstallDir `"$installDir`""
        if ($Purge) { $argLine += " -RemoveData" }
        $process = Start-Process powershell.exe -ArgumentList $argLine -Wait -PassThru
        if ($process.ExitCode -ne 0) { throw "卸载脚本退出码：$($process.ExitCode)" }
        Write-Step "已卸载"
        return
    }
    throw "未找到 Ostium 安装目录或卸载程序。"
}

Assert-Admin
if ($Uninstall) {
    Uninstall-Ostium
    exit 0
}

$resolved = Resolve-Version
Install-Ostium $resolved
