import Foundation
import Combine

/// User-facing preferences. Backed by `UserDefaults` for non-secrets, and by
/// `~/Library/Application Support/DeepSeekHarness/env.sh` for the DeepSeek API
/// key (so the shell side `dsh.sh` / `first-run.sh` can source it).
///
/// We deliberately do NOT use Keychain tonight — the parallel shell stack
/// already standardizes on env.sh, and we want the two halves to share storage.
/// Keychain migration is a TODO for tomorrow's hardening pass.
@MainActor
final class Preferences: ObservableObject {

    static let shared = Preferences()

    // Non-secret prefs
    @Published var model: DeepSeekModel {
        didSet { UserDefaults.standard.set(model.rawValue, forKey: K.model) }
    }
    @Published var dailyBudgetUSD: Double {
        didSet { UserDefaults.standard.set(dailyBudgetUSD, forKey: K.budget) }
    }
    @Published var useCloud: Bool {
        didSet { UserDefaults.standard.set(useCloud, forKey: K.useCloud) }
    }
    @Published var cloudBaseURL: String {
        didSet { UserDefaults.standard.set(cloudBaseURL, forKey: K.cloudURL) }
    }
    @Published var cloudJWT: String {
        // TODO: move to Keychain
        didSet { UserDefaults.standard.set(cloudJWT, forKey: K.cloudJWT) }
    }

    // Secret-ish: the DeepSeek API key. Read on demand from env.sh; not held in
    // memory beyond the time it takes to write it.
    @Published private(set) var hasApiKey: Bool

    private enum K {
        static let model    = "dsh.model"
        static let budget   = "dsh.dailyBudgetUSD"
        static let useCloud = "dsh.useCloud"
        static let cloudURL = "dsh.cloudBaseURL"
        static let cloudJWT = "dsh.cloudJWT"
    }

    private init() {
        let d = UserDefaults.standard
        self.model = DeepSeekModel(rawValue: d.string(forKey: K.model) ?? "") ?? .auto
        self.dailyBudgetUSD = d.object(forKey: K.budget) as? Double ?? 5.0
        self.useCloud = d.bool(forKey: K.useCloud)
        self.cloudBaseURL = d.string(forKey: K.cloudURL) ?? "https://api.deepseek-harness.dev"
        self.cloudJWT = d.string(forKey: K.cloudJWT) ?? ""
        self.hasApiKey = Preferences.readApiKeyFromEnvFile() != nil
        Preferences.ensureBuddyWorkspace()
    }

    /// Auto-create `~/Documents/鲸伴小助手/` and use it as the agent's working
    /// directory. The user never sees the word "workspace" anywhere — buddy
    /// just operates here by default.
    static var buddyWorkspaceURL: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Documents/鲸伴小助手", isDirectory: true)
    }
    private static func ensureBuddyWorkspace() {
        try? FileManager.default.createDirectory(at: buddyWorkspaceURL,
                                                 withIntermediateDirectories: true)
    }

    // MARK: - Base URL

    var baseURL: URL {
        if useCloud, let u = URL(string: cloudBaseURL) {
            return u
        }
        return URL(string: "http://127.0.0.1:7777")!
    }

    var bearerToken: String? {
        useCloud && !cloudJWT.isEmpty ? cloudJWT : nil
    }

    // MARK: - API key handling

    static var supportDir: URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory,
                                            in: .userDomainMask).first
            ?? URL(fileURLWithPath: NSHomeDirectory() + "/Library/Application Support")
        return base.appendingPathComponent("DeepSeekHarness", isDirectory: true)
    }

    static var envFileURL: URL { supportDir.appendingPathComponent("env.sh") }

    /// Persist the API key by writing env.sh. We try to delegate the heavy
    /// lifting to bundled `first-run.sh` so the shell + desktop halves agree
    /// on file format; if the bundled script is missing (SPM dev build), we
    /// write a minimal env.sh ourselves.
    func saveApiKey(_ key: String) throws {
        try FileManager.default.createDirectory(at: Preferences.supportDir,
                                                withIntermediateDirectories: true)
        if let script = Bundle.main.path(forResource: "first-run", ofType: "sh") {
            let p = Process()
            p.executableURL = URL(fileURLWithPath: "/bin/bash")
            p.arguments = [script, "--yes"]
            var env = ProcessInfo.processInfo.environment
            env["DEEPSEEK_API_KEY"] = key
            env["WC_HOME"] = Preferences.supportDir.path
            env["YES"] = "1"
            p.environment = env
            try p.run()
            p.waitUntilExit()
            if p.terminationStatus != 0 {
                // Fall through to direct-write fallback.
                try writeEnvFallback(key: key)
            }
        } else {
            try writeEnvFallback(key: key)
        }
        self.hasApiKey = true
    }

    private func writeEnvFallback(key: String) throws {
        let escaped = key.replacingOccurrences(of: "\"", with: "\\\"")
        let body = """
        # written by DeepSeek Harness desktop (fallback)
        export DEEPSEEK_API_KEY="\(escaped)"
        export ANTHROPIC_BASE_URL="https://api.deepseek.com/anthropic"
        export ANTHROPIC_AUTH_TOKEN="$DEEPSEEK_API_KEY"

        """
        try body.write(to: Preferences.envFileURL, atomically: true, encoding: .utf8)
        // tighten perms
        try? FileManager.default.setAttributes([.posixPermissions: 0o600],
                                               ofItemAtPath: Preferences.envFileURL.path)
    }

    static func readApiKeyFromEnvFile() -> String? {
        guard let text = try? String(contentsOf: envFileURL, encoding: .utf8) else {
            return nil
        }
        for line in text.split(separator: "\n") {
            let trimmed = line.trimmingCharacters(in: .whitespaces)
            if trimmed.hasPrefix("export DEEPSEEK_API_KEY=") {
                var value = String(trimmed.dropFirst("export DEEPSEEK_API_KEY=".count))
                if value.hasPrefix("\"") && value.hasSuffix("\"") && value.count >= 2 {
                    value = String(value.dropFirst().dropLast())
                }
                return value.isEmpty ? nil : value
            }
        }
        return nil
    }

    func refreshApiKeyStatus() {
        hasApiKey = Preferences.readApiKeyFromEnvFile() != nil
    }
}
