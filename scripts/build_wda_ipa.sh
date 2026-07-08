#!/bin/bash
# =============================================================================
# Build a pre-signed WebDriverAgent (WDA.ipa) for tester distribution.
#
# Run this ONCE on the admin Mac (requires Xcode + Wellysis dev account).
# The output runtime/WDA.ipa is picked up by the Mac zip build and installed
# automatically on tester devices — testers never need Xcode.
#
# Prerequisites:
#   1. Xcode installed, signed in with the Wellysis Apple Developer account
#   2. All tester-device UDIDs registered at developer.apple.com
#      (Certificates, Identifiers & Profiles > Devices)
#   3. Appium xcuitest driver installed (provides the WDA source):
#        appium driver install xcuitest
#
# Usage:
#   bash scripts/build_wda_ipa.sh
# =============================================================================
set -euo pipefail

TEAM_ID="9538X2C925"   # Wellysis Corp.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="$ROOT/runtime"
DERIVED="$(mktemp -d /tmp/wda_build.XXXX)"

# Locate WDA source shipped with the appium xcuitest driver
WDA_PROJ=$(find "$HOME/.appium" -path "*appium-webdriveragent/WebDriverAgent.xcodeproj" -maxdepth 6 2>/dev/null | head -1)
if [ -z "$WDA_PROJ" ]; then
    echo "ERROR: WebDriverAgent.xcodeproj not found under ~/.appium"
    echo "       Run: appium driver install xcuitest"
    exit 1
fi
echo "WDA project: $WDA_PROJ"

echo "Building WebDriverAgentRunner (signed, team $TEAM_ID)..."
xcodebuild build-for-testing \
    -project "$WDA_PROJ" \
    -scheme WebDriverAgentRunner \
    -destination "generic/platform=iOS" \
    -derivedDataPath "$DERIVED" \
    -allowProvisioningUpdates \
    -allowProvisioningDeviceRegistration \
    DEVELOPMENT_TEAM="$TEAM_ID" \
    CODE_SIGN_IDENTITY="Apple Development" \
    | tail -5

APP=$(find "$DERIVED/Build/Products" -name "WebDriverAgentRunner-Runner.app" -maxdepth 3 | head -1)
if [ -z "$APP" ]; then
    echo "ERROR: build product not found"; exit 1
fi

echo "Packaging WDA.ipa..."
mkdir -p "$OUT_DIR"
PKG="$(mktemp -d /tmp/wda_pkg.XXXX)"
mkdir -p "$PKG/Payload"
cp -R "$APP" "$PKG/Payload/"
(cd "$PKG" && zip -qr "$OUT_DIR/WDA.ipa" Payload)
rm -rf "$PKG" "$DERIVED"

echo ""
echo "Done: $OUT_DIR/WDA.ipa"
echo "Registered-device check: this ipa installs ONLY on UDIDs in the"
echo "provisioning profile. After registering new devices, re-run this script."
