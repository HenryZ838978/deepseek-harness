import Foundation
import SQLite3

/// Local SQLite persistence for multi-tab conversations (Seedance-style sidebar).
/// Server JSON sessions remain the source of truth for claude --resume; this DB
/// mirrors titles/messages for fast UI restore and offline sidebar.
@MainActor
final class SessionDatabase {
    static let shared = SessionDatabase()

    private var db: OpaquePointer?

    private init() {
        let dir = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
            .appendingPathComponent("DeepSeekHarness", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let path = dir.appendingPathComponent("sessions.db").path
        if sqlite3_open(path, &db) != SQLITE_OK {
            NSLog("[SessionDatabase] open failed: \(String(cString: sqlite3_errmsg(db)))")
            return
        }
        migrate()
    }

    deinit { if db != nil { sqlite3_close(db) } }

    private func migrate() {
        exec("""
        CREATE TABLE IF NOT EXISTS conversations (
          id TEXT PRIMARY KEY,
          server_session_id TEXT,
          title TEXT NOT NULL DEFAULT '新对话',
          model TEXT NOT NULL DEFAULT 'auto',
          draft TEXT,
          last_active REAL NOT NULL,
          created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS messages (
          id TEXT PRIMARY KEY,
          conversation_id TEXT NOT NULL,
          role TEXT NOT NULL,
          text TEXT NOT NULL,
          is_streaming INTEGER NOT NULL DEFAULT 0,
          sort_order INTEGER NOT NULL,
          created_at REAL NOT NULL,
          FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id, sort_order);
        """)
    }

    // MARK: - Conversations

    struct ConversationRow: Identifiable, Equatable {
        let id: String
        var serverSessionId: String?
        var title: String
        var model: String
        var draft: String
        var lastActive: Date
    }

    func listConversations() -> [ConversationRow] {
        var rows: [ConversationRow] = []
        query("SELECT id, server_session_id, title, model, draft, last_active FROM conversations ORDER BY last_active DESC") { stmt in
            rows.append(rowFrom(stmt))
        }
        return rows
    }

    func getConversation(id: String) -> ConversationRow? {
        var found: ConversationRow?
        query("SELECT id, server_session_id, title, model, draft, last_active FROM conversations WHERE id = ?", bind: { stmt in
            sqlite3_bind_text(stmt, 1, id, -1, SQLITE_TRANSIENT)
        }) { stmt in
            found = rowFrom(stmt)
        }
        return found
    }

    @discardableResult
    func upsertConversation(_ c: ConversationRow) {
        exec("""
        INSERT INTO conversations (id, server_session_id, title, model, draft, last_active, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
          server_session_id=excluded.server_session_id,
          title=excluded.title,
          model=excluded.model,
          draft=excluded.draft,
          last_active=excluded.last_active
        """, bind: { stmt in
            self.bindText(stmt, 1, c.id)
            self.bindOptText(stmt, 2, c.serverSessionId)
            self.bindText(stmt, 3, c.title)
            self.bindText(stmt, 4, c.model)
            self.bindText(stmt, 5, c.draft)
            sqlite3_bind_double(stmt, 6, c.lastActive.timeIntervalSince1970)
            sqlite3_bind_double(stmt, 7, c.lastActive.timeIntervalSince1970)
        })
    }

    func deleteConversation(id: String) {
        exec("DELETE FROM messages WHERE conversation_id = ?", bind: { sqlite3_bind_text($0, 1, id, -1, SQLITE_TRANSIENT) })
        exec("DELETE FROM conversations WHERE id = ?", bind: { sqlite3_bind_text($0, 1, id, -1, SQLITE_TRANSIENT) })
    }

    func touchConversation(id: String, title: String? = nil) {
        if let title = title {
            exec("UPDATE conversations SET last_active = ?, title = ? WHERE id = ?", bind: { stmt in
                sqlite3_bind_double(stmt, 1, Date().timeIntervalSince1970)
                self.bindText(stmt, 2, title)
                self.bindText(stmt, 3, id)
            })
        } else {
            exec("UPDATE conversations SET last_active = ? WHERE id = ?", bind: { stmt in
                sqlite3_bind_double(stmt, 1, Date().timeIntervalSince1970)
                self.bindText(stmt, 2, id)
            })
        }
    }

    func setServerSessionId(conversationId: String, serverId: String) {
        exec("UPDATE conversations SET server_session_id = ? WHERE id = ?", bind: { stmt in
            self.bindText(stmt, 1, serverId)
            self.bindText(stmt, 2, conversationId)
        })
    }

    func saveDraft(conversationId: String, draft: String) {
        exec("UPDATE conversations SET draft = ?, last_active = ? WHERE id = ?", bind: { stmt in
            self.bindText(stmt, 1, draft)
            sqlite3_bind_double(stmt, 2, Date().timeIntervalSince1970)
            self.bindText(stmt, 3, conversationId)
        })
    }

    // MARK: - Messages

    func loadMessages(conversationId: String) -> [ChatMessage] {
        var out: [ChatMessage] = []
        query("""
        SELECT id, role, text, is_streaming, created_at FROM messages
        WHERE conversation_id = ? ORDER BY sort_order ASC
        """, bind: { sqlite3_bind_text($0, 1, conversationId, -1, SQLITE_TRANSIENT) }) { stmt in
            let idStr = String(cString: sqlite3_column_text(stmt, 0))
            let roleStr = String(cString: sqlite3_column_text(stmt, 1))
            let text = String(cString: sqlite3_column_text(stmt, 2))
            let streaming = sqlite3_column_int(stmt, 3) != 0
            let ts = Date(timeIntervalSince1970: sqlite3_column_double(stmt, 4))
            let role = MessageRole(rawValue: roleStr) ?? .assistant
            out.append(ChatMessage(id: UUID(uuidString: idStr) ?? UUID(),
                                   role: role, text: text,
                                   isStreaming: streaming, createdAt: ts))
        }
        return out
    }

    func replaceMessages(conversationId: String, messages: [ChatMessage]) {
        exec("DELETE FROM messages WHERE conversation_id = ?", bind: {
            sqlite3_bind_text($0, 1, conversationId, -1, SQLITE_TRANSIENT)
        })
        for (i, m) in messages.enumerated() {
            exec("""
            INSERT INTO messages (id, conversation_id, role, text, is_streaming, sort_order, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """, bind: { stmt in
                self.bindText(stmt, 1, m.id.uuidString)
                self.bindText(stmt, 2, conversationId)
                self.bindText(stmt, 3, m.role.rawValue)
                self.bindText(stmt, 4, m.text)
                sqlite3_bind_int(stmt, 5, m.isStreaming ? 1 : 0)
                sqlite3_bind_int(stmt, 6, Int32(i))
                sqlite3_bind_double(stmt, 7, m.createdAt.timeIntervalSince1970)
            })
        }
    }

    // MARK: - SQLite helpers

    private func rowFrom(_ stmt: OpaquePointer?) -> ConversationRow {
        let id = String(cString: sqlite3_column_text(stmt, 0))
        let sid: String? = sqlite3_column_type(stmt, 1) == SQLITE_NULL ? nil :
            String(cString: sqlite3_column_text(stmt, 1))
        let title = String(cString: sqlite3_column_text(stmt, 2))
        let model = String(cString: sqlite3_column_text(stmt, 3))
        let draft = sqlite3_column_type(stmt, 4) == SQLITE_NULL ? "" :
            String(cString: sqlite3_column_text(stmt, 4))
        let last = Date(timeIntervalSince1970: sqlite3_column_double(stmt, 5))
        return ConversationRow(id: id, serverSessionId: sid, title: title,
                              model: model, draft: draft, lastActive: last)
    }

    private func exec(_ sql: String, bind: ((OpaquePointer?) -> Void)? = nil) {
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { return }
        defer { sqlite3_finalize(stmt) }
        bind?(stmt)
        if sqlite3_step(stmt) != SQLITE_DONE {
            NSLog("[SessionDatabase] exec: \(String(cString: sqlite3_errmsg(db)))")
        }
    }

    private func query(_ sql: String, bind: ((OpaquePointer?) -> Void)? = nil,
                       row: (OpaquePointer?) -> Void) {
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else { return }
        defer { sqlite3_finalize(stmt) }
        bind?(stmt)
        while sqlite3_step(stmt) == SQLITE_ROW { row(stmt) }
    }

    private func bindText(_ stmt: OpaquePointer?, _ idx: Int32, _ s: String) {
        sqlite3_bind_text(stmt, idx, s, -1, SQLITE_TRANSIENT)
    }
    private func bindOptText(_ stmt: OpaquePointer?, _ idx: Int32, _ s: String?) {
        if let s = s { self.bindText(stmt, idx, s) }
        else { sqlite3_bind_null(stmt, idx) }
    }
}

private let SQLITE_TRANSIENT = unsafeBitCast(-1, to: sqlite3_destructor_type.self)
