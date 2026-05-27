import Foundation

/// A tiny Server-Sent-Events client built over `URLSession.bytes(for:)`.
///
/// Yields `(event, data)` pairs where `event` defaults to `"message"` per the
/// SSE spec when no `event:` line was present in the frame.
///
/// IMPORTANT: we do NOT use `bytes.lines`. As of macOS 13's `AsyncLineSequence`
/// implementation, empty lines are *not* yielded — but SSE relies on the blank
/// line (`\n\n`) to terminate each frame. We do our own line splitting against
/// the raw byte stream so empty lines survive.
struct SSEFrame: Sendable {
    let event: String
    let data: Data
}

enum SSEClientError: Error, LocalizedError {
    case badStatus(Int)
    case notSSE(String?)

    var errorDescription: String? {
        switch self {
        case .badStatus(let code): return "HTTP \(code) from server"
        case .notSSE(let ct):      return "Expected text/event-stream, got \(ct ?? "nothing")"
        }
    }
}

struct SSEClient {

    let session: URLSession

    init(session: URLSession = .shared) {
        self.session = session
    }

    func stream(_ request: URLRequest) -> AsyncThrowingStream<SSEFrame, Error> {
        AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    var req = request
                    req.setValue("text/event-stream", forHTTPHeaderField: "Accept")
                    req.setValue("no-cache",         forHTTPHeaderField: "Cache-Control")

                    let (bytes, response) = try await session.bytes(for: req)
                    guard let http = response as? HTTPURLResponse else {
                        throw SSEClientError.badStatus(-1)
                    }
                    guard (200..<300).contains(http.statusCode) else {
                        throw SSEClientError.badStatus(http.statusCode)
                    }
                    let ct = http.value(forHTTPHeaderField: "Content-Type") ?? ""
                    guard ct.lowercased().contains("text/event-stream") else {
                        throw SSEClientError.notSSE(ct)
                    }

                    let debug = ProcessInfo.processInfo.environment["DSH_SSE_DEBUG"] == "1"

                    var eventName = "message"
                    var dataBuf = Data()
                    var lineBuf = Data()
                    lineBuf.reserveCapacity(4096)

                    func dispatchFrame() {
                        // SSE: empty data + default event name → ignore.
                        if dataBuf.isEmpty && eventName == "message" { return }
                        continuation.yield(SSEFrame(event: eventName, data: dataBuf))
                        eventName = "message"
                        dataBuf = Data()
                    }

                    func handleLine(_ raw: Data) {
                        // Strip optional trailing \r (handles CRLF).
                        var line = raw
                        if line.last == 0x0D { line.removeLast() }

                        if debug {
                            let s = String(data: line, encoding: .utf8) ?? "<binary>"
                            FileHandle.standardError.write(Data("SSE< \(s.debugDescription)\n".utf8))
                        }

                        // Blank line → dispatch.
                        if line.isEmpty {
                            dispatchFrame()
                            return
                        }
                        // Comment line.
                        if line.first == 0x3A { return }   // ':'

                        guard let s = String(data: line, encoding: .utf8) else { return }
                        let (field, value) = Self.splitField(s)
                        switch field {
                        case "event":
                            eventName = value
                        case "data":
                            if !dataBuf.isEmpty { dataBuf.append(0x0A) }
                            dataBuf.append(Data(value.utf8))
                        default:
                            break
                        }
                    }

                    for try await byte in bytes {
                        if Task.isCancelled { break }
                        if byte == 0x0A {  // '\n'
                            handleLine(lineBuf)
                            lineBuf.removeAll(keepingCapacity: true)
                        } else {
                            lineBuf.append(byte)
                        }
                    }
                    // Flush any trailing partial line + last frame.
                    if !lineBuf.isEmpty {
                        handleLine(lineBuf)
                    }
                    dispatchFrame()
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: error)
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }

    private static func splitField(_ line: String) -> (String, String) {
        guard let idx = line.firstIndex(of: ":") else { return (line, "") }
        let field = String(line[..<idx])
        var value = String(line[line.index(after: idx)...])
        if value.hasPrefix(" ") { value.removeFirst() }
        return (field, value)
    }
}
