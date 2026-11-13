# Build the Windows x64 client bundle and Inno Setup installer.
# Run from the repository root in an elevated PowerShell with uv, Node and Inno Setup 6 installed.
param(
    [string]$Version = "0.1.0",
    [string]$CoreBinary = "",
    [string]$WintunDll = ""
)

$ErrorActionPreference = "Stop"
if ($env:OS -ne "Windows_NT") { throw "Run this script on Windows." }

function Copy-IfDifferent([string]$Source, [string]$Destination) {
    $sourceFull = [IO.Path]::GetFullPath($Source)
    $destinationFull = [IO.Path]::GetFullPath($Destination)
    if (-not [string]::Equals($sourceFull, $destinationFull, [StringComparison]::OrdinalIgnoreCase)) {
        Copy-Item $sourceFull $destinationFull -Force
    }
}

Push-Location web
npm ci --no-audit --no-fund
npm run build
Pop-Location

# Bake the release version into the PyInstaller bundle instead of relying on
# a shallow checkout that has no tags.
$env:SETUPTOOLS_SCM_PRETEND_VERSION = $Version
uv sync
New-Item -ItemType Directory -Force -Path "dist\core" | Out-Null
if ($CoreBinary) {
    Copy-IfDifferent $CoreBinary "dist\core\sing-box.exe"
}
if ($WintunDll) {
    Copy-IfDifferent $WintunDll "dist\core\wintun.dll"
}

uv run pyinstaller --noconfirm --clean deploy\pyinstaller\ostium.spec
uv run pyinstaller --noconfirm --clean deploy\pyinstaller\ostium-service.spec

$out = "dist\windows\Ostium"
New-Item -ItemType Directory -Force -Path $out, "$out\core", "$out\service" | Out-Null
Copy-Item "dist\Ostium\*" $out -Recurse -Force
# PyInstaller one-dir builds need the whole service folder (`_internal`
# included), not just the executable.  Keep it in a subdirectory so its
# `_internal` tree cannot overwrite the console application's files.
Copy-Item "dist\OstiumService\*" "$out\service" -Recurse -Force
Copy-Item "deploy\windows\install.ps1", "deploy\windows\uninstall.ps1" $out -Force
Copy-Item "LICENSE", "NOTICE" $out -Force
if (Test-Path "dist\core\sing-box.exe") { Copy-Item "dist\core\sing-box.exe" "$out\core\" -Force }
if (Test-Path "dist\core\wintun.dll") { Copy-Item "dist\core\wintun.dll" "$out\core\" -Force }
foreach ($doc in @("LICENSE", "SBOM.txt")) {
    if (Test-Path "dist\core\$doc") { Copy-Item "dist\core\$doc" "$out\core\" -Force }
}

if (Get-Command ISCC.exe -ErrorAction SilentlyContinue) {
    ISCC.exe deploy\windows\ostium.iss /DAppVersion=$Version
    Write-Host "Installer written to dist\windows"
} else {
    Write-Warning "Inno Setup (ISCC.exe) not found; the portable bundle is in $out"
}
