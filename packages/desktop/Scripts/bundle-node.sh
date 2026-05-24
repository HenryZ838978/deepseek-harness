#!/usr/bin/env bash
# bundle-node.sh — download a portable Node.js + claude-code into Resources/runtime/
#                  so the production .app can run without the user having Node
#                  installed. Run BEFORE Scripts/make-app.sh for a release build.
#
#   ./Scripts/bundle-node.sh
#   ./Scripts/bundle-node.sh --node 20.18.0
#
# Outputs:
#   Resources/runtime/node                       (executable)
#   Resources/runtime/node_modules/@anthropic-ai/claude-code/...
#   Resources/runtime/serverEntry.js             (TODO: copied from packages/server)
#
# TONIGHT this script is documentation only. Tomorrow's session will actually
# wire it up to the published packages/server build artifact.

set -euo pipefail

NODE_VERSION="20.18.0"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --node) NODE_VERSION="$2"; shift 2 ;;
        *) echo "unknown arg: $1" >&2; exit 1 ;;
    esac
done

HERE="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
ROOT="$( cd "$HERE/.." && pwd )"
RUNTIME="$ROOT/Resources/runtime"

ARCH="$(uname -m)"
case "$ARCH" in
    arm64)  NODE_ARCH="arm64" ;;
    x86_64) NODE_ARCH="x64"   ;;
    *) echo "unsupported arch $ARCH" >&2; exit 1 ;;
esac

TARBALL="node-v${NODE_VERSION}-darwin-${NODE_ARCH}.tar.gz"
URL="https://nodejs.org/dist/v${NODE_VERSION}/${TARBALL}"

echo "==> fetching $URL"
mkdir -p "$RUNTIME"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

curl -fsSL "$URL" -o "$TMP/$TARBALL"
tar -xzf "$TMP/$TARBALL" -C "$TMP"

NODE_DIR="$TMP/node-v${NODE_VERSION}-darwin-${NODE_ARCH}"
cp "$NODE_DIR/bin/node" "$RUNTIME/node"
chmod +x "$RUNTIME/node"
echo "==> node installed at $RUNTIME/node"

# Install claude-code via the bundled npm.
NPM="$NODE_DIR/bin/npm"
mkdir -p "$RUNTIME/node_modules"
PREFIX="$RUNTIME" "$NPM" install --prefix "$RUNTIME" --no-save \
    @anthropic-ai/claude-code@^2.1.0
echo "==> claude-code installed under $RUNTIME/node_modules"

# TODO: copy or build packages/server entry script here.
if [[ ! -f "$RUNTIME/serverEntry.js" ]]; then
    cat > "$RUNTIME/serverEntry.js" <<'STUB'
// STUB serverEntry.js — replace with packages/server bundled output.
// For now this just exits so EmbeddedServer's restart loop logs a clear error.
console.error("[stub] serverEntry.js not yet implemented. Run packages/server build.");
process.exit(2);
STUB
    echo "==> wrote stub serverEntry.js (replace with real packages/server build)"
fi

echo ""
echo "==> done. Now run: Scripts/make-app.sh release"
