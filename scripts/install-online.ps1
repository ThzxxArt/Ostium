<#
Ostium 一键在线安装器（Windows 客户端）。

用法（管理员 PowerShell）：
  irm https://raw.githubusercontent.com/ThzxxArt/Ostium/main/scripts/install-online.ps1 | iex

带参数：
  & ([scriptblock]::Create((irm .../install-online.ps1))) -Version 0.1.0 -RunAsSystem

离线：
  .\install-online.ps1 -LocalDir D:\Ostium-release

卸载：
  .\install-online.ps1 -Uninstall [-Purge]
#>
[CmdletBinding()]
param(
    [string]$Version = "0.1.0",
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
    if ($Version -ne "latest") { return $Version }
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
        $process = Start-Process -FilePath $setup -ArgumentList $arguments -Wait -PassThru
        if ($process.ExitCode -ne 0) { throw "安装程序退出码：$($process.ExitCode)" }

        $installDir = Join-Path $env:ProgramFiles "Ostium"
        $passwordFile = Join-Path $env:ProgramData "Ostium\initial-password.txt"
        $service = Get-Service OstiumCore -ErrorAction SilentlyContinue
        if (-not $service -or $service.Status -ne "Running") {
            throw "OstiumCore 服务未运行；请检查 ProgramData\Ostium\logs 和 Windows 服务日志。"
        }
        if (Test-Path $passwordFile) {
            $initialPassword = Get-Content -LiteralPath $passwordFile -Raw
            Write-Host "初始管理员密码：$initialPassword" -ForegroundColor Yellow
            Write-Host "该密码只显示一次，登录后请立即启用 TOTP。"
            Remove-Item -LiteralPath $passwordFile -Force
        }

        if ($RunAsSystem) {
            Write-Step "将控制面也切换为 SYSTEM（取消用户级隔离）"
            Stop-ScheduledTask -TaskName "Ostium" -ErrorAction SilentlyContinue
            Unregister-ScheduledTask -TaskName "Ostium" -Confirm:$false -ErrorAction SilentlyContinue
            $action = New-ScheduledTaskAction -Execute (Join-Path $installDir "ostium-ui.cmd")
            $trigger = New-ScheduledTaskTrigger -AtStartup
            $principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
            Register-ScheduledTask -TaskName "Ostium" -Action $action -Trigger $trigger -Principal $principal -Force | Out-Null
            if (-not $NoStart) { Start-ScheduledTask -TaskName "Ostium" }
        }
        if ($NoStart) {
            Stop-ScheduledTask -TaskName "Ostium" -ErrorAction SilentlyContinue
        }
        Write-Step "安装完成。打开 http://127.0.0.1:8787"
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
