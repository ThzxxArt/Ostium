#!/usr/bin/env bash
# Build the macOS client DMG from release artifacts.
#
# The DMG contains the wheel, the pinned darwin core archive and the launchd
# installer; users run install-macos.sh from the mounted volume.  Building a
# .app bundle is intentionally out of scope for 0.1.x because the client is a
# local web console served from 127.0.0.1.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

VERSION="${1:-0.1.1}"
WHEEL="${OSTIUM_WHEEL:-}"
CORE_TARBALL="${OSTIUM_CORE_TARBALL:-}"
IDENTITY="${OSTIUM_CODESIGN_IDENTITY:-}"
NOTARY_PROFILE="${OSTIUM_NOTARY_PROFILE:-}"

if [[ -z "$WHEEL" ]]; then
  WHEEL="$(find dist -maxdepth 1 -name 'ostium_ctl-*.whl' | head -1)"
fi
if [[ -z "$CORE_TARBALL" ]]; then
  CORE_TARBALL="$(find dist -maxdepth 1 -name 'ostium-core-*-darwin-*.tar.gz' | head -1)"
fi
if [[ ! -f "$WHEEL" ]]; then
  echo "provide OSTIUM_WHEEL or build the wheel first" >&2
  exit 2
fi
if [[ ! -f "$CORE_TARBALL" ]]; then
  echo "provide OSTIUM_CORE_TARBALL or download a darwin core archive" >&2
  exit 2
fi

STAGE="dist/dmg/Ostium"
rm -rf "$STAGE"
mkdir -p "$STAGE"
cp "$WHEEL" "$CORE_TARBALL" "$STAGE/"
cp deploy/launchd/install-macos.sh "$STAGE/"
cp deploy/launchd/com.ostium.core.plist deploy/launchd/com.ostium.ui.plist \
  deploy/launchd/com.ostium.ui.root.plist "$STAGE/"
cp LICENSE NOTICE "$STAGE/"
cat >"$STAGE/README.txt" <<EOF
Ostium ${VERSION} for macOS

1. Open Terminal in this folder.
2. Run: sudo ./install-macos.sh client
3. Open http://127.0.0.1:8787 and complete the setup wizard.

Uninstall (data preserved): sudo ./install-macos.sh uninstall
Full removal: sudo OSTIUM_PURGE=true ./install-macos.sh uninstall

This build is $( [[ -n "$IDENTITY" ]] && echo "signed with $IDENTITY" || echo "UNSIGNED" ).
EOF

DMG="dist/Ostium-${VERSION}-macos-$(uname -m).dmg"
hdiutil create -volname "Ostium" -srcfolder "$STAGE" -ov -format UDZO "$DMG"
if [[ -n "$IDENTITY" ]]; then
  codesign --force --timestamp --sign "$IDENTITY" "$DMG"
  codesign --verify --verbose=2 "$DMG" || true
else
  echo "warning: OSTIUM_CODESIGN_IDENTITY is not set; the DMG is unsigned" >&2
fi
if [[ -n "$NOTARY_PROFILE" && -n "$IDENTITY" ]]; then
  xcrun notarytool submit "$DMG" --keychain-profile "$NOTARY_PROFILE" --wait
  xcrun stapler staple "$DMG"
  echo "notarized and stapled: $DMG"
elif [[ -n "$NOTARY_PROFILE" ]]; then
  echo "warning: notarization skipped because no signing identity is configured" >&2
fi
echo "built $DMG"
