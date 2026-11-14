# Build the Windows x64 client bundle and Inno Setup installer.
# Run from the repository root in an elevated PowerShell with uv, Node and Inno Setup 6 installed.
param(
    [string]$Version = "0.1.1",
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

if (-not $CoreBinary -or -not (Test-Path $CoreBinary)) {
    throw "CoreBinary is required and must exist: $CoreBinary"
}
if (-not $WintunDll -or -not (Test-Path $WintunDll)) {
    throw "WintunDll is required and must exist: $WintunDll"
}

Push-Location web
npm ci --no-audit --no-fund
if ($LASTEXITCODE -ne 0) { throw "npm ci failed" }
npm run build
if ($LASTEXITCODE -ne 0) { throw "web build failed" }
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
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed for the UI bundle" }
uv run pyinstaller --noconfirm --clean deploy\pyinstaller\ostium-service.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed for the service bundle" }

if ($env:OSTIUM_SIGN_THUMBPRINT) {
    $signtool = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if (-not $signtool) { throw "signtool.exe is required when OSTIUM_SIGN_THUMBPRINT is set" }
    foreach ($exe in @("dist\Ostium\ostium.exe", "dist\OstiumService\ostium-service.exe")) {
        if (Test-Path $exe) {
            & $signtool.Source sign /sha1 $env:OSTIUM_SIGN_THUMBPRINT /tr http://timestamp.digicert.com /td sha256 /fd sha256 $exe
            if ($LASTEXITCODE -ne 0) { throw "Authenticode signing failed for $exe" }
        }
    }
} else {
    Write-Warning "OSTIUM_SIGN_THUMBPRINT is not set; Windows binaries will be unsigned"
}

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

if (-not (Get-Command ISCC.exe -ErrorAction SilentlyContinue)) {
    throw "Inno Setup (ISCC.exe) is required to build the release installer"
}
ISCC.exe deploy\windows\ostium.iss /DAppVersion=$Version
if ($LASTEXITCODE -ne 0) { throw "Inno Setup compilation failed" }
$setup = Get-ChildItem "dist\windows\*-setup.exe" | Select-Object -First 1
if (-not $setup) { throw "Inno Setup did not produce a setup executable" }
if ($env:OSTIUM_SIGN_THUMBPRINT) {
    $signtool = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if (-not $signtool) { throw "signtool.exe is required when OSTIUM_SIGN_THUMBPRINT is set" }
    & $signtool.Source sign /sha1 $env:OSTIUM_SIGN_THUMBPRINT /tr http://timestamp.digicert.com /td sha256 /fd sha256 $setup.FullName
    if ($LASTEXITCODE -ne 0) { throw "Authenticode signing failed for $($setup.FullName)" }
}
Write-Host "Installer written to dist\windows"
