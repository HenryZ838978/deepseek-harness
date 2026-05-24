import Foundation

/// Headless exercise of the buddy code path. Invoked via `--diag` from main.
/// Prints to stdout. Never used in the GUI.
enum Diagnostic {

    static func run() async {
        FileHandle.standardError.write(Data("→ [diag] booting BootScan + FileIndex…\n".utf8))

        let bootScan  = BootScan()
        let fileIndex = FileIndex()

        async let device = bootScan.snapshot(force: true)
        async let files  = fileIndex.refresh()
        let (snap, recents) = await (device, files)

        FileHandle.standardError.write(Data("→ [diag] device snapshot:\n".utf8))
        printJSON(snap)
        FileHandle.standardError.write(Data("→ [diag] \(recents.count) recent files; first 10:\n".utf8))
        for f in recents.prefix(10) {
            FileHandle.standardError.write(Data("    · \(f.name)  (\(f.app), \(f.modified))\n".utf8))
        }

        // Two ways to drive the diag:
        //   default              → greeting + "你好"
        //   --diag --ask "..."  → no greeting, send arbitrary prompt
        var prompt = "你好"
        var greeting = true
        if let askIdx = CommandLine.arguments.firstIndex(of: "--ask"),
           askIdx + 1 < CommandLine.arguments.count {
            prompt = CommandLine.arguments[askIdx + 1]
            greeting = false
        }
        let ctx2 = BuddyContext(
            user_name: NSFullUserName(),
            greeting: greeting ? true : nil,
            device: snap,
            recent_files: recents.isEmpty ? nil : recents
        )
        let body = RunRequest(
            prompt: prompt,
            model: "auto",
            session_id: nil,
            workspace: "default",
            permission_mode: "bypassPermissions",
            mode: "buddy",
            context: ctx2
        )

        let baseURL = URL(string: "http://127.0.0.1:7777")!
        var req = URLRequest(url: baseURL.appendingPathComponent("v1/run"))
        req.httpMethod = "POST"
        req.timeoutInterval = 120
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        do {
            req.httpBody = try JSONEncoder().encode(body)
        } catch {
            FileHandle.standardError.write(Data("encode error: \(error)\n".utf8))
            return
        }
        FileHandle.standardError.write(Data("→ [diag] POST /v1/run, waiting for SSE…\n\n".utf8))

        let sse = SSEClient()
        var assistantBuf = ""
        var sessionID: String?
        var costUSD: Double?
        do {
            for try await frame in sse.stream(req) {
                switch frame.event {
                case "session":
                    if let ev = try? JSONDecoder().decode(SessionEvent.self, from: frame.data) {
                        sessionID = ev.session_id
                        FileHandle.standardError.write(Data("[session] \(ev.session_id)\n".utf8))
                    }
                case "delta":
                    if let ev = try? JSONDecoder().decode(DeltaEvent.self, from: frame.data) {
                        assistantBuf.append(ev.text)
                        FileHandle.standardOutput.write(Data(ev.text.utf8))
                    }
                case "tool_call":
                    if let ev = try? JSONDecoder().decode(ToolCallEvent.self, from: frame.data) {
                        FileHandle.standardError.write(Data("\n[tool] \(ev.name)\n".utf8))
                    }
                case "usage":
                    if let ev = try? JSONDecoder().decode(UsageEvent.self, from: frame.data) {
                        costUSD = ev.cost_usd
                    }
                case "done":
                    if let ev = try? JSONDecoder().decode(DoneEvent.self, from: frame.data) {
                        costUSD = ev.cost_usd_total ?? costUSD
                        if assistantBuf.isEmpty, let r = ev.result {
                            FileHandle.standardOutput.write(Data(r.utf8))
                            assistantBuf = r
                        }
                    }
                case "error":
                    if let ev = try? JSONDecoder().decode(ErrorEvent.self, from: frame.data) {
                        FileHandle.standardError.write(Data("\n[error] \(ev.code): \(ev.message)\n".utf8))
                    }
                default:
                    break
                }
            }
        } catch {
            FileHandle.standardError.write(Data("\n[stream error] \(error)\n".utf8))
        }

        FileHandle.standardOutput.write(Data("\n\n".utf8))
        FileHandle.standardError.write(Data("→ [diag] session=\(sessionID ?? "?") cost=$\(costUSD ?? 0)\n".utf8))
        FileHandle.standardError.write(Data("→ [diag] assistant said \(assistantBuf.count) chars\n".utf8))
    }

    private static func printJSON<T: Encodable>(_ value: T) {
        let enc = JSONEncoder()
        enc.outputFormatting = [.prettyPrinted, .sortedKeys]
        if let data = try? enc.encode(value), let s = String(data: data, encoding: .utf8) {
            FileHandle.standardError.write(Data((s + "\n").utf8))
        }
    }
}
