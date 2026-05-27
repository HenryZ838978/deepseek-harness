# 鲸伴小助手 · DeepSeek Harness (Mac desktop)

A SwiftUI menubar "super-buddy" that lives on a normal user's Mac. Not Claude
Code with a GUI — a Chinese-speaking, non-technical assistant who already
knows the device state and recently used files, and *opens the conversation*
when you click the icon for the first time.

- macOS 13 (Ventura) +
- Pure SwiftUI / AppKit, no third-party deps
- Builds with **Apple Command Line Tools only** — full Xcode not required for
  the dev loop
- Talks to a local `dsh serve` (`packages/server`) via SSE; switches to a
  hosted cloud later for "keep running after I close the lid" tasks

## Buddy-layer integration

The Mac app implements all six product requirements:

1. **Boot-time self-check** — `BootScan.swift` shells out to `sysctl`,
   `vm_stat`, `pmset`, `osascript`, IOKit, and friends to produce a
   `DeviceSnapshot { model, cpu, ram_gb, ram_used_pct, disk_*, battery_pct,
   charging, chrome_tab_count, running_apps_count, uptime_hours, warnings }`.
   Warnings are added inline: disk_free_pct<15 → `存储空间紧张`,
   chrome_tab_count>30 → `Chrome 标签过多`,
   running_apps_count>25 → `软件开得有点多`,
   ram_used_pct>85 → `内存吃紧`,
   battery_pct<20 (not charging) → `电量偏低`.
2. **No workspace UI** — `Preferences.ensureBuddyWorkspace()` auto-creates
   `~/Documents/鲸伴小助手/`. The word "workspace" appears nowhere in the
   user-facing UI; Settings has no such option.
3. **File pre-scan** — `FileIndex.swift` walks `~/Documents`, `~/Desktop`,
   `~/Downloads`, plus WeChat/Lark/WPS/DingTalk container dirs, every 5 min.
   Keeps the 200 most-recently-modified files (last 30 days, extension
   whitelist, ≤500 MB), each labelled with a friendly app name (`微信`,
   `飞书`, `WPS`, `钉钉`, `桌面`, `文稿`, `下载`). TCC denials are silently
   swallowed.
4. **Auto-approve everything** — every request is sent with
   `permission_mode: "bypassPermissions"`. The Settings UI has no
   permission-mode option to confuse the user.
5. **`mode: "buddy"` on every request** — `ChatViewModel.runStream(…)`
   constructs `RunRequest { mode: "buddy", context: BuddyContext { user_name,
   greeting, device, recent_files } }` for every send.
6. **Proactive opening** — `AppDelegate.applicationDidFinishLaunching` warms
   `BootScan` + `FileIndex` then calls `chatVM.proactiveGreeting()`, which
   sends a buddy request with `greeting: true`. The agent's reply lands in
   the popover as the first bubble before the user types anything.

The server-side prompt logic lives in `packages/server/src/buddy.js`
(`BUDDY_SYSTEM_PROMPT`, `wrapBuddyPrompt`, `postProcess`). Server activates
all of it when `body.mode === "buddy"`.

## Layout

```
packages/desktop/
├── Package.swift              SPM manifest (executable target)
├── VERSION                    semver
├── Info.plist.template        bundled into the .app by make-app.sh
├── Sources/DeepSeekHarness/
│   ├── main.swift             NSApplication bootstrap + `--diag` mode
│   ├── AppDelegate.swift      menubar + popover + buddy wiring
│   ├── EmbeddedServer.swift   spawns/supervises bundled `node serverEntry.js`
│   ├── Preferences.swift      defaults + env.sh + auto-workspace
│   ├── Models.swift           Codable types (DeviceSnapshot, RecentFile,
│   │                          BuddyContext, RunRequest, SSE events…)
│   ├── BootScan.swift         actor: device snapshot gathering
│   ├── FileIndex.swift        actor: 5-min recent-file walk
│   ├── Permissions.swift      TCC status probes + System Settings shortcuts
│   ├── SSEClient.swift        byte-level SSE parser (does NOT use bytes.lines —
│   │                          see "Gotchas" below)
│   ├── ChatViewModel.swift    @MainActor stream pump + proactive greeting
│   ├── ChatView.swift         popover (no model picker; device + cost pills)
│   ├── SettingsView.swift     API key / 助手类型 / 上限 / TCC indicators / 云端
│   ├── FirstRunFlow.swift     welcome window for new users
│   └── Diagnostic.swift       `--diag` headless buddy smoke test
├── Resources/                 dsh.sh, first-run.sh, AppIcon.png, runtime/
├── Scripts/                   make-app.sh, bundle-node.sh
└── XcodeProject/              empty — open Package.swift in Xcode directly
```

## Dev loop (CLT only)

```bash
# 1. compile and run the menubar app (debug, ~2s rebuild)
swift run

# 2. headless buddy smoke test (no GUI, exits when agent replies)
swift run DeepSeekHarness --diag                    # greeting
swift run DeepSeekHarness --diag --ask "整理下载里的安装包"

# 3. compile + bundle as a real double-clickable .app (release)
./Scripts/make-app.sh release
open .build/DeepSeekHarness.app
```

`--diag` is the most useful tool — it runs `BootScan` + `FileIndex` once,
posts a real buddy `/v1/run`, streams the SSE response, and prints both the
device JSON to stderr and the agent's reply to stdout. Sample run on a
MacBook Pro 13″ (M2), 8 GB RAM, 3% free disk (real numbers from the dev
machine):

```
→ [diag] device snapshot:
{
  "battery_pct" : 100, "charging" : true,
  "cpu" : "Apple M2", "model" : "MacBook Pro 13″ (M2)",
  "ram_gb" : 8, "ram_used_pct" : 76,
  "disk_total_gb" : 228, "disk_free_gb" : 7, "disk_free_pct" : 3,
  "uptime_hours" : 54, "running_apps_count" : 5,
  "warnings" : [ "存储空间紧张" ]
}
→ [diag] 2 recent files
→ [diag] POST /v1/run, waiting for SSE…

下午好 Henry！您电脑用到现在挺顺畅的，不过存储空间快满了（只剩 7G），得留意一下。

要不要我帮您：
- **清理一下下载文件夹里的旧文件**，腾出点空间？
- **看看《飞书20260523-022710.mp4》那个视频**，帮您转个格式或者存到别的地方？
```

Set `DSH_SSE_DEBUG=1` to log every SSE line as it arrives.

## Gotchas

- **`URLSession.bytes(for:).lines` silently drops empty lines** on macOS 13.
  SSE relies on the blank-line frame terminator, so `SSEClient` walks raw
  bytes and splits on `\n` itself. Don't "fix" it by switching to `.lines`.
- **Server requires non-empty `prompt`** even for greeting requests. The
  proactive greeting sends `prompt: "你好"`; the buddy system prompt +
  `greeting: true` make the agent ignore the literal content and just greet.
- **TCC permissions are user-grant gates we can't bypass.** The Settings
  panel shows status + a "去开启" deep-link button; we never try to
  programmatically grant. If `automationChromeStatus()` returns
  `.unknown` and Chrome is running, it usually means the user has *not yet*
  been prompted (first `osascript` against Chrome shows the dialog) — clicking
  "去开启" sends them to the right pane.
- **Disk free %** uses `volumeAvailableCapacityForImportantUsageKey` (what
  Finder shows). On APFS the raw `volumeAvailableCapacityKey` is much
  larger because it includes purgeable space. Buddy speaks in Finder terms.

## TODOs (tomorrow's session)

- [ ] First-time TCC prompts: the moment the user clicks anything that fires
      AppleScript at Chrome / reads `~/Library/Containers/com.tencent.xinWeChat`,
      macOS shows a one-time consent dialog. We should detect "we have not
      been asked yet" and proactively run a 1-line `osascript`/`ls` to trigger
      the prompts during first-run, so the user grants once and never again.
- [ ] Replace ad-hoc signature with a Developer ID Application cert. TCC
      *bindings* are signature-keyed, so re-signing invalidates prior grants —
      best to do this before asking the user to click Allow.
- [ ] Wire `Scripts/bundle-node.sh` to the real `packages/server` build output
      (replaces the stub `serverEntry.js`).
- [ ] Move the DeepSeek API key out of `env.sh` and into the macOS Keychain.
- [ ] Cloud-mode JWT login flow (phone OTP → `POST /v1/auth/login`).
- [ ] Sparkle 2.x for auto-update.
- [ ] Use real-time FX rate for the RMB display (currently hard-coded ×7.2).
- [ ] Persist session history across restarts; today the popover is in-memory only.
- [ ] Real whale glyph (replace `fish.fill` SF Symbol).
- [ ] Notarization: `xcrun notarytool submit DeepSeekHarness.app --apple-id … --team-id …`
      then `xcrun stapler staple`.
- [ ] Once `BootScan.warnings` produces something actionable, have the
      proactive greeting *also* surface a tappable quick-action (e.g. a
      "🧹 帮我清理" button below the bubble that sends a pre-filled prompt).
- [ ] Add `.pkg` / `.dmg` / `.app` to `FileIndex.keepExtensions` so the buddy
      sees installers (today the agent only finds them by independently
      ls-ing `~/Downloads`; we should hand them over directly).
