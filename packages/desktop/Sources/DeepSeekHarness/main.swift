import AppKit
import Foundation

// Manual NSApplication bootstrap — we avoid @main / SwiftUI App because
// NSStatusItem-style menubar apps want full control of activation policy
// and we target macOS 13 (MenuBarExtra is 14+).
//
// `main` is run on the main thread, but Swift 6 SDK headers mark
// NSApplication / NSApplicationDelegate as @MainActor. We use
// `MainActor.assumeIsolated` to acknowledge that yes, this top-level code
// is in fact already on the main thread.

// --- Diagnostic mode -----------------------------------------------------
// Invocation:  swift run DeepSeekHarness --diag
// Runs BootScan + FileIndex once, builds the same buddy /v1/run request the
// popover would send, prints the request body + the full streamed reply,
// then exits. Useful when you can't inspect the SwiftUI popover state from
// the shell (CI, headless dev box, etc.).
if CommandLine.arguments.contains("--diag") {
    let sem = DispatchSemaphore(value: 0)
    Task {
        await Diagnostic.run()
        sem.signal()
    }
    sem.wait()
    exit(0)
}

MainActor.assumeIsolated {
    let app = NSApplication.shared
    let delegate = AppDelegate()
    app.delegate = delegate

    // .accessory == no Dock icon, no top menu bar. Pure status item.
    app.setActivationPolicy(.accessory)

    // Retain delegate for the lifetime of the process — NSApp keeps a weak ref.
    objc_setAssociatedObject(app, "dsh.delegate", delegate, .OBJC_ASSOCIATION_RETAIN)

    app.run()
}
