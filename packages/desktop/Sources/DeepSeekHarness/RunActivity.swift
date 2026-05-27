import Foundation
import SwiftUI

// MARK: - Activity models (mirrors LarksorTC collapsible panels)

struct TodoItem: Codable, Equatable, Identifiable {
    var id: String
    var content: String
    var status: String

    var statusIcon: String {
        switch status.lowercased() {
        case "in_progress": return "🔄"
        case "completed":   return "✅"
        case "cancelled":   return "✗"
        default:            return "○"
        }
    }
}

struct ToolActivity: Identifiable, Equatable {
    let id: String
    var name: String
    var label: String
    var statusIcon: String
    var elapsedMs: Int?
}

struct TodoEvent: Decodable {
    let todos: [TodoItem]
}

// MARK: - Collapsible panels (Thinking / Todos / Tools)

struct CollapsiblePanelsView: View {
    @ObservedObject var vm: ChatViewModel

    var body: some View {
        VStack(spacing: 6) {
            if vm.hasThinkingPanel {
                CollapsiblePanel(
                    title: vm.thinkingHeader,
                    isExpanded: $vm.thinkingExpanded,
                    tint: .purple
                ) {
                    Text(vm.thinkingText)
                        .font(.system(.caption, design: .monospaced))
                        .textSelection(.enabled)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
            }

            if !vm.todos.isEmpty {
                CollapsiblePanel(
                    title: vm.todosHeader,
                    isExpanded: $vm.todosExpanded,
                    tint: .blue
                ) {
                    VStack(alignment: .leading, spacing: 4) {
                        ForEach(vm.todos) { t in
                            HStack(alignment: .top, spacing: 6) {
                                Text(t.statusIcon).font(.caption)
                                Text(todoLine(t))
                                    .font(.caption)
                                    .textSelection(.enabled)
                            }
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
            }

            if !vm.tools.isEmpty {
                CollapsiblePanel(
                    title: vm.toolsHeader,
                    isExpanded: $vm.toolsExpanded,
                    tint: .orange
                ) {
                    VStack(alignment: .leading, spacing: 4) {
                        ForEach(vm.tools) { t in
                            HStack(spacing: 6) {
                                Text(t.statusIcon).font(.caption)
                                Text(t.label)
                                    .font(.system(.caption, design: .monospaced))
                                    .textSelection(.enabled)
                                if let ms = t.elapsedMs {
                                    Text("\(ms)ms")
                                        .font(.caption2)
                                        .foregroundStyle(.tertiary)
                                }
                            }
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 6)
    }

    private func todoLine(_ t: TodoItem) -> String {
        let c = t.content.trimmingCharacters(in: .whitespacesAndNewlines)
        switch t.status.lowercased() {
        case "completed": return "~~\(c)~~"
        case "in_progress": return "**\(c)**"
        case "cancelled": return "_\(c)_"
        default: return c
        }
    }
}

private struct CollapsiblePanel<Content: View>: View {
    let title: String
    @Binding var isExpanded: Bool
    var tint: Color = .accentColor
    @ViewBuilder let content: () -> Content

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Button {
                withAnimation(.easeInOut(duration: 0.2)) { isExpanded.toggle() }
            } label: {
                HStack(spacing: 6) {
                    Image(systemName: isExpanded ? "chevron.down" : "chevron.right")
                        .font(.caption2.weight(.semibold))
                        .foregroundStyle(.secondary)
                    Text(title)
                        .font(.caption.weight(.medium))
                        .foregroundStyle(tint)
                    Spacer()
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)

            if isExpanded {
                content()
                    .padding(.top, 6)
                    .padding(.leading, 18)
            }
        }
        .padding(8)
        .background(Color(nsColor: .controlBackgroundColor).opacity(0.6),
                    in: RoundedRectangle(cornerRadius: 8))
    }
}

// MARK: - Agent console (workbench terminal strip)

struct AgentConsoleView: View {
  @ObservedObject var vm: ChatViewModel

  var body: some View {
    VStack(alignment: .leading, spacing: 4) {
      HStack {
        Text("Agent 控制台")
          .font(.caption.bold())
        Spacer()
        Button("清空") { vm.clearConsole() }
          .font(.caption)
          .buttonStyle(.plain)
      }
      .padding(.horizontal, 10)
      .padding(.top, 6)

      ScrollViewReader { proxy in
        ScrollView {
          LazyVStack(alignment: .leading, spacing: 2) {
            ForEach(Array(vm.consoleLines.enumerated()), id: \.offset) { idx, line in
              Text(line)
                .font(.system(size: 11, design: .monospaced))
                .foregroundStyle(.secondary)
                .textSelection(.enabled)
                .id(idx)
            }
          }
          .padding(.horizontal, 10)
          .padding(.bottom, 8)
        }
        .frame(maxHeight: 140)
        .background(Color(nsColor: .textBackgroundColor))
        .onChange(of: vm.consoleLines.count) { _ in
          if let last = vm.consoleLines.indices.last {
            withAnimation { proxy.scrollTo(last, anchor: .bottom) }
          }
        }
      }
    }
  }
}
