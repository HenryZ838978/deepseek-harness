import Foundation

// MARK: - UI-side message model

enum MessageRole: String, Codable {
    case user
    case assistant
    case system
}

struct ChatMessage: Identifiable, Equatable {
    let id: UUID
    var role: MessageRole
    var text: String
    var isStreaming: Bool
    var createdAt: Date

    init(id: UUID = UUID(),
         role: MessageRole,
         text: String,
         isStreaming: Bool = false,
         createdAt: Date = Date()) {
        self.id = id
        self.role = role
        self.text = text
        self.isStreaming = isStreaming
        self.createdAt = createdAt
    }
}

// MARK: - SSE event payloads (mirror docs/consumer/API.md)

enum SSEEventName: String {
    case session
    case thinking
    case tool_call
    case tool_result
    case delta
    case usage
    case done
    case error
}

struct SessionEvent: Decodable {
    let session_id: String
    let created: Bool?
}

struct ThinkingEvent: Decodable {
    let delta: String
}

struct ToolCallEvent: Decodable {
    let id: String
    let name: String
    let args_preview: String?
    let status: String?
}

struct ToolResultEvent: Decodable {
    let id: String
    let ok: Bool
    let rc: Int?
    let elapsed_ms: Int?
}

struct DeltaEvent: Decodable {
    let text: String
}

struct UsageEvent: Decodable {
    let input_tokens: Int?
    let output_tokens: Int?
    let cached_tokens: Int?
    let cost_usd: Double?
}

struct DoneEvent: Decodable {
    let result: String?
    let usage_total: UsageEvent?
    let cost_usd_total: Double?
    let num_turns: Int?
}

struct ErrorEvent: Decodable {
    let code: String
    let message: String
    let hint: String?
}

// MARK: - Buddy context (mirrors packages/server/src/buddy.js JSDoc)

/// Snapshot of the user's device, gathered by `BootScan`. All fields optional —
/// anything we can't measure (TCC denial, hardware feature missing) is omitted
/// rather than guessed. snake_case keys to match the server's `formatDevice`.
struct DeviceSnapshot: Codable, Equatable {
    var model: String?
    var cpu: String?
    var ram_gb: Int?
    var ram_used_pct: Int?
    var disk_total_gb: Int?
    var disk_free_gb: Int?
    var disk_free_pct: Int?
    var cpu_load: Int?
    var battery_pct: Int?
    var charging: Bool?
    var chrome_tab_count: Int?
    var running_apps_count: Int?
    var uptime_hours: Int?
    var network: String?
    var warnings: [String]
}

/// One row in the "recent files" injection. snake_case keys (`full_path`) match
/// what `buddy.js` reads when it formats the `<RECENT_FILES>` block.
struct RecentFile: Codable, Equatable, Identifiable, Hashable {
    var name: String
    var app: String
    var modified: String      // ISO-8601 yyyy-MM-dd
    var full_path: String

    var id: String { full_path }
}

struct BuddyContext: Codable {
    var user_name: String?
    var greeting: Bool?
    var device: DeviceSnapshot?
    var recent_files: [RecentFile]?
}

// MARK: - REST payloads

/// `/v1/run` body. `mode` and `context` are buddy-layer additions; the server
/// silently ignores them if mode != "buddy".
struct RunRequest: Encodable {
    let prompt: String
    let model: String
    let session_id: String?
    let workspace: String
    let permission_mode: String
    let mode: String?
    let context: BuddyContext?
}

struct BudgetSnapshot: Decodable {
    let today_usd: Double
    let cap_usd: Double
    let month_usd: Double?
    let tier: String?
}

// MARK: - Model picker

enum DeepSeekModel: String, CaseIterable, Identifiable {
    case auto, flash, pro
    case pro1m = "pro-1m"

    var id: String { rawValue }

    /// Friendly Chinese label. Only `auto` and `pro-1m` are surfaced in the
    /// new buddy-mode UI ("流畅" vs "深度思考"); the other two stay around for
    /// power-user override via UserDefaults but aren't shown in Settings.
    var display: String {
        switch self {
        case .auto:  return "流畅 (推荐)"
        case .flash: return "Flash"
        case .pro:   return "Pro"
        case .pro1m: return "深度思考"
        }
    }
}
