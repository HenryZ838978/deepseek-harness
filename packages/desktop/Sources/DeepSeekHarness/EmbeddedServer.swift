import Foundation

/// Spawns and supervises the local `dsh serve` Node process.
///
/// Lookup order for the node binary:
///   1. `Bundle.main.resourcePath/runtime/node`   (production .app, set up by bundle-node.sh)
///   2. `/usr/local/bin/node`, `/opt/homebrew/bin/node`, or `which node` from PATH
///
/// If no node is found we log a clear error and quietly stop — ChatViewModel will
/// then show "无法连接本地服务 (cannot reach local server)" when the user hits Send.
///
/// Server entry script: `Bundle.main.resourcePath/runtime/serverEntry.js`.
/// During SPM dev (`swift run`) the bundle has no Resources, so we just don't
/// spawn anything. The user is expected to be running `dsh serve` elsewhere,
/// or to get a graceful UI error.
final class EmbeddedServer {

    private let port = 7777
    private let host = "127.0.0.1"

    private var process: Process?
    private var logHandle: FileHandle?

    private let queue = DispatchQueue(label: "dev.deepseek-harness.embeddedServer")

    /// Where stdout/stderr from the embedded server lands.
    var logFileURL: URL {
        let dir = supportDir()
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir.appendingPathComponent("server.log")
    }

    func start() {
        queue.async { [weak self] in self?._start() }
    }

    func stop() {
        queue.sync { [weak self] in self?._stop() }
    }

    // MARK: -

    private func _start() {
        guard process == nil else { return }

        guard let node = locateNode() else {
            log("[embedded-server] no node binary found; skipping spawn. "
                + "Install Node 20+ or ship runtime/ in Resources.")
            return
        }
        guard let entry = locateServerEntry() else {
            log("[embedded-server] no serverEntry.js found in bundle; "
                + "running in 'connect to whatever' mode.")
            return
        }

        let p = Process()
        p.executableURL = URL(fileURLWithPath: node)
        p.arguments = [entry, "serve", "--port", "\(port)", "--bind", host, "--auth", "none"]

        var env = ProcessInfo.processInfo.environment
        env["DSH_AUTH_MODE"] = "none"
        env["DSH_BIND"] = host
        env["DSH_PORT"] = String(port)
        env["DSH_HOME"] = supportDir().path
        p.environment = env

        // Pipe stdout+stderr into a rolling log file.
        let logURL = logFileURL
        if !FileManager.default.fileExists(atPath: logURL.path) {
            FileManager.default.createFile(atPath: logURL.path, contents: nil)
        }
        if let handle = try? FileHandle(forWritingTo: logURL) {
            handle.seekToEndOfFile()
            logHandle = handle
            let pipe = Pipe()
            p.standardOutput = pipe
            p.standardError = pipe
            pipe.fileHandleForReading.readabilityHandler = { [weak self] fh in
                let data = fh.availableData
                if !data.isEmpty { self?.logHandle?.write(data) }
            }
        }

        p.terminationHandler = { [weak self] proc in
            self?.queue.async {
                guard let self = self else { return }
                self.log("[embedded-server] exited rc=\(proc.terminationStatus); restarting in 2s")
                self.process = nil
                DispatchQueue.global().asyncAfter(deadline: .now() + 2.0) {
                    self._start()
                }
            }
        }

        do {
            try p.run()
            process = p
            log("[embedded-server] spawned pid=\(p.processIdentifier) node=\(node) entry=\(entry)")
        } catch {
            log("[embedded-server] failed to spawn: \(error)")
        }
    }

    private func _stop() {
        process?.terminationHandler = nil
        process?.terminate()
        process = nil
        try? logHandle?.close()
        logHandle = nil
    }

    // MARK: - Locators

    private func locateNode() -> String? {
        if let res = Bundle.main.resourcePath {
            let bundled = (res as NSString).appendingPathComponent("runtime/node")
            if FileManager.default.isExecutableFile(atPath: bundled) {
                return bundled
            }
        }
        for path in ["/opt/homebrew/bin/node", "/usr/local/bin/node", "/usr/bin/node"] {
            if FileManager.default.isExecutableFile(atPath: path) { return path }
        }
        // Last resort: PATH lookup.
        return which("node")
    }

    private func locateServerEntry() -> String? {
        if let res = Bundle.main.resourcePath {
            let p = (res as NSString).appendingPathComponent("runtime/serverEntry.js")
            if FileManager.default.fileExists(atPath: p) { return p }
        }
        return nil
    }

    private func which(_ cmd: String) -> String? {
        let p = Process()
        p.launchPath = "/usr/bin/env"
        p.arguments = ["which", cmd]
        let pipe = Pipe()
        p.standardOutput = pipe
        do { try p.run() } catch { return nil }
        p.waitUntilExit()
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        let s = String(data: data, encoding: .utf8)?
            .trimmingCharacters(in: .whitespacesAndNewlines)
        return (s?.isEmpty == false) ? s : nil
    }

    private func supportDir() -> URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory,
                                            in: .userDomainMask).first
            ?? URL(fileURLWithPath: NSHomeDirectory() + "/Library/Application Support")
        return base.appendingPathComponent("DeepSeekHarness", isDirectory: true)
    }

    private func log(_ s: String) {
        let line = "[\(Date())] \(s)\n"
        FileHandle.standardError.write(Data(line.utf8))
        if let data = line.data(using: .utf8) { logHandle?.write(data) }
    }
}
