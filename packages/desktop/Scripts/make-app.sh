#!/usr/bin/env bash
# make-app.sh — package the SPM build output as a real .app bundle.
#
#   ./Scripts/make-app.sh            # release (default)
#   ./Scripts/make-app.sh release    # release (optimized)
#   ./Scripts/make-app.sh debug      # debug (faster compile, used for `swift run` parity)
#
# Outputs:  .build/DeepSeekHarness.app   (ad-hoc signed, double-clickable)
#
# IMPORTANT: run Scripts/bundle-node.sh first if you want a self-contained .app
# (otherwise EmbeddedServer falls back to a system `node` which the end user
# almost certainly does not have).

set -euo pipefail

CONFIG="${1:-release}"
HERE="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
ROOT="$( cd "$HERE/.." && pwd )"

cd "$ROOT"

VERSION="$(cat VERSION 2>/dev/null | tr -d '[:space:]' || echo 0.1.0)"
APP_NAME="DeepSeekHarness"
DISPLAY="鲸伴"
BUNDLE_ID="dev.deepseek-harness.desktop"

if [[ ! -d "Resources/runtime" || ! -x "Resources/runtime/node" ]]; then
    echo "!! Resources/runtime/node not found — run Scripts/bundle-node.sh first" >&2
    echo "   (otherwise the resulting .app cannot start the embedded server on a clean Mac)" >&2
    exit 1
fi

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

# Resources/* → Contents/Resources/* (includes the bundled runtime/)
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
    cp "$ICONSET/icon_32x32.png"    "$ICONSET/icon_16x16@2x.png"    2>/dev/null || true
    cp "$ICONSET/icon_64x64.png"    "$ICONSET/icon_32x32@2x.png"    2>/dev/null || true
    cp "$ICONSET/icon_256x256.png"  "$ICONSET/icon_128x128@2x.png"  2>/dev/null || true
    cp "$ICONSET/icon_512x512.png"  "$ICONSET/icon_256x256@2x.png"  2>/dev/null || true
    cp "$ICONSET/icon_1024x1024.png" "$ICONSET/icon_512x512@2x.png" 2>/dev/null || true
    iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/AppIcon.icns" >/dev/null 2>&1 || true
fi

sed "s/__VERSION__/$VERSION/g" Info.plist.template > "$APP/Contents/Info.plist"

# Ad-hoc codesign with Hardened Runtime + minimal entitlements so:
#   - Bundled `node` (unsigned) can run as a child process under the parent.
#   - Library validation is disabled so dyld doesn't reject ad-hoc signed binaries.
#   - Without an Apple Developer cert this is the strongest signing we can do
#     on a personal Mac. First-launch quarantine still applies — see README.
ENTITLEMENTS="Entitlements.plist"
if [[ ! -f "$ENTITLEMENTS" ]]; then
    echo "!! $ENTITLEMENTS missing — falling back to plain ad-hoc sign" >&2
    codesign --force --deep --sign - "$APP" 2>/dev/null || \
        echo "!! codesign failed; app may still launch with quarantine warnings" >&2
else
    echo "==> ad-hoc codesigning (hardened runtime, $ENTITLEMENTS)"
    # Sign nested Mach-O binaries first (deepest first), then the bundle.
    if [[ -f "$APP/Contents/Resources/runtime/node" ]]; then
        codesign --force --sign - --options runtime \
            --entitlements "$ENTITLEMENTS" \
            "$APP/Contents/Resources/runtime/node" 2>/dev/null || \
            echo "   (warn) failed to sign bundled node — the app should still run"
    fi
    codesign --force --deep --sign - --options runtime \
        --entitlements "$ENTITLEMENTS" "$APP" 2>/dev/null || {
        echo "!! hardened-runtime codesign failed; retrying without --options runtime" >&2
        codesign --force --deep --sign - "$APP" 2>/dev/null || \
            echo "!! plain codesign also failed — app may launch with extra warnings" >&2
    }
fi

# Verify the signature so we fail loudly if it's broken.
codesign --verify --deep --strict --verbose=2 "$APP" 2>&1 | tail -5 || true

ABS_APP="$(cd "$(dirname "$APP")" && pwd)/$(basename "$APP")"
APP_SIZE="$(du -sh "$APP" | cut -f1)"

echo ""
echo "==> done ($APP_SIZE)"
echo "    $ABS_APP"
echo ""
echo "    Double-click in Finder, or run:"
echo "      open \"$ABS_APP\""
echo ""
echo "    Logs:  ~/Library/Application Support/DeepSeekHarness/server.log"
