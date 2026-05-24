import SwiftUI
import AppKit

struct ChatView: View {
    @EnvironmentObject var vm: ChatViewModel
    @EnvironmentObject var prefs: Preferences
    @EnvironmentObject var env: AppEnv

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider()
            if let err = vm.errorBanner {
                errorBanner(err)
            }
            messageList
            Divider()
            inputBar
        }
        .frame(width: 480, height: 640)
        .onAppear { vm.capUSD = prefs.dailyBudgetUSD }
        .onChange(of: prefs.dailyBudgetUSD) { new in vm.capUSD = new }
    }

    // MARK: - Header (intentionally choice-free: no model picker, no workspace)

    private var header: some View {
        HStack(spacing: 10) {
            Image(systemName: "fish.fill")
                .foregroundStyle(.tint)
            Text("深求小助手")
                .font(.headline)

            Spacer()

            deviceHealthPill
            budgetPill

            Menu {
                Button("新会话 (New Session)") { vm.newSession() }
                    .keyboardShortcut("n", modifiers: .command)
                Button("清空聊天 (Clear Chat)") { vm.clear() }
                    .keyboardShortcut("k", modifiers: .command)
                Divider()
                Button("设置… (Settings…)") { env.openSettings() }
                Divider()
                Button("退出 (Quit)") { env.quit() }
            } label: {
                Image(systemName: "ellipsis.circle")
            }
            .menuStyle(.borderlessButton)
            .fixedSize()
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
    }

    private var deviceHealthPill: some View {
        let health = vm.deviceHealth
        let color: Color = {
            switch health {
            case .unknown: return .gray
            case .green:   return .green
            case .yellow:  return .yellow
            case .red:     return .red
            }
        }()
        let warningCount = vm.deviceSnapshot?.warnings.count ?? 0
        return Button {
            // One-tap diagnostic — let the buddy interpret the snapshot.
            vm.send(prompt: "帮我看看电脑现在怎么样，有什么可以优化的吗？")
        } label: {
            HStack(spacing: 4) {
                Circle().fill(color).frame(width: 8, height: 8)
                Text(health == .red && warningCount > 0
                     ? "电脑 ⚠️\(warningCount)"
                     : "电脑")
                    .font(.caption)
            }
            .padding(.horizontal, 8).padding(.vertical, 4)
            .background(.quaternary, in: Capsule())
        }
        .buttonStyle(.plain)
        .help(deviceTooltip)
    }

    private var deviceTooltip: String {
        guard let d = vm.deviceSnapshot else { return "正在检测设备状态…" }
        var parts: [String] = []
        if let m = d.model { parts.append(m) }
        if let r = d.ram_gb { parts.append("内存 \(r)GB（已用 \(d.ram_used_pct ?? 0)%）") }
        if let f = d.disk_free_gb, let p = d.disk_free_pct { parts.append("剩余 \(f)GB / \(p)%") }
        if let b = d.battery_pct { parts.append("电量 \(b)%") }
        if !d.warnings.isEmpty { parts.append("⚠️ " + d.warnings.joined(separator: "；")) }
        parts.append("👉 点击让助手解读")
        return parts.joined(separator: "\n")
    }

    private var budgetPill: some View {
        let ratio = vm.budgetRatio
        let color: Color = ratio >= 1.0 ? .red : (ratio >= 0.8 ? .yellow : .green)
        return HStack(spacing: 4) {
            Circle().fill(color).frame(width: 8, height: 8)
            Text(String(format: "今日 ¥%.2f / ¥%.2f", vm.todayRMB, vm.capRMB))
                .font(.caption.monospacedDigit())
        }
        .padding(.horizontal, 8).padding(.vertical, 4)
        .background(.quaternary, in: Capsule())
        .help("今日花费 / 每日上限")
    }

    private func errorBanner(_ msg: String) -> some View {
        HStack(alignment: .top, spacing: 6) {
            Image(systemName: "exclamationmark.triangle.fill")
                .foregroundStyle(.orange)
            Text(msg)
                .font(.caption)
                .textSelection(.enabled)
            Spacer()
            Button {
                vm.errorBanner = nil
            } label: { Image(systemName: "xmark.circle.fill") }
                .buttonStyle(.plain)
                .foregroundStyle(.secondary)
        }
        .padding(8)
        .background(Color.orange.opacity(0.12))
    }

    // MARK: - Messages

    private var messageList: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 12) {
                    if vm.messages.isEmpty {
                        emptyState
                            .padding(.top, 60)
                    } else {
                        ForEach(vm.messages) { msg in
                            MessageBubble(message: msg)
                                .id(msg.id)
                        }
                    }
                }
                .padding(12)
            }
            .background(Color(nsColor: .textBackgroundColor))
            .onChange(of: vm.messages.last?.id) { id in
                if let id = id { withAnimation { proxy.scrollTo(id, anchor: .bottom) } }
            }
            .onChange(of: vm.currentAssistantText) { _ in
                if let id = vm.messages.last?.id {
                    proxy.scrollTo(id, anchor: .bottom)
                }
            }
        }
    }

    private var emptyState: some View {
        VStack(spacing: 8) {
            Image(systemName: "fish.fill")
                .font(.system(size: 36))
                .foregroundStyle(.tint.opacity(0.5))
            Text("您好，我是深求小助手")
                .font(.callout)
                .foregroundStyle(.secondary)
            Text("有什么想让我帮忙的，直接告诉我就行～")
                .font(.caption2)
                .foregroundStyle(.tertiary)
        }
        .frame(maxWidth: .infinity)
    }

    // MARK: - Input

    private var inputBar: some View {
        HStack(alignment: .bottom, spacing: 8) {
            ZStack(alignment: .topLeading) {
                if vm.input.isEmpty {
                    Text("跟我说点什么…")
                        .foregroundStyle(.tertiary)
                        .padding(.horizontal, 8)
                        .padding(.vertical, 6)
                        .allowsHitTesting(false)
                }
                TextEditor(text: $vm.input)
                    .font(.body)
                    .scrollContentBackground(.hidden)
                    .padding(.horizontal, 4)
                    .padding(.vertical, 2)
            }
            .frame(minHeight: 36, maxHeight: 110)
            .background(Color(nsColor: .textBackgroundColor))
            .overlay(RoundedRectangle(cornerRadius: 8)
                .stroke(Color(nsColor: .separatorColor), lineWidth: 1))

            if vm.isStreaming {
                Button(action: vm.cancel) {
                    Image(systemName: "stop.circle.fill")
                        .font(.system(size: 22))
                }
                .buttonStyle(.plain)
                .foregroundStyle(.red)
                .help("停一下")
            } else {
                Button(action: { vm.send() }) {
                    Image(systemName: "paperplane.circle.fill")
                        .font(.system(size: 22))
                }
                .buttonStyle(.plain)
                .keyboardShortcut(.return, modifiers: [.command])
                .disabled(vm.input.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                .help("发送 ⌘↩")
            }
        }
        .padding(10)
    }
}

// MARK: - Bubble

private struct MessageBubble: View {
    let message: ChatMessage
    @State private var isHovering = false

    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            avatar
            VStack(alignment: .leading, spacing: 4) {
                roleLine
                content
            }
            Spacer(minLength: 0)
        }
        .padding(8)
        .background(bubbleBg, in: RoundedRectangle(cornerRadius: 10))
        .onHover { isHovering = $0 }
        .contextMenu {
            Button("复制") { copyToPasteboard(message.text) }
        }
    }

    private var avatar: some View {
        Group {
            switch message.role {
            case .user:
                Image(systemName: "person.circle.fill")
                    .foregroundStyle(.blue)
            case .assistant:
                Image(systemName: "fish.fill")
                    .foregroundStyle(.tint)
            case .system:
                Image(systemName: "gear")
                    .foregroundStyle(.secondary)
            }
        }
        .font(.system(size: 18))
        .frame(width: 22, height: 22)
    }

    private var roleLine: some View {
        HStack(spacing: 6) {
            Text(roleLabel).font(.caption.bold())
            if message.isStreaming {
                ProgressView().controlSize(.mini)
            }
        }
        .foregroundStyle(.secondary)
    }

    private var roleLabel: String {
        switch message.role {
        case .user:      return "您"
        case .assistant: return "深求"
        case .system:    return "系统"
        }
    }

    @ViewBuilder
    private var content: some View {
        if message.isStreaming {
            Text(message.text)
                .textSelection(.enabled)
                .font(.body)
                .fixedSize(horizontal: false, vertical: true)
        } else {
            if let attr = try? AttributedString(
                markdown: message.text,
                options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace)
            ) {
                Text(attr)
                    .textSelection(.enabled)
                    .font(.body)
                    .fixedSize(horizontal: false, vertical: true)
            } else {
                Text(message.text)
                    .textSelection(.enabled)
                    .font(.body)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private var bubbleBg: Color {
        switch message.role {
        case .user:      return Color.blue.opacity(0.10)
        case .assistant: return Color.gray.opacity(0.08)
        case .system:    return Color.yellow.opacity(0.10)
        }
    }

    private func copyToPasteboard(_ s: String) {
        let pb = NSPasteboard.general
        pb.clearContents()
        pb.setString(s, forType: .string)
    }
}
