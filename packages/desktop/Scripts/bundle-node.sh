#!/usr/bin/env bash
# bundle-node.sh — download a portable Node.js runtime and bundle the
#                  packages/server source (with its node_modules, including
#                  @anthropic-ai/claude-code) into Resources/runtime/ so the
#                  production .app can run on a clean Mac without the user
#                  having Node installed. Run BEFORE Scripts/make-app.sh.
#
#   ./Scripts/bundle-node.sh
#   ./Scripts/bundle-node.sh --node 20.18.0
#
# Outputs:
#   Resources/runtime/node                            (portable node executable)
#   Resources/runtime/server/bin/dsh-server.js        (real server entry)
#   Resources/runtime/server/src/*.js                 (server source)
#   Resources/runtime/server/node_modules/...         (claude-code + deps)
#   Resources/runtime/serverEntry.js                  (CJS shim into server/)
#
# EmbeddedServer.swift launches `runtime/node runtime/serverEntry.js …`; the
# shim hands off to the ESM `server/bin/dsh-server.js`. CLI args are ignored
# by the server (it reads env vars set by EmbeddedServer).

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
REPO_ROOT="$( cd "$ROOT/../.." && pwd )"
SERVER_SRC="$REPO_ROOT/packages/server"

if [[ ! -d "$SERVER_SRC" ]]; then
    echo "!! cannot find packages/server at $SERVER_SRC" >&2
    exit 1
fi

ARCH="$(uname -m)"
case "$ARCH" in
    arm64)  NODE_ARCH="arm64" ;;
    x86_64) NODE_ARCH="x64"   ;;
    *) echo "unsupported arch $ARCH" >&2; exit 1 ;;
esac

TARBALL="node-v${NODE_VERSION}-darwin-${NODE_ARCH}.tar.gz"
URL="https://nodejs.org/dist/v${NODE_VERSION}/${TARBALL}"

echo "==> preparing $RUNTIME"
rm -rf "$RUNTIME"
mkdir -p "$RUNTIME"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "==> fetching $URL"
curl -fsSL "$URL" -o "$TMP/$TARBALL"
tar -xzf "$TMP/$TARBALL" -C "$TMP"

NODE_DIR="$TMP/node-v${NODE_VERSION}-darwin-${NODE_ARCH}"
cp "$NODE_DIR/bin/node" "$RUNTIME/node"
chmod +x "$RUNTIME/node"
echo "==> node installed at $RUNTIME/node ($("$RUNTIME/node" --version))"

# Make sure packages/server has its node_modules (claude-code + transitive
# deps). Use the bundled npm so we don't depend on a system Node.
NPM="$NODE_DIR/bin/npm"
if [[ ! -d "$SERVER_SRC/node_modules/@anthropic-ai/claude-code" ]]; then
    echo "==> npm install (omit=dev) in $SERVER_SRC"
    ( cd "$SERVER_SRC" && PATH="$NODE_DIR/bin:$PATH" "$NPM" install --omit=dev --no-audit --no-fund )
else
    echo "==> packages/server/node_modules already populated; skipping npm install"
fi

# Copy server bundle into Resources/runtime/server. Exclude tests + caches.
echo "==> bundling packages/server -> $RUNTIME/server"
mkdir -p "$RUNTIME/server"
rsync -a \
    --exclude 'tests/' \
    --exclude '.npm/' \
    --exclude '*.log' \
    --exclude '.DS_Store' \
    "$SERVER_SRC/" "$RUNTIME/server/"

# Tiny CJS shim. EmbeddedServer.swift hardcodes serverEntry.js, but the real
# server is ESM, so we use dynamic import() to bridge. We also prepend the
# bundled server's node_modules/.bin to PATH so agent.js can spawn `claude`
# without depending on a system-wide install.
cat > "$RUNTIME/serverEntry.js" <<'ENTRY'
// serverEntry.js — bootstrap shim into the bundled packages/server.
// EmbeddedServer.swift hardcodes this filename and passes args we ignore;
// the server reads env vars (DSH_PORT, DSH_BIND, DSH_AUTH_MODE, DSH_HOME).
const path = require('node:path');
const here = __dirname;

// Make the bundled `claude` CLI discoverable on PATH for agent.js's spawn().
const binDir = path.join(here, 'server', 'node_modules', '.bin');
const sep = process.platform === 'win32' ? ';' : ':';
process.env.PATH = binDir + sep + (process.env.PATH || '');

// Dynamic import bridges CJS shim to the ESM server entry.
import('./server/bin/dsh-server.js').catch((err) => {
    console.error('[serverEntry] failed to start dsh-server:', err && err.stack || err);
    process.exit(2);
});
ENTRY

echo "==> bundled runtime: $(du -sh "$RUNTIME" | cut -f1)"
echo ""
echo "==> done. Now run: Scripts/make-app.sh release"
