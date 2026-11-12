#!/usr/bin/env bash
# Build the macOS client .app/.dmg from source on macOS.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
VERSION="${1:-0.1.0}"

cd web
npm ci --no-audit --no-fund
npm run build
cd ..

uv sync
uv run pyinstaller --noconfirm --clean deploy/pyinstaller/ostium.spec

APP="dist/Ostium.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp -R dist/Ostium/* "$APP/Contents/MacOS/"
cp deploy/launchd/com.ostium.core.plist deploy/launchd/com.ostium.ui.plist "$APP/Contents/Resources/"
cat >"$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>Ostium</string>
  <key>CFBundleIdentifier</key><string>com.ostium.console</string>
  <key>CFBundleVersion</key><string>${VERSION}</string>
  <key>CFBundleShortVersionString</key><string>${VERSION}</string>
  <key>CFBundleExecutable</key><string>ostium</string>
</dict></plist>
PLIST

hdiutil create -volname "Ostium" -srcfolder "$APP" -ov -format UDZO "dist/Ostium-${VERSION}-macos-$(uname -m).dmg"
echo "built dist/Ostium-${VERSION}-macos-$(uname -m).dmg"
