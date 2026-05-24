import SwiftUI

struct FirstRunView: View {
    @EnvironmentObject var prefs: Preferences

    let onDone: () -> Void

    @State private var apiKey: String = ""
    @State private var status: String?
    @State private var saving = false
    @State private var success = false

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack(spacing: 12) {
                Image(systemName: "fish.fill")
                    .font(.system(size: 42))
                    .foregroundStyle(.tint)
                VStack(alignment: .leading, spacing: 2) {
                    Text("欢迎使用 深求")
                        .font(.title2.bold())
                    Text("Welcome to DeepSeek Harness")
                        .foregroundStyle(.secondary)
                }
            }

            Divider()

            if success {
                VStack(alignment: .leading, spacing: 10) {
                    Label("配置完成！(Setup complete!)",
                          systemImage: "checkmark.seal.fill")
                        .foregroundStyle(.green)
                        .font(.headline)
                    Text("点击菜单栏中的 🐟 图标即可开始对话。")
                        .font(.callout)
                    Text("Click the fish icon in the menubar to start.")
                        .font(.callout).foregroundStyle(.secondary)
                    Spacer()
                    HStack {
                        Spacer()
                        Button("好的 (OK)") { onDone() }
                            .keyboardShortcut(.return)
                    }
                }
            } else {
                Text("第一步：粘贴你的 DeepSeek API 密钥。")
                    .font(.headline)
                Text("Step 1: paste your DeepSeek API key.")
                    .foregroundStyle(.secondary)

                SecureField("sk-…", text: $apiKey)
                    .textFieldStyle(.roundedBorder)
                    .font(.system(.body, design: .monospaced))

                HStack {
                    Link("还没有？点这里申请 (Get a key)",
                         destination: URL(string: "https://platform.deepseek.com/api_keys")!)
                        .font(.callout)
                    Spacer()
                }

                if let s = status {
                    Text(s).font(.caption).foregroundStyle(.secondary)
                }

                Spacer()

                HStack {
                    Button("稍后再说 (Later)") { onDone() }
                    Spacer()
                    Button(saving ? "保存中… (Saving…)" : "保存并开始 (Save & Start)") {
                        saveAndContinue()
                    }
                    .keyboardShortcut(.return)
                    .disabled(apiKey.trimmingCharacters(in: .whitespaces).isEmpty || saving)
                }
            }
        }
        .padding(28)
        .frame(width: 560, height: 420)
    }

    private func saveAndContinue() {
        saving = true
        status = nil
        let key = apiKey
        Task {
            do {
                try prefs.saveApiKey(key)
                await MainActor.run {
                    success = true
                    saving = false
                }
            } catch {
                await MainActor.run {
                    status = "保存失败: \(error.localizedDescription)"
                    saving = false
                }
            }
        }
    }
}
