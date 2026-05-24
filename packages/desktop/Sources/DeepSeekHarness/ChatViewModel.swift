import Foundation
import Combine
import AppKit

@MainActor
final class ChatViewModel: ObservableObject {

    @Published var messages: [ChatMessage] = []
    @Published var input: String = ""
    @Published var isStreaming: Bool = false
    @Published var errorBanner: String?

    /// Live assistant text under construction (mirrored into messages[last].text).
    @Published var currentAssistantText: String = ""

    /// Budget snapshot from the most recent `usage` event (or /v1/budget poll).
    @Published var todayUSD: Double = 0
    @Published var capUSD: Double = 5

    /// Last device snapshot, surfaced in the popover's "设备状态" pill.
    @Published var deviceSnapshot: DeviceSnapshot?

    /// Current server-issued session id (nil = new session next send).
    @Published var sessionID: String?

    /// True until the first user-visible request of the session has been sent.
    /// Drives `context.greeting: true` exactly once per session, and unlocks
    /// the proactive boot greeting flow.
    private var pendingFirstTurn: Bool = true

    /// Set after a proactive greeting has been issued in this app run so we
    /// don't double-greet if the user clicks the icon repeatedly.
    private var proactiveGreetingFired: Bool = false

    private var streamTask: Task<Void, Never>?
    private let sseClient = SSEClient()

    // Injected by AppDelegate.
    weak var bootScan: BootScan?
    weak var fileIndex: FileIndex?

    // MARK: - Public API

    func send(prompt: String? = nil) {
        let text = (prompt ?? input).trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, !isStreaming else { return }
        input = ""
        errorBanner = nil

        messages.append(ChatMessage(role: .user, text: text))
        let assistantID = UUID()
        messages.append(ChatMessage(id: assistantID, role: .assistant, text: "",
                                    isStreaming: true))
        currentAssistantText = ""
        isStreaming = true

        let isGreetingTurn = pendingFirstTurn
        pendingFirstTurn = false

        streamTask = Task { [weak self] in
            guard let self = self else { return }
            await self.runStream(prompt: text,
                                 assistantID: assistantID,
                                 greeting: isGreetingTurn,
                                 showUserBubble: true)
        }
    }

    /// Fire a proactive greeting on app launch. The user has not typed
    /// anything yet, so the UI shows only an assistant bubble (no user
    /// message bubble above it). Idempotent within an app run.
    func proactiveGreeting() {
        guard !proactiveGreetingFired else { return }
        guard !isStreaming else { return }
        proactiveGreetingFired = true
        pendingFirstTurn = false

        let assistantID = UUID()
        messages.append(ChatMessage(id: assistantID, role: .assistant, text: "",
                                    isStreaming: true))
        currentAssistantText = ""
        isStreaming = true

        streamTask = Task { [weak self] in
            guard let self = self else { return }
            // The server's `if (!body.prompt)` check rejects empty strings, so
            // we send a tiny placeholder. The buddy system prompt + greeting=true
            // make the agent ignore the literal content and greet anyway.
            await self.runStream(prompt: "你好",
                                 assistantID: assistantID,
                                 greeting: true,
                                 showUserBubble: false)
        }
    }

    func cancel() {
        streamTask?.cancel()
        streamTask = nil
        if let idx = messages.lastIndex(where: { $0.role == .assistant && $0.isStreaming }) {
            messages[idx].isStreaming = false
            if messages[idx].text.isEmpty {
                messages[idx].text = "_(已取消 / cancelled)_"
            }
        }
        isStreaming = false

        if let sid = sessionID {
            Task { try? await postCancel(sid: sid) }
        }
    }

    func clear() {
        cancel()
        messages.removeAll()
        currentAssistantText = ""
        errorBanner = nil
    }

    func newSession() {
        cancel()
        sessionID = nil
        messages.removeAll()
        currentAssistantText = ""
        errorBanner = nil
        pendingFirstTurn = true
        proactiveGreetingFired = false
    }

    // MARK: - Stream pump

    private func runStream(prompt: String,
                           assistantID: UUID,
                           greeting: Bool,
                           showUserBubble: Bool) async {
        let prefs = Preferences.shared

        // Gather buddy context — device snapshot + recent files. These are
        // both cheap thanks to caching, but await them off the main actor.
        let device: DeviceSnapshot? = await {
            guard let bs = self.bootScan else { return nil }
            return await bs.snapshot()
        }()
        let recent: [RecentFile] = await {
            guard let fi = self.fileIndex else { return [] }
            return await fi.currentSnapshot()
        }()

        if let device = device {
            await MainActor.run { self.deviceSnapshot = device }
        }

        let context = BuddyContext(
            user_name: NSFullUserName(),
            greeting: greeting ? true : nil,    // omit field when false → cleaner prompt
            device: device,
            recent_files: recent.isEmpty ? nil : recent
        )

        let url = prefs.baseURL.appendingPathComponent("v1/run")
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.timeoutInterval = 120
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if let tok = prefs.bearerToken {
            req.setValue("Bearer \(tok)", forHTTPHeaderField: "Authorization")
        }

        let body = RunRequest(
            prompt: prompt,
            model: prefs.model.rawValue,
            session_id: sessionID,
            workspace: "default",
            permission_mode: "bypassPermissions",
            mode: "buddy",
            context: context
        )
        do {
            let enc = JSONEncoder()
            enc.outputFormatting = []
            req.httpBody = try enc.encode(body)
        } catch {
            finishWithError("无法准备请求 (request encode failed): \(error.localizedDescription)")
            return
        }

        _ = showUserBubble   // currently unused — caller already decided

        do {
            for try await frame in sseClient.stream(req) {
                if Task.isCancelled { break }
                handleFrame(frame, assistantID: assistantID)
            }
            finalizeStream(assistantID: assistantID)
        } catch is CancellationError {
            // already cleaned up by cancel()
        } catch let e as URLError where e.code == .cannotConnectToHost
                                  || e.code == .cannotFindHost
                                  || e.code == .networkConnectionLost
                                  || e.code == .timedOut {
            finishWithError("我连不上自己内部的小助手了 (cannot reach local server)。"
                            + " 请稍后再试，或在设置里检查云端模式。")
        } catch {
            finishWithError("出了点小问题 (stream error): \(error.localizedDescription)")
        }
    }

    private func handleFrame(_ frame: SSEFrame, assistantID: UUID) {
        let dec = JSONDecoder()
        switch frame.event {
        case "session":
            if let ev = try? dec.decode(SessionEvent.self, from: frame.data) {
                self.sessionID = ev.session_id
            }
        case "thinking":
            break
        case "tool_call":
            if let ev = try? dec.decode(ToolCallEvent.self, from: frame.data) {
                appendAssistant("\n> 🔧 \(ev.name)\n", id: assistantID)
            }
        case "tool_result":
            break
        case "delta":
            if let ev = try? dec.decode(DeltaEvent.self, from: frame.data) {
                appendAssistant(ev.text, id: assistantID)
            }
        case "usage":
            if let ev = try? dec.decode(UsageEvent.self, from: frame.data),
               let cost = ev.cost_usd {
                self.todayUSD = cost
            }
        case "done":
            if let ev = try? dec.decode(DoneEvent.self, from: frame.data) {
                if let total = ev.cost_usd_total { self.todayUSD = total }
                // If we didn't get any deltas (claude-code returns only `result`
                // sometimes), fall back to result for display.
                if currentAssistantText.isEmpty, let r = ev.result, !r.isEmpty {
                    appendAssistant(r, id: assistantID)
                }
            }
            finalizeStream(assistantID: assistantID)
        case "error":
            if let ev = try? dec.decode(ErrorEvent.self, from: frame.data) {
                finishWithError("[\(ev.code)] \(ev.message)" + (ev.hint.map { "\n提示: \($0)" } ?? ""))
            } else {
                finishWithError("Unknown server error")
            }
        default:
            break
        }
    }

    private func appendAssistant(_ chunk: String, id: UUID) {
        currentAssistantText.append(chunk)
        if let idx = messages.lastIndex(where: { $0.id == id }) {
            messages[idx].text = currentAssistantText
        }
    }

    private func finalizeStream(assistantID: UUID) {
        if let idx = messages.lastIndex(where: { $0.id == assistantID }) {
            messages[idx].isStreaming = false
            if messages[idx].text.isEmpty {
                messages[idx].text = "_(没听清，您再说一次？ / no response)_"
            }
        }
        isStreaming = false
        streamTask = nil
    }

    private func finishWithError(_ message: String) {
        Task { @MainActor in
            self.errorBanner = message
            if let idx = self.messages.lastIndex(where: { $0.role == .assistant && $0.isStreaming }) {
                self.messages[idx].isStreaming = false
                if self.messages[idx].text.isEmpty {
                    self.messages[idx].text = "_(\(message))_"
                }
            }
            self.isStreaming = false
            self.streamTask = nil
        }
    }

    // MARK: - REST helpers

    private func postCancel(sid: String) async throws {
        let prefs = Preferences.shared
        var req = URLRequest(url: prefs.baseURL.appendingPathComponent("v1/cancel/\(sid)"))
        req.httpMethod = "POST"
        if let tok = prefs.bearerToken {
            req.setValue("Bearer \(tok)", forHTTPHeaderField: "Authorization")
        }
        _ = try await URLSession.shared.data(for: req)
    }

    // MARK: - Derived UI state

    /// Approximate USD→RMB. We deliberately don't hit an FX API — the figure is
    /// a friendly hint, not an invoice. Update tomorrow if needed.
    var todayRMB: Double { todayUSD * 7.2 }
    var capRMB: Double   { capUSD * 7.2 }

    var budgetRatio: Double {
        guard capUSD > 0 else { return 0 }
        return min(1.0, max(0.0, todayUSD / capUSD))
    }

    /// Three-bucket health for the device pill.
    /// - red    = ≥ 1 warning
    /// - yellow = no warnings but disk_free_pct < 25 OR cpu_load > 70 OR ram_used_pct > 75
    /// - green  = otherwise
    var deviceHealth: DeviceHealth {
        guard let d = deviceSnapshot else { return .unknown }
        if !d.warnings.isEmpty { return .red }
        if let p = d.disk_free_pct, p < 25 { return .yellow }
        if let c = d.cpu_load, c > 70 { return .yellow }
        if let r = d.ram_used_pct, r > 75 { return .yellow }
        return .green
    }
}

enum DeviceHealth {
    case unknown, green, yellow, red

    var label: String {
        switch self {
        case .unknown: return "设备状态 检测中"
        case .green:   return "设备状态 良好"
        case .yellow:  return "设备状态 注意"
        case .red:     return "设备状态 异常"
        }
    }
}
