# `packages/desktop/dist/` — built artifacts

Build artifacts from `Scripts/bundle-node.sh` + `Scripts/make-app.sh` + `hdiutil`.

The `.dmg` files in this folder are NOT committed to git (see top-level
`.gitignore`). Re-build locally before each release.

## Reproducing the build

```bash
cd packages/desktop

# 1. Download portable Node + bundle the dsh-server source/node_modules into Resources/runtime/
./Scripts/bundle-node.sh                         # ~30s + ~497 MB on disk

# 2. swift build + assemble + ad-hoc codesign with Hardened Runtime
./Scripts/make-app.sh release                    # ~2s after first build → .build/DeepSeekHarness.app

# 3. Compress to a Finder-friendly DMG with an Applications drop target
VERSION=$(cat VERSION | tr -d '[:space:]')
STAGING=$(mktemp -d)
rsync -a .build/DeepSeekHarness.app "$STAGING/"
ln -s /Applications "$STAGING/Applications"
hdiutil create -fs HFS+ \
    -volname "DeepSeek Harness $VERSION" \
    -srcfolder "$STAGING" \
    -ov -format UDZO \
    "dist/DeepSeekHarness-$VERSION.dmg"
rm -rf "$STAGING"
hdiutil verify "dist/DeepSeekHarness-$VERSION.dmg"
```

`create-dmg` is fancier (custom backgrounds, icon positions) but isn't
installed on this dev Mac and requires Homebrew. `hdiutil create … -format
UDZO` ships in the OS, ad-hoc codesigns cleanly, and produces a 170-ish MB
artifact from the 499 MB `.app`.

## Installing the DMG

```bash
hdiutil attach -readonly -nobrowse dist/DeepSeekHarness-0.1.0.dmg
cp -R "/Volumes/DeepSeek Harness 0.1.0/DeepSeekHarness.app" /Applications/
hdiutil detach "/Volumes/DeepSeek Harness 0.1.0"
xattr -dr com.apple.quarantine /Applications/DeepSeekHarness.app    # optional, see below
open /Applications/DeepSeekHarness.app
```

Or just double-click the `.dmg` in Finder and drag the app onto the
`Applications` link.

## First-launch on a different Mac (where you didn't build it)

Because the app is **ad-hoc signed** (no Apple Developer ID), Gatekeeper will
quarantine it. The standard "right-click → 打开 (Open) → 仍要打开 (Open
Anyway)" workaround still works:

1. After dragging into `/Applications`, **double-click the dmg → 右键点
   `DeepSeekHarness.app` → 打开**. macOS will warn "无法验证开发者". Click
   **打开**.
2. Or, in **System Settings → 隐私与安全性 (Privacy & Security)** scroll to
   the bottom — there will be a "App 已被阻止使用" entry with a `仍要打开`
   button. Click it once and macOS remembers the decision forever.
3. From Terminal, the same effect can be achieved with:

   ```bash
   xattr -dr com.apple.quarantine /Applications/DeepSeekHarness.app
   ```

   (no admin password needed if you own `/Applications`).

After the first launch the app will run normally on every subsequent
double-click.

## What's inside the .app (≈ 499 MB)

```
DeepSeekHarness.app/
└── Contents/
    ├── Info.plist                          (LSUIElement=true → menubar only)
    ├── MacOS/DeepSeekHarness               (~ 2 MB Swift binary)
    ├── Resources/
    │   ├── AppIcon.icns                    (generated from AppIcon.png)
    │   ├── dsh.sh, first-run.sh
    │   └── runtime/                        (~ 497 MB)
    │       ├── node                        (portable Node 20.18.0 darwin-arm64)
    │       ├── serverEntry.js              (CJS shim: PATH += server/.bin, then ESM-import the server)
    │       └── server/
    │           ├── bin/dsh-server.js       (real entrypoint, ESM)
    │           ├── src/*.js                (HTTP+SSE server, agent, buddy, store)
    │           └── node_modules/
    │               ├── .bin/claude         → ../@anthropic-ai/claude-code/bin/claude.exe
    │               └── @anthropic-ai/claude-code/bin/claude.exe   (~213 MB single-binary CLI)
    └── _CodeSignature/CodeResources
```

`runtime/node` and `runtime/server/.../claude.exe` together account for the
bulk of the size. The Swift binary itself is tiny.

## Why the size?

The single-file `claude.exe` ships everything Claude-Code needs (V8, Node
internals, JS bundle) in one ~213 MB binary; we additionally ship a
*separate* portable `node` (~120 MB) that Swift's `EmbeddedServer.swift`
spawns to run `serverEntry.js`. The two could be unified in a future round
by either:

- having `EmbeddedServer.swift` exec `claude.exe` directly with a different
  entry, or
- packaging the server as a Single-Executable-Application via Node 22 SEA.

Both are out of scope for v0.1; the size is acceptable for a self-contained
buddy app and the DMG compresses to ~170 MB.

## Sign + notarize (when we get a Developer ID)

The current ad-hoc-signed flow forces the Gatekeeper bypass dance above.
Once we have an Apple Developer cert (`Developer ID Application: ...`) plus
notarization credentials, replace the codesign call in `Scripts/make-app.sh`:

```bash
codesign --force --deep --sign "Developer ID Application: <Team Name> (<Team ID>)" \
    --options runtime --entitlements ../Entitlements.plist \
    .build/DeepSeekHarness.app

xcrun notarytool submit dist/DeepSeekHarness-$VERSION.dmg \
    --apple-id you@example.com --team-id <Team ID> --wait
xcrun stapler staple dist/DeepSeekHarness-$VERSION.dmg
```

After stapling, end users no longer need the right-click workaround.

## Verifying a build matches the codebase

```bash
codesign --verify --strict --verbose=2 /Applications/DeepSeekHarness.app
codesign -d --entitlements - /Applications/DeepSeekHarness.app
spctl --assess --type execute --verbose /Applications/DeepSeekHarness.app
```

Ad-hoc signed builds will pass `codesign --verify` but fail `spctl --assess`
("source=No matching profile") — that's expected.

## Smoke test the embedded server (without a GUI)

```bash
APP=/Applications/DeepSeekHarness.app
DSH_AUTH_MODE=none DSH_PORT=17777 DSH_BIND=127.0.0.1 \
    "$APP/Contents/Resources/runtime/node" \
    "$APP/Contents/Resources/runtime/serverEntry.js" &
sleep 3
curl -sS http://127.0.0.1:17777/health
# {"ok":true,"version":"0.1.0","runtime":"claude-code","auth_mode":"none","has_anthropic_key":true}

# Real buddy round-trip (requires ANTHROPIC_AUTH_TOKEN to be set in env):
curl -N -X POST http://127.0.0.1:17777/v1/run \
    -H 'content-type: application/json' \
    -d '{"prompt":"用一个字回答：你好","mode":"buddy","context":{"user_name":"Henry"}}'
# event: delta  data: {"text":"好"}
# event: done   data: {"result":"好","usage_total":{...},"cost_usd_total":0.13,"num_turns":1}
```

## Logs

The embedded server writes stdout+stderr to:

```
~/Library/Application Support/DeepSeekHarness/server.log
```

EmbeddedServer.swift prepends `[YYYY-MM-DD HH:MM:SS +ZZZZ] [embedded-server]`
bookkeeping lines around supervised restarts.
