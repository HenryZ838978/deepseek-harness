import Foundation
import Combine

/// Multi-tab conversation sidebar — mirrors Seedance left-rail + server /v1/sessions.
@MainActor
final class ConversationStore: ObservableObject {
    @Published private(set) var conversations: [SessionDatabase.ConversationRow] = []
    @Published var activeId: String?

    weak var chatVM: ChatViewModel?

    private let db = SessionDatabase.shared

    func bootstrap() async {
        await syncFromServer()
        if conversations.isEmpty {
            _ = createLocal(title: "新对话")
        }
        if activeId == nil, let first = conversations.first?.id {
            select(first, persistCurrent: false)
        }
    }

    @discardableResult
    func createLocal(title: String = "新对话") -> String {
        let id = UUID().uuidString
        let row = SessionDatabase.ConversationRow(
            id: id, serverSessionId: nil, title: title,
            model: Preferences.shared.model.rawValue, draft: "",
            lastActive: Date()
        )
        db.upsertConversation(row)
        reloadList()
        return id
    }

    func newConversation() {
        persistActiveChat()
        let id = createLocal()
        select(id, persistCurrent: false)
    }

    func select(_ id: String, persistCurrent: Bool = true) {
        if persistCurrent { persistActiveChat() }
        activeId = id
        guard let vm = chatVM else { return }
        guard let row = db.getConversation(id: id) else { return }
        vm.loadConversation(row: row, messages: db.loadMessages(conversationId: id))
    }

    func delete(_ id: String) async {
        if let sid = db.getConversation(id: id)?.serverSessionId {
            try? await deleteServerSession(sid)
        }
        db.deleteConversation(id: id)
        reloadList()
        if activeId == id {
            if let next = conversations.first?.id {
                select(next, persistCurrent: false)
            } else {
                let nid = createLocal()
                select(nid, persistCurrent: false)
            }
        }
    }

    func persistActiveChat() {
        guard let id = activeId, let vm = chatVM else { return }
        db.replaceMessages(conversationId: id, messages: vm.messages)
        db.saveDraft(conversationId: id, draft: vm.input)
        if let sid = vm.sessionID {
            db.setServerSessionId(conversationId: id, serverId: sid)
        }
        var row = db.getConversation(id: id) ?? SessionDatabase.ConversationRow(
            id: id, serverSessionId: vm.sessionID, title: "新对话",
            model: vm.prefsModelRaw, draft: vm.input, lastActive: Date()
        )
        row.title = deriveTitle(from: vm.messages, fallback: row.title)
        row.lastActive = Date()
        db.upsertConversation(row)
        reloadList()
    }

    func onServerSessionId(_ serverId: String) {
        guard let id = activeId else { return }
        db.setServerSessionId(conversationId: id, serverId: serverId)
        reloadList()
    }

    func reloadList() {
        conversations = db.listConversations()
    }

    // MARK: - Server sync

    func syncFromServer() async {
        guard let data = try? await fetchSessions() else { return }
        struct Resp: Decodable { let sessions: [S] }
        struct S: Decodable {
            let id: String
            let title: String?
            let model: String?
            let last_active: Double?
        }
        guard let resp = try? JSONDecoder().decode(Resp.self, from: data) else { return }
        for s in resp.sessions {
            let convId = db.listConversations().first(where: { $0.serverSessionId == s.id })?.id ?? UUID().uuidString
            let row = SessionDatabase.ConversationRow(
                id: convId,
                serverSessionId: s.id,
                title: s.title ?? "(untitled)",
                model: s.model ?? "auto",
                draft: db.getConversation(id: convId)?.draft ?? "",
                lastActive: Date(timeIntervalSince1970: (s.last_active ?? 0) / 1000)
            )
            db.upsertConversation(row)
        }
        reloadList()
    }

    private func fetchSessions() async throws -> Data {
        let prefs = Preferences.shared
        var req = URLRequest(url: prefs.baseURL.appendingPathComponent("v1/sessions"))
        if let tok = prefs.bearerToken {
            req.setValue("Bearer \(tok)", forHTTPHeaderField: "Authorization")
        }
        let (data, resp) = try await URLSession.shared.data(for: req)
        guard (resp as? HTTPURLResponse)?.statusCode == 200 else { throw URLError(.badServerResponse) }
        return data
    }

    private func deleteServerSession(_ id: String) async throws {
        let prefs = Preferences.shared
        var req = URLRequest(url: prefs.baseURL.appendingPathComponent("v1/sessions/\(id)"))
        req.httpMethod = "DELETE"
        if let tok = prefs.bearerToken {
            req.setValue("Bearer \(tok)", forHTTPHeaderField: "Authorization")
        }
        _ = try await URLSession.shared.data(for: req)
    }

    private func deriveTitle(from messages: [ChatMessage], fallback: String) -> String {
        if let first = messages.first(where: { $0.role == .user })?.text {
            let line = first.split(separator: "\n").first.map(String.init) ?? first
            return String(line.prefix(40))
        }
        return fallback
    }
}
