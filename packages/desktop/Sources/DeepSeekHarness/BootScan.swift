import Foundation
import AppKit
import IOKit
import IOKit.ps

/// Gathers a `DeviceSnapshot` of the host Mac.
///
/// All probes are best-effort: anything that fails (TCC denial, app not
/// running, hardware feature missing, parse mismatch) is reported as `nil`
/// rather than guessed, so the buddy agent can simply omit that fact.
///
/// Snapshots are cached for `cacheTTL` seconds so the popover doesn't spawn
/// a flock of `sysctl`/`pmset`/`osascript` processes on every keystroke.
actor BootScan {

    private(set) var lastSnapshot: DeviceSnapshot?
    private var lastTaken: Date?
    private let cacheTTL: TimeInterval = 30

    /// Friendly Mac model names. We only need a handful — the agent is happy
    /// to receive raw "Mac15,3" too, since the buddy system prompt translates.
    private static let modelLookup: [String: String] = [
        "MacBookPro18,1": "MacBook Pro 16″ (M1 Pro)",
        "MacBookPro18,2": "MacBook Pro 16″ (M1 Max)",
        "MacBookPro18,3": "MacBook Pro 14″ (M1 Pro)",
        "MacBookPro18,4": "MacBook Pro 14″ (M1 Max)",
        "Mac14,7":        "MacBook Pro 13″ (M2)",
        "Mac14,9":        "MacBook Pro 14″ (M2 Pro)",
        "Mac14,10":       "MacBook Pro 16″ (M2 Pro)",
        "Mac15,3":        "MacBook Pro 14″ (M3)",
        "Mac15,6":        "MacBook Pro 14″ (M3 Pro)",
        "Mac15,7":        "MacBook Pro 16″ (M3 Pro)",
        "MacBookAir10,1": "MacBook Air (M1)",
        "Mac14,2":        "MacBook Air (M2)",
        "Mac15,12":       "MacBook Air 13″ (M3)",
        "Macmini9,1":     "Mac mini (M1)",
        "Mac14,3":        "Mac mini (M2)",
        "iMac21,1":       "iMac 24″ (M1)",
        "iMac21,2":       "iMac 24″ (M1)"
    ]

    func snapshot(force: Bool = false) async -> DeviceSnapshot {
        if !force, let cached = lastSnapshot, let when = lastTaken,
           Date().timeIntervalSince(when) < cacheTTL {
            return cached
        }
        let snap = await gather()
        lastSnapshot = snap
        lastTaken = Date()
        return snap
    }

    // MARK: - Gather

    private func gather() async -> DeviceSnapshot {
        // Synchronous probes (cheap, in-process)
        let totalRAM = Int(ProcessInfo.processInfo.physicalMemory / 1024 / 1024 / 1024)
        let uptime   = Int(ProcessInfo.processInfo.systemUptime / 3600)
        let runningApps = NSWorkspace.shared.runningApplications.filter {
            $0.activationPolicy == .regular
        }.count

        // Disk
        let (totalGB, freeGB) = Self.diskCapacity()
        let freePct: Int? = (totalGB.flatMap { t in freeGB.map { f in Int(Double(f) / Double(t) * 100.0) } })

        // Shelled probes — run in parallel
        async let modelRaw    = Self.sysctl("hw.model")
        async let cpuBrand    = Self.sysctl("machdep.cpu.brand_string")
        async let ramUsedPct  = Self.parseVmStat()
        async let battery     = Self.batteryViaIOKit()
        async let chromeTabs  = Self.chromeTabCountViaOsascript()
        async let cpuLoad     = Self.cpuLoadPercent()
        async let wifi        = Self.wifiSSID()

        let model = await modelRaw.map { Self.modelLookup[$0] ?? $0 }
        let (battPct, charging) = await battery

        // Warnings
        var warnings: [String] = []
        if let p = freePct, p < 15 { warnings.append("存储空间紧张") }
        if let n = await chromeTabs, n > 30 { warnings.append("Chrome 标签过多") }
        if runningApps > 25 { warnings.append("软件开得有点多") }
        if let pct = await ramUsedPct, pct > 85 { warnings.append("内存吃紧") }
        if let b = battPct, b < 20, charging != true { warnings.append("电量偏低") }

        return DeviceSnapshot(
            model:              model,
            cpu:                await cpuBrand,
            ram_gb:             totalRAM > 0 ? totalRAM : nil,
            ram_used_pct:       await ramUsedPct,
            disk_total_gb:      totalGB,
            disk_free_gb:       freeGB,
            disk_free_pct:      freePct,
            cpu_load:           await cpuLoad,
            battery_pct:        battPct,
            charging:           charging,
            chrome_tab_count:   await chromeTabs,
            running_apps_count: runningApps,
            uptime_hours:       uptime,
            network:            await wifi,
            warnings:           warnings
        )
    }

    // MARK: - Probes (all `static` so they're trivially Sendable)

    private static func sysctl(_ name: String) async -> String? {
        let out = await runProcess(
            executable: "/usr/sbin/sysctl",
            args: ["-n", name],
            timeout: 2
        )
        guard let s = out?.trimmingCharacters(in: .whitespacesAndNewlines),
              !s.isEmpty else { return nil }
        return s
    }

    private static func diskCapacity() -> (Int?, Int?) {
        let url = URL(fileURLWithPath: "/")
        let keys: Set<URLResourceKey> = [
            .volumeTotalCapacityKey,
            .volumeAvailableCapacityForImportantUsageKey,
            .volumeAvailableCapacityKey
        ]
        guard let v = try? url.resourceValues(forKeys: keys) else { return (nil, nil) }
        let total = v.volumeTotalCapacity.map { Int(Double($0) / 1_073_741_824.0) }
        // Prefer "important usage" (the value Finder shows) when available.
        let avail = (v.volumeAvailableCapacityForImportantUsage.map { Int(Double($0) / 1_073_741_824.0) })
                  ?? (v.volumeAvailableCapacity.map { Int(Double($0) / 1_073_741_824.0) })
        return (total, avail)
    }

    /// `vm_stat` output is like:
    ///     Mach Virtual Memory Statistics: (page size of 16384 bytes)
    ///     Pages free:                    302921.
    ///     Pages active:                  486112.
    ///     Pages inactive:                483017.
    ///     Pages wired down:              215099.
    ///     Pages occupied by compressor:   86412.
    ///     ...
    /// Used% = (active + wired + compressor) / (active + wired + compressor + free + inactive)
    private static func parseVmStat() async -> Int? {
        guard let out = await runProcess(executable: "/usr/bin/vm_stat", args: [], timeout: 2)
        else { return nil }
        var pageSize: Double = 4096
        if let m = out.range(of: #"page size of (\d+)"#, options: .regularExpression) {
            let digits = out[m].filter { $0.isNumber }
            if let v = Double(digits) { pageSize = v }
        }
        func pages(_ key: String) -> Double? {
            for line in out.split(separator: "\n") {
                if line.contains(key) {
                    let digits = line.filter { $0.isNumber }
                    return Double(digits)
                }
            }
            return nil
        }
        let active     = pages("Pages active:") ?? 0
        let wired      = pages("Pages wired down:") ?? 0
        let compressor = pages("Pages occupied by compressor:") ?? 0
        let free       = pages("Pages free:") ?? 0
        let inactive   = pages("Pages inactive:") ?? 0
        let used       = active + wired + compressor
        let total      = used + free + inactive
        guard total > 0 else { return nil }
        _ = pageSize // not needed for ratio, but kept for future absolute MB
        return Int((used / total) * 100.0)
    }

    /// 1-minute CPU load average → rough busyness percent (capped at 100).
    private static func cpuLoadPercent() async -> Int? {
        var loads = [Double](repeating: 0, count: 3)
        let n = getloadavg(&loads, 3)
        guard n >= 1 else { return nil }
        let cores = max(1, ProcessInfo.processInfo.activeProcessorCount)
        let pct = min(100, Int((loads[0] / Double(cores)) * 100.0))
        return pct
    }

    private static func batteryViaIOKit() async -> (Int?, Bool?) {
        guard let blob = IOPSCopyPowerSourcesInfo()?.takeRetainedValue() else {
            return (nil, nil)
        }
        guard let sources = IOPSCopyPowerSourcesList(blob)?.takeRetainedValue() as? [CFTypeRef]
        else { return (nil, nil) }

        for src in sources {
            guard let desc = IOPSGetPowerSourceDescription(blob, src)?.takeUnretainedValue()
                    as? [String: Any] else { continue }
            // Only consider internal batteries.
            if let type = desc[kIOPSTypeKey as String] as? String,
               type == kIOPSInternalBatteryType {
                let pct = desc[kIOPSCurrentCapacityKey as String] as? Int
                let powerState = desc[kIOPSPowerSourceStateKey as String] as? String
                let charging = (powerState == kIOPSACPowerValue)
                return (pct, charging)
            }
        }
        return (nil, nil)
    }

    /// Returns the Chrome tab count, or nil if Chrome isn't running / TCC denied.
    /// The AppleScript here counts tabs across all windows.
    private static func chromeTabCountViaOsascript() async -> Int? {
        // First short-circuit: if Chrome isn't running, no point asking.
        let running = NSWorkspace.shared.runningApplications.contains { app in
            (app.bundleIdentifier ?? "").lowercased().contains("com.google.chrome")
        }
        guard running else { return 0 }

        let script = """
        try
          tell application "Google Chrome"
            set theCount to 0
            repeat with w in windows
              set theCount to theCount + (count of tabs of w)
            end repeat
            return theCount
          end tell
        on error errMsg number errNum
          return "ERR:" & errNum
        end try
        """
        guard let out = await runProcess(
            executable: "/usr/bin/osascript",
            args: ["-e", script],
            timeout: 3
        ) else { return nil }
        let trimmed = out.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.hasPrefix("ERR:") { return nil }
        return Int(trimmed)
    }

    private static func wifiSSID() async -> String? {
        // `networksetup -getairportnetwork en0` — works without elevated perms
        // but won't surface SSID on macOS 14+ unless Location Services is on.
        // Returning nil is fine; the agent simply won't mention the network.
        guard let out = await runProcess(
            executable: "/usr/sbin/networksetup",
            args: ["-getairportnetwork", "en0"],
            timeout: 2
        ) else { return nil }
        let line = out.trimmingCharacters(in: .whitespacesAndNewlines)
        if let r = line.range(of: ": ") {
            let ssid = String(line[r.upperBound...]).trimmingCharacters(in: .whitespaces)
            if !ssid.isEmpty, ssid != "You are not associated with an AirPort network." {
                return ssid
            }
        }
        return nil
    }

    // MARK: - Process runner

    /// Runs a short-lived process and returns its stdout, or nil on timeout/error.
    private static func runProcess(executable: String,
                                   args: [String],
                                   timeout: TimeInterval) async -> String? {
        guard FileManager.default.isExecutableFile(atPath: executable) else { return nil }
        return await withCheckedContinuation { cont in
            DispatchQueue.global(qos: .utility).async {
                let p = Process()
                p.executableURL = URL(fileURLWithPath: executable)
                p.arguments = args
                let out = Pipe()
                p.standardOutput = out
                p.standardError = Pipe()   // swallow stderr
                do { try p.run() } catch {
                    cont.resume(returning: nil); return
                }

                // Timeout watchdog
                let timer = DispatchSource.makeTimerSource(queue: .global())
                timer.schedule(deadline: .now() + timeout)
                let didFire = NSLock()
                var fired = false
                timer.setEventHandler {
                    didFire.lock(); defer { didFire.unlock() }
                    if !fired && p.isRunning {
                        fired = true
                        p.terminate()
                    }
                }
                timer.resume()

                p.waitUntilExit()
                timer.cancel()

                let data = (try? out.fileHandleForReading.readToEnd()) ?? Data()
                let str = String(data: data, encoding: .utf8)
                cont.resume(returning: p.terminationStatus == 0 ? str : nil)
            }
        }
    }
}
