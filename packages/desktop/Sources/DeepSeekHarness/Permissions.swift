import Foundation
import AppKit

/// Lightweight TCC permission probes + "open System Settings" shortcuts.
///
/// We cannot definitively check most TCC permissions without triggering the
/// user-facing prompt, so these probes are *best-effort signals*, not source
/// of truth. They:
/// - Return `.unknown` if we can't tell (treat as "probably not granted yet")
/// - Return `.granted` only if we actively succeeded in a probe
/// - Return `.denied` only if we got an explicit deny-style error
///
/// The Settings UI displays the status and an "去开启 (open)" button — we
/// never try to elevate ourselves, just send the user to the right pane.
enum PermissionStatus {
    case unknown
    case granted
    case denied
}

enum Permissions {

    // MARK: - AppleScript automation → Chrome

    /// Tries a tiny `osascript` against Chrome. The relevant error numbers:
    ///   -1743  user-denied or no consent yet ("not authorized to send Apple events")
    ///   -1728  Chrome isn't running (can't conclude permission status)
    ///   -600   process not found
    /// Anything else → assume granted if rc==0, unknown otherwise.
    static func automationChromeStatus() -> PermissionStatus {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/usr/bin/osascript")
        p.arguments = ["-e",
            "tell application \"System Events\" to tell process \"Google Chrome\" to return 1"]
        let outPipe = Pipe(), errPipe = Pipe()
        p.standardOutput = outPipe
        p.standardError = errPipe
        do { try p.run() } catch { return .unknown }
        p.waitUntilExit()
        let errStr = String(data: (try? errPipe.fileHandleForReading.readToEnd()) ?? Data(),
                            encoding: .utf8) ?? ""
        if p.terminationStatus == 0 { return .granted }
        if errStr.contains("-1743") || errStr.lowercased().contains("not authorized") {
            return .denied
        }
        // Probably "Chrome isn't running" — we just don't know.
        return .unknown
    }

    // MARK: - Full Disk Access (FDA)

    /// Tries to read a known FDA-gated location. If `URL.checkResourceIsReachable`
    /// throws (or the directory listing throws), we're not granted FDA.
    /// We probe the Mail container — it's present on every Mac, always FDA-gated,
    /// and never requires us to write anything.
    static func fullDiskAccessStatus() -> PermissionStatus {
        let home = FileManager.default.homeDirectoryForCurrentUser
        let probe = home.appendingPathComponent("Library/Mail")
        if !FileManager.default.fileExists(atPath: probe.path) {
            // Mail.app never used — fall back to WeChat container as a softer probe.
            let alt = home.appendingPathComponent("Library/Containers/com.tencent.xinWeChat")
            if !FileManager.default.fileExists(atPath: alt.path) { return .unknown }
            do {
                _ = try FileManager.default.contentsOfDirectory(atPath: alt.path)
                return .granted
            } catch { return .denied }
        }
        do {
            _ = try FileManager.default.contentsOfDirectory(atPath: probe.path)
            return .granted
        } catch {
            return .denied
        }
    }

    // MARK: - "Open System Settings" shortcuts

    static func openAutomationPane() {
        if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Automation") {
            NSWorkspace.shared.open(url)
        }
    }

    static func openFullDiskAccessPane() {
        if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles") {
            NSWorkspace.shared.open(url)
        }
    }
}
