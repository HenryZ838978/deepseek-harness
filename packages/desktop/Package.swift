// swift-tools-version:6.0
//
// DeepSeek Harness (深求) — SwiftUI macOS menubar client.
//
// Build with Command Line Tools only:
//     swift build -c release
//     swift run               # launches menubar app from terminal
//     ./Scripts/make-app.sh   # bundles as a real .app you can double-click
//
// Open in full Xcode (tomorrow) by File → Open this Package.swift directly.
// No .xcodeproj needed; Xcode opens SPM packages natively.

import PackageDescription

let package = Package(
    name: "DeepSeekHarness",
    platforms: [
        .macOS(.v13)
    ],
    products: [
        .executable(name: "DeepSeekHarness", targets: ["DeepSeekHarness"])
    ],
    targets: [
        .executableTarget(
            name: "DeepSeekHarness",
            path: "Sources/DeepSeekHarness",
            // Resources/ lives at the package root and is copied into the .app
            // bundle by Scripts/make-app.sh. SPM dev builds (`swift run`) do not
            // bundle Resources — EmbeddedServer falls back to the system `node`.
            resources: [],
            // Pin to Swift 5 language mode: AppKit/NSApplicationDelegate +
            // SwiftUI menubar code is not ergonomic under Swift 6 strict
            // concurrency yet (NSApp top-level bootstrap, MainActor inference).
            swiftSettings: [
                .swiftLanguageMode(.v5)
            ]
        )
    ]
)
