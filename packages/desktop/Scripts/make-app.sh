#!/usr/bin/env bash
# make-app.sh — package the SPM build output as a real .app bundle.
#
#   ./Scripts/make-app.sh            # debug (faster)
#   ./Scripts/make-app.sh release    # release (optimized)
#
# Outputs:  .build/DeepSeekHarness.app   (ad-hoc signed, double-clickable)

set -euo pipefail

CONFIG="${1:-release}"
HERE="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
ROOT="$( cd "$HERE/.." && pwd )"

cd "$ROOT"

VERSION="$(cat VERSION 2>/dev/null | tr -d '[:space:]' || echo 0.1.0)"
APP_NAME="DeepSeekHarness"
DISPLAY="深求"
BUNDLE_ID="dev.deepseek-harness.desktop"

echo "==> swift build -c $CONFIG (arch host)"
swift build -c "$CONFIG"

BIN_PATH="$(swift build -c "$CONFIG" --show-bin-path)"
BINARY="$BIN_PATH/$APP_NAME"
if [[ ! -x "$BINARY" ]]; then
    echo "!! build produced no $APP_NAME binary at $BINARY" >&2
    exit 1
fi

APP=".build/$APP_NAME.app"
echo "==> assembling $APP"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"
mkdir -p "$APP/Contents/Resources"

cp "$BINARY" "$APP/Contents/MacOS/$APP_NAME"

# Resources/* → Contents/Resources/*
if [[ -d Resources ]]; then
    rsync -a Resources/ "$APP/Contents/Resources/"
fi

# Convert AppIcon.png → AppIcon.icns if sips + iconutil are present.
if [[ -f "$APP/Contents/Resources/AppIcon.png" ]] && command -v sips >/dev/null && command -v iconutil >/dev/null; then
    ICONSET="$(mktemp -d)/AppIcon.iconset"
    mkdir -p "$ICONSET"
    SRC="$APP/Contents/Resources/AppIcon.png"
    for size in 16 32 64 128 256 512 1024; do
        sips -z "$size" "$size" "$SRC" --out "$ICONSET/icon_${size}x${size}.png" >/dev/null 2>&1 || true
    done
    # Retina @2x duplicates for the standard sizes
    cp "$ICONSET/icon_32x32.png"    "$ICONSET/icon_16x16@2x.png"    2>/dev/null || true
    cp "$ICONSET/icon_64x64.png"    "$ICONSET/icon_32x32@2x.png"    2>/dev/null || true
    cp "$ICONSET/icon_256x256.png"  "$ICONSET/icon_128x128@2x.png"  2>/dev/null || true
    cp "$ICONSET/icon_512x512.png"  "$ICONSET/icon_256x256@2x.png"  2>/dev/null || true
    cp "$ICONSET/icon_1024x1024.png" "$ICONSET/icon_512x512@2x.png" 2>/dev/null || true
    iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/AppIcon.icns" >/dev/null 2>&1 || true
fi

# Info.plist
sed "s/__VERSION__/$VERSION/g" Info.plist.template > "$APP/Contents/Info.plist"

# Ad-hoc codesign so Gatekeeper lets it run on the local machine.
echo "==> ad-hoc codesigning"
codesign --force --deep --sign - "$APP" 2>/dev/null || {
    echo "!! codesign failed; the app may still launch with quarantine warnings." >&2
}

ABS_APP="$(cd "$(dirname "$APP")" && pwd)/$(basename "$APP")"
echo ""
echo "==> done"
echo "    $ABS_APP"
echo ""
echo "    Double-click in Finder, or run:"
echo "      open \"$ABS_APP\""
echo ""
echo "    Logs:  ~/Library/Application Support/DeepSeekHarness/server.log"
