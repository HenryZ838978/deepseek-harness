import SwiftUI

struct SettingsView: View {
    @EnvironmentObject var prefs: Preferences

    @State private var apiKey: String = ""
    @State private var saveMessage: String?
    @State private var saving = false

    @State private var automationStatus: PermissionStatus = .unknown
    @State private var fdaStatus: PermissionStatus = .unknown

    /// In the buddy-mode UI we only surface two choices: "流畅" (auto) and
    /// "深度思考" (pro-1m). Flash and Pro are still selectable via UserDefaults
    /// for power users but never shown here.
    private let helperOptions: [DeepSeekModel] = [.auto, .pro1m]

    var body: some View {
        Form {
            Section("DeepSeek API 密钥") {
                SecureField("sk-…", text: $apiKey)
                    .textContentType(.password)

                HStack {
                    if prefs.hasApiKey {
                        Label("已配置", systemImage: "checkmark.seal.fill")
                            .foregroundStyle(.green).font(.caption)
                    } else {
                        Label("还没填", systemImage: "exclamationmark.triangle.fill")
                            .foregroundStyle(.orange).font(.caption)
                    }
                    Spacer()
                    Link("去 deepseek.com 申请一个",
                         destination: URL(string: "https://platform.deepseek.com/api_keys")!)
                        .font(.caption)
                }

                HStack {
                    Spacer()
                    Button(saving ? "保存中…" : "保存") { saveKey() }
                        .disabled(apiKey.trimmingCharacters(in: .whitespaces).isEmpty || saving)
                        .keyboardShortcut(.return)
                }
                if let m = saveMessage {
                    Text(m).font(.caption).foregroundStyle(.secondary)
                }
            }

            Section("助手类型") {
                Picker("默认", selection: $prefs.model) {
                    ForEach(helperOptions) { m in Text(m.display).tag(m) }
                }
                .pickerStyle(.segmented)
                Text("「流畅」适合日常聊天、整理文件；「深度思考」适合写长文、分析复杂问题（慢一些，费用稍高）。")
                    .font(.caption).foregroundStyle(.secondary)
            }

            Section("每日费用上限") {
                HStack {
                    Slider(value: $prefs.dailyBudgetUSD, in: 1...50, step: 1)
                    Text(String(format: "¥%.0f", prefs.dailyBudgetUSD * 7.2))
                        .monospacedDigit()
                        .frame(width: 70, alignment: .trailing)
                }
                Text("到达 80% 会提醒，超出就会暂停。")
                    .font(.caption).foregroundStyle(.secondary)
            }

            Section("电脑权限") {
                permissionRow(
                    title: "允许识别 Chrome 浏览器",
                    subtitle: "用来告诉您 Chrome 标签数；不开也能用，但电脑状态会少一项。",
                    status: automationStatus,
                    openAction: Permissions.openAutomationPane
                )
                permissionRow(
                    title: "完整磁盘访问",
                    subtitle: "用来认识您在微信/飞书/钉钉里收到的文件。不开就只能看 桌面/文稿/下载。",
                    status: fdaStatus,
                    openAction: Permissions.openFullDiskAccessPane
                )
                HStack {
                    Spacer()
                    Button("重新检测") { refreshPermissions() }
                        .controlSize(.small)
                }
            }

            Section("云端备份（高级）") {
                Toggle("用云端跑任务（关上电脑也继续）", isOn: $prefs.useCloud)
                if prefs.useCloud {
                    TextField("服务器地址", text: $prefs.cloudBaseURL)
                    SecureField("登录凭证（临时）", text: $prefs.cloudJWT)
                }
                Text("默认所有事情都在您自己的 Mac 上完成。打开这个开关，长任务会接力到云端，关电脑也不会断。")
                    .font(.caption).foregroundStyle(.secondary)
                Text("TODO: v0.2 接入手机验证码登录，目前需要手填凭证。")
                    .font(.caption2).foregroundStyle(.tertiary)
            }

            Section {
                HStack {
                    Spacer()
                    Text("深求小助手 v\(appVersion())")
                        .font(.caption).foregroundStyle(.tertiary)
                }
            }
        }
        .formStyle(.grouped)
        .padding()
        .frame(width: 560, height: 620)
        .onAppear {
            prefs.refreshApiKeyStatus()
            refreshPermissions()
        }
    }

    // MARK: - permission row helper

    private func permissionRow(title: String,
                               subtitle: String,
                               status: PermissionStatus,
                               openAction: @escaping () -> Void) -> some View {
        HStack(alignment: .top, spacing: 10) {
            statusIcon(status)
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.body)
                Text(subtitle).font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            Button("去开启") { openAction() }
                .controlSize(.small)
        }
        .padding(.vertical, 2)
    }

    private func statusIcon(_ s: PermissionStatus) -> some View {
        Group {
            switch s {
            case .granted:
                Image(systemName: "checkmark.seal.fill").foregroundStyle(.green)
            case .denied:
                Image(systemName: "xmark.seal.fill").foregroundStyle(.red)
            case .unknown:
                Image(systemName: "questionmark.circle.fill").foregroundStyle(.gray)
            }
        }
        .font(.title3)
        .frame(width: 22)
    }

    private func refreshPermissions() {
        // Quick checks; the AppleScript probe takes ~1s if Chrome is running.
        DispatchQueue.global(qos: .userInitiated).async {
            let auto = Permissions.automationChromeStatus()
            let fda = Permissions.fullDiskAccessStatus()
            DispatchQueue.main.async {
                self.automationStatus = auto
                self.fdaStatus = fda
            }
        }
    }

    // MARK: - save key

    private func saveKey() {
        saving = true
        saveMessage = nil
        let key = apiKey
        Task {
            do {
                try prefs.saveApiKey(key)
                await MainActor.run {
                    apiKey = ""
                    saveMessage = "保存成功！"
                    saving = false
                }
            } catch {
                await MainActor.run {
                    saveMessage = "保存失败：\(error.localizedDescription)"
                    saving = false
                }
            }
        }
    }

    private func appVersion() -> String {
        Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String
            ?? "0.1.0-dev"
    }
}
