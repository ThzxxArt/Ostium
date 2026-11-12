# Build the Windows x64 client bundle and Inno Setup installer.
# Run from the repository root in an elevated PowerShell with uv, Node and Inno Setup 6 installed.
param(
    [string]$Version = "0.1.0",
    [string]$CoreBinary = "",
    [string]$WintunDll = ""
)

$ErrorActionPreference = "Stop"
if (-not $IsWindows) { throw "Run this script on Windows." }

Push-Location web
npm ci --no-audit --no-fund
npm run build
Pop-Location

uv sync
if ($CoreBinary) {
    Copy-Item $CoreBinary "dist\core\sing-box.exe" -Force
}
if ($WintunDll) {
    Copy-Item $WintunDll "dist\core\wintun.dll" -Force
}

uv run pyinstaller --noconfirm --clean deploy\pyinstaller\ostium.spec
uv run pyinstaller --noconfirm --clean deploy\pyinstaller\ostium-service.spec

$out = "dist\windows\Ostium"
New-Item -ItemType Directory -Force -Path $out, "$out\core" | Out-Null
Copy-Item "dist\Ostium\*" $out -Recurse -Force
Copy-Item "dist\OstiumService\ostium-service.exe" $out -Force
Copy-Item "deploy\windows\install.ps1", "deploy\windows\uninstall.ps1" $out -Force
if (Test-Path "dist\core\sing-box.exe") { Copy-Item "dist\core\sing-box.exe" "$out\core\" -Force }
if (Test-Path "dist\core\wintun.dll") { Copy-Item "dist\core\wintun.dll" "$out\core\" -Force }

if (Get-Command ISCC.exe -ErrorAction SilentlyContinue) {
    ISCC.exe deploy\windows\ostium.iss /DAppVersion=$Version
    Write-Host "Installer written to dist\windows"
} else {
    Write-Warning "Inno Setup (ISCC.exe) not found; the portable bundle is in $out"
}
