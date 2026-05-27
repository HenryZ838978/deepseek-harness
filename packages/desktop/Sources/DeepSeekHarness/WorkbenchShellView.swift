import SwiftUI

/// Seedance-inspired shell: top bar + resizable sidebar + flexible detail.
struct WorkbenchShellView: View {
    @EnvironmentObject var vm: ChatViewModel
    @EnvironmentObject var store: ConversationStore
    @EnvironmentObject var prefs: Preferences
    @EnvironmentObject var env: AppEnv

    @State private var columnVisibility: NavigationSplitViewVisibility = .all
    @AppStorage("dsh.sidebarWidth") private var sidebarWidth: Double = 240

    var body: some View {
        NavigationSplitView(columnVisibility: $columnVisibility) {
            SessionSidebarView()
                .navigationSplitViewColumnWidth(
                    min: 180,
                    ideal: CGFloat(sidebarWidth),
                    max: 360
                )
        } detail: {
            ChatView(presentation: .workbench)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .navigationTitle("鲸伴 · 工作台")
        .frame(minWidth: 720, minHeight: 560)
    }
}

struct SessionSidebarView: View {
    @EnvironmentObject var store: ConversationStore
    @EnvironmentObject var env: AppEnv

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                Text("对话")
                    .font(.headline)
                Spacer()
                Button {
                    store.newConversation()
                } label: {
                    Image(systemName: "plus.circle.fill")
                }
                .buttonStyle(.plain)
                .help("新建对话")
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 10)

            List(selection: Binding(
                get: { store.activeId },
                set: { if let id = $0 { store.select(id) } }
            )) {
                ForEach(store.conversations) { conv in
                    ConversationSidebarRow(conv: conv)
                        .tag(conv.id as String?)
                        .contextMenu {
                            Button("删除对话", role: .destructive) {
                                Task { await store.delete(conv.id) }
                            }
                        }
                }
            }
            .listStyle(.sidebar)

            Divider()

            VStack(alignment: .leading, spacing: 6) {
                Button("设置…") { env.openSettings() }
                    .buttonStyle(.plain)
                    .font(.caption)
            }
            .padding(10)
        }
        .background(Color(nsColor: .controlBackgroundColor))
    }
}

private struct ConversationSidebarRow: View {
    let conv: SessionDatabase.ConversationRow

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(conv.title)
                .font(.subheadline.weight(.medium))
                .lineLimit(2)
            Text(relativeTime(conv.lastActive))
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
        .padding(.vertical, 4)
    }

    private func relativeTime(_ d: Date) -> String {
        let f = RelativeDateTimeFormatter()
        f.locale = Locale(identifier: "zh_CN")
        return f.localizedString(for: d, relativeTo: Date())
    }
}
