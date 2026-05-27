import AppKit
import SwiftUI
import Combine

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {

    private var statusItem: NSStatusItem!
    private var popover: NSPopover!
    private var settingsWindow: NSWindow?
    private var firstRunWindow: NSWindow?
    private var workbenchWindow: NSWindow?

    let server = EmbeddedServer()
    let chatVM = ChatViewModel()
    let conversationStore = ConversationStore()
    let prefs = Preferences.shared

    // Buddy-layer background actors.
    let bootScan = BootScan()
    let fileIndex = FileIndex()
    private var fileIndexTimer: Timer?

    private var monitor: Any?

    func applicationDidFinishLaunching(_ notification: Notification) {
        // Kick off embedded server in the background. Failure is non-fatal —
        // ChatViewModel will surface a friendly error if no one is on 127.0.0.1:7777.
        server.start()

        // Wire the buddy actors into the chat view-model.
        chatVM.bootScan = bootScan
        chatVM.fileIndex = fileIndex
        chatVM.conversationStore = conversationStore
        conversationStore.chatVM = chatVM

        buildStatusItem()
        buildPopover()
        registerHotkeys()

        // Boot scan + initial file walk + proactive greeting — all kicked off
        // in the background so the menubar icon appears instantly.
        Task { [weak self] in
            guard let self = self else { return }
            await self.conversationStore.bootstrap()
            // Warm the caches: device snapshot + file index can both fire
            // before the user clicks anything.
            async let _ = self.bootScan.snapshot()
            async let _ = self.fileIndex.refresh()
            _ = await (self.bootScan.snapshot(), self.fileIndex.refresh())

            // Now the proactive greeting (only if API key is configured — no
            // point burning tokens if the request will fail with auth).
            if self.prefs.hasApiKey {
                await MainActor.run { self.chatVM.proactiveGreeting() }
            }
        }

        // Refresh file index every 5 minutes.
        fileIndexTimer = Timer.scheduledTimer(withTimeInterval: 300,
                                              repeats: true) { [weak self] _ in
            guard let self = self else { return }
            Task { await self.fileIndex.refresh() }
        }

        // First-run: if user has never saved an API key, pop the welcome window.
        if !prefs.hasApiKey {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) { [weak self] in
                self?.showFirstRun()
            }
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        fileIndexTimer?.invalidate()
        server.stop()
    }

    // MARK: - Status item

    private func buildStatusItem() {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        if let button = statusItem.button {
            // SF Symbol fallback — until we ship a real whale glyph.
            let img = NSImage(systemSymbolName: "fish.fill",
                              accessibilityDescription: "DeepSeek Harness")
            img?.isTemplate = true
            button.image = img
            button.toolTip = "鲸伴 (DeepSeek Harness)"
            button.action = #selector(togglePopover(_:))
            button.target = self
            button.sendAction(on: [.leftMouseUp, .rightMouseUp])
        }
    }

    // MARK: - Popover

    private func buildPopover() {
        popover = NSPopover()
        popover.contentSize = NSSize(width: 480, height: 640)
        popover.behavior = .transient
        popover.animates = true
        let root = ChatView()
            .environmentObject(chatVM)
            .environmentObject(prefs)
            .environmentObject(self.asEnv)
        popover.contentViewController = NSHostingController(rootView: root)
    }

    // Tiny wrapper so SwiftUI views can ask the delegate to open Settings etc.
    lazy var asEnv: AppEnv = AppEnv(
        openSettings: { [weak self] in self?.showSettings() },
        openWorkbench: { [weak self] in self?.showWorkbench() },
        openFirstRun: { [weak self] in self?.showFirstRun() },
        quit:         { NSApp.terminate(nil) }
    )

    @objc private func togglePopover(_ sender: AnyObject?) {
        guard let button = statusItem.button else { return }

        if let event = NSApp.currentEvent, event.type == .rightMouseUp {
            showContextMenu(from: button)
            return
        }

        if popover.isShown {
            popover.performClose(sender)
        } else {
            NSApp.activate(ignoringOtherApps: true)
            popover.show(relativeTo: button.bounds, of: button, preferredEdge: .minY)
            // Tap ESC to close — global local monitor.
            installEscMonitor()
        }
    }

    private func showContextMenu(from button: NSStatusBarButton) {
        let menu = NSMenu()
        menu.addItem(withTitle: "新会话 (New Session) ⌘N",
                     action: #selector(menuNewSession), keyEquivalent: "")
        menu.addItem(withTitle: "清空聊天 (Clear Chat) ⌘K",
                     action: #selector(menuClearChat), keyEquivalent: "")
        menu.addItem(.separator())
        menu.addItem(withTitle: "打开工作台 (Workbench)",
                     action: #selector(menuWorkbench), keyEquivalent: "")
        menu.addItem(withTitle: "设置… (Settings…)",
                     action: #selector(menuSettings), keyEquivalent: "")
        menu.addItem(.separator())
        menu.addItem(withTitle: "退出 (Quit)",
                     action: #selector(menuQuit), keyEquivalent: "")
        for item in menu.items { item.target = self }
        statusItem.menu = menu
        button.performClick(nil)
        // Clear so left-click reverts to popover.
        statusItem.menu = nil
    }

    @objc private func menuNewSession() { conversationStore.newConversation() }
    @objc private func menuClearChat()  { chatVM.clear() }
    @objc private func menuWorkbench()  { showWorkbench() }
    @objc private func menuSettings()   { showSettings() }
    @objc private func menuQuit()       { NSApp.terminate(nil) }

    // MARK: - Workbench window (dockable terminal-style UI)

    func showWorkbench() {
        if let w = workbenchWindow {
            w.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
            return
        }
        let root = WorkbenchShellView()
            .environmentObject(chatVM)
            .environmentObject(conversationStore)
            .environmentObject(prefs)
            .environmentObject(asEnv)
        let host = NSHostingController(rootView: root)
        let w = NSWindow(contentViewController: host)
        w.title = "鲸伴 · 工作台"
        w.setContentSize(NSSize(width: 960, height: 720))
        w.minSize = NSSize(width: 720, height: 560)
        w.styleMask = [.titled, .closable, .miniaturizable, .resizable]
        w.isReleasedWhenClosed = false
        w.center()
        workbenchWindow = w
        w.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    // MARK: - Settings window

    func showSettings() {
        if let w = settingsWindow {
            w.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
            return
        }
        let view = SettingsView().environmentObject(prefs)
        let host = NSHostingController(rootView: view)
        let w = NSWindow(contentViewController: host)
        w.title = "设置 (Settings)"
        w.setContentSize(NSSize(width: 520, height: 460))
        w.styleMask = [.titled, .closable, .miniaturizable]
        w.isReleasedWhenClosed = false
        w.center()
        settingsWindow = w
        w.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    // MARK: - First-run window

    func showFirstRun() {
        if let w = firstRunWindow {
            w.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: true)
            return
        }
        let view = FirstRunView { [weak self] in
            self?.firstRunWindow?.close()
            self?.firstRunWindow = nil
        }
        .environmentObject(prefs)
        let host = NSHostingController(rootView: view)
        let w = NSWindow(contentViewController: host)
        w.title = "欢迎使用鲸伴 (Welcome to DeepSeek Harness)"
        w.setContentSize(NSSize(width: 560, height: 420))
        w.styleMask = [.titled, .closable]
        w.isReleasedWhenClosed = false
        w.center()
        firstRunWindow = w
        w.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    // MARK: - Hotkeys (local-event monitor while popover is open)

    private func installEscMonitor() {
        guard monitor == nil else { return }
        monitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] event in
            guard let self = self else { return event }
            if event.keyCode == 53 { // ESC
                self.popover.performClose(nil)
                self.removeEscMonitor()
                return nil
            }
            // ⌘N / ⌘K while popover focused
            if event.modifierFlags.contains(.command) {
                if event.charactersIgnoringModifiers == "n" {
                    self.conversationStore.newConversation(); return nil
                }
                if event.charactersIgnoringModifiers == "k" {
                    self.chatVM.clear(); return nil
                }
            }
            return event
        }
    }

    private func removeEscMonitor() {
        if let m = monitor { NSEvent.removeMonitor(m); monitor = nil }
    }

    private func registerHotkeys() {
        // Per-popover monitor is installed on open; nothing global tonight.
    }
}

// Lightweight env passed into SwiftUI for delegate callbacks.
final class AppEnv: ObservableObject {
    let openSettings: () -> Void
    let openWorkbench: () -> Void
    let openFirstRun: () -> Void
    let quit: () -> Void
    init(openSettings: @escaping () -> Void,
         openWorkbench: @escaping () -> Void,
         openFirstRun: @escaping () -> Void,
         quit: @escaping () -> Void) {
        self.openSettings = openSettings
        self.openWorkbench = openWorkbench
        self.openFirstRun = openFirstRun
        self.quit = quit
    }
}
