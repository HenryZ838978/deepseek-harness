import Foundation

/// Background actor that maintains an in-memory list of the user's recently
/// modified files, drawn from a curated set of "human" directories
/// (Documents / Desktop / Downloads / WeChat / Lark / WPS / DingTalk).
///
/// The agent uses this list to talk about files by name (《项目周报.docx》)
/// without ever asking the user "what's the path?".
///
/// Hard limits to stay honest:
/// - Only files modified within the last `lookbackDays` days (default 30)
/// - Cap at `maxEntries` (default 200) after sorting newest-first
/// - Skip hidden files, files > `maxFileSizeBytes` (default 500 MB)
/// - Per-directory walk capped at `perDirCap` files (default 5000) so a 200k-file
///   Downloads folder can't stall the scan
/// - Recursion depth capped at `maxDepth` (default 6)
/// - Silently swallow TCC denials — the agent simply won't see what we can't read
actor FileIndex {

    private(set) var snapshot: [RecentFile] = []
    private(set) var lastRefresh: Date?

    private let lookbackDays: Int = 30
    private let maxEntries: Int = 200
    private let maxFileSizeBytes: Int = 500 * 1024 * 1024
    private let perDirCap: Int = 5000
    private let maxDepth: Int = 6

    func currentSnapshot() -> [RecentFile] { snapshot }

    /// Kick a refresh in the background. Coalesces concurrent calls — if a
    /// scan is already in flight we return its result instead of starting
    /// another. Returns the new snapshot.
    @discardableResult
    func refresh() async -> [RecentFile] {
        let new = await Self.walkAll(
            lookbackDays: lookbackDays,
            maxEntries: maxEntries,
            maxFileSizeBytes: maxFileSizeBytes,
            perDirCap: perDirCap,
            maxDepth: maxDepth
        )
        snapshot = new
        lastRefresh = Date()
        return new
    }

    // MARK: - Walker (static so it's trivially Sendable)

    private struct ScanRoot {
        let url: URL
        let app: String       // friendly label for the buddy prompt
    }

    private static func candidateRoots() -> [ScanRoot] {
        let home = FileManager.default.homeDirectoryForCurrentUser
        let lib  = home.appendingPathComponent("Library/Containers")

        return [
            ScanRoot(url: home.appendingPathComponent("Documents"),  app: "文稿"),
            ScanRoot(url: home.appendingPathComponent("Desktop"),    app: "桌面"),
            ScanRoot(url: home.appendingPathComponent("Downloads"),  app: "下载"),

            // WeChat (sandboxed; the user-data lives a few levels deep but the
            // enumerator handles recursion).
            ScanRoot(url: lib.appendingPathComponent("com.tencent.xinWeChat/Data"),
                     app: "微信"),
            // Feishu / Lark
            ScanRoot(url: lib.appendingPathComponent("com.electron.lark/Data"),
                     app: "飞书"),
            // WPS
            ScanRoot(url: lib.appendingPathComponent("com.kingsoft.wpsoffice.mac/Data"),
                     app: "WPS"),
            // DingTalk
            ScanRoot(url: lib.appendingPathComponent("com.alibaba.DingTalkMac/Data"),
                     app: "钉钉"),

            // Common user-visible mirrors (non-sandboxed apps)
            ScanRoot(url: home.appendingPathComponent("Documents/WeChat Files"),
                     app: "微信"),
            ScanRoot(url: home.appendingPathComponent("Documents/Lark"),
                     app: "飞书"),
            ScanRoot(url: home.appendingPathComponent("Documents/WPS Cloud Files"),
                     app: "WPS"),
        ]
    }

    /// Friendly file-extension whitelist. Anything not in here is dropped —
    /// the buddy prompt shouldn't be reciting `.plist` or `.DS_Store` files.
    private static let keepExtensions: Set<String> = [
        "doc", "docx", "xls", "xlsx", "ppt", "pptx",
        "pdf", "txt", "md", "rtf", "pages", "numbers", "key",
        "csv", "tsv", "json",
        "png", "jpg", "jpeg", "heic", "gif", "webp", "bmp", "tiff",
        "mp3", "wav", "m4a", "aac", "flac",
        "mp4", "mov", "m4v", "mkv", "webm",
        "zip", "rar", "7z", "tar", "gz",
        "psd", "ai", "fig", "sketch",
        "et", "wps", "dps"                  // WPS / Kingsoft formats
    ]

    private static func walkAll(lookbackDays: Int,
                                maxEntries: Int,
                                maxFileSizeBytes: Int,
                                perDirCap: Int,
                                maxDepth: Int) async -> [RecentFile] {
        await withCheckedContinuation { cont in
            DispatchQueue.global(qos: .utility).async {
                let cutoff = Date().addingTimeInterval(-Double(lookbackDays) * 86400)
                var collected: [RecentFile] = []
                let dateFmt = ISO8601DateFormatter()
                dateFmt.formatOptions = [.withFullDate]

                for root in candidateRoots() {
                    guard FileManager.default.fileExists(atPath: root.url.path) else { continue }
                    let resKeys: Set<URLResourceKey> = [
                        .isRegularFileKey,
                        .isHiddenKey,
                        .fileSizeKey,
                        .contentModificationDateKey
                    ]
                    let opts: FileManager.DirectoryEnumerationOptions = [
                        .skipsHiddenFiles,
                        .skipsPackageDescendants
                    ]
                    guard let it = FileManager.default.enumerator(
                        at: root.url,
                        includingPropertiesForKeys: Array(resKeys),
                        options: opts,
                        errorHandler: { _, _ in true }  // skip unreadable, keep going
                    ) else { continue }

                    var perRoot = 0
                    let rootPath = root.url.path
                    while let next = it.nextObject() as? URL {
                        // Depth guard
                        let relDepth = next.path
                            .replacingOccurrences(of: rootPath, with: "")
                            .split(separator: "/").count
                        if relDepth > maxDepth { it.skipDescendants(); continue }

                        guard let v = try? next.resourceValues(forKeys: resKeys) else { continue }
                        if v.isRegularFile != true { continue }
                        if v.isHidden == true { continue }
                        if let sz = v.fileSize, sz > maxFileSizeBytes { continue }
                        guard let mtime = v.contentModificationDate, mtime > cutoff else { continue }

                        let ext = next.pathExtension.lowercased()
                        guard !ext.isEmpty, keepExtensions.contains(ext) else { continue }

                        collected.append(RecentFile(
                            name: next.lastPathComponent,
                            app: root.app,
                            modified: dateFmt.string(from: mtime),
                            full_path: next.path
                        ))

                        perRoot += 1
                        if perRoot >= perDirCap { break }
                    }
                }

                // Newest first, dedupe by path, cap.
                var seen = Set<String>()
                let sorted = collected
                    .sorted { $0.modified > $1.modified }
                    .filter { seen.insert($0.full_path).inserted }
                    .prefix(maxEntries)

                cont.resume(returning: Array(sorted))
            }
        }
    }
}
