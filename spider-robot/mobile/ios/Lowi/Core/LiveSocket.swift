import Foundation

/// The one WebSocket to the brain: auth first, a heartbeat every second, reconnect with backoff.
///
/// A socket that has said nothing for 3 s is treated as dead (the brain sends state at least
/// once a second), so a half-open connection is noticed even when the OS has not.
@MainActor
final class LiveSocket {
    enum Status: Equatable, Sendable {
        case idle
        case connecting
        case live
        case reconnecting(attempt: Int, retryIn: Double)
        case unauthorized
    }

    static let heartbeatInterval: TimeInterval = 1.0
    static let silenceLimit: TimeInterval = 3.0
    static let maxBackoff: TimeInterval = 10.0

    var onStatus: @MainActor (Status) -> Void = { _ in }
    var onMessage: @MainActor (ServerMessage) -> Void = { _ in }
    var onPong: @MainActor (TimeInterval) -> Void = { _ in }  // round trip, seconds

    private(set) var status: Status = .idle {
        didSet { if status != oldValue { onStatus(status) } }
    }

    private let session: URLSession
    private let clock: @Sendable () -> TimeInterval
    private var loop: Task<Void, Never>?
    private var socket: URLSessionWebSocketTask?
    private var lastReceived: TimeInterval = 0

    init(session: URLSession = .shared,
         clock: @escaping @Sendable () -> TimeInterval = { ProcessInfo.processInfo.systemUptime }) {
        self.session = session
        self.clock = clock
    }

    var isLive: Bool { status == .live }

    func start(url: URL, token: String) {
        stop()
        loop = Task { [weak self] in await self?.run(url: url, token: token) }
    }

    func stop() {
        loop?.cancel()
        loop = nil
        socket?.cancel(with: .goingAway, reason: nil)
        socket = nil
        status = .idle
    }

    /// Queues a message on the live socket. False when there is none, so the caller can fall back.
    @discardableResult
    func send(_ message: ClientMessage) -> Bool {
        guard status == .live, let socket else { return false }
        socket.send(.string(message.json)) { _ in }
        return true
    }

    private func run(url: URL, token: String) async {
        var attempt = 0
        while !Task.isCancelled {
            if attempt == 0 { status = .connecting }
            let task = session.webSocketTask(with: url)
            socket = task
            task.resume()
            let (closeCode, wasLive) = await serve(task, token: token)
            task.cancel(with: .goingAway, reason: nil)
            if socket === task { socket = nil }
            if Task.isCancelled { return }
            if closeCode == 4401 {
                status = .unauthorized
                return
            }
            attempt = wasLive ? 1 : attempt + 1
            let backoff = min(Self.maxBackoff, 0.5 * pow(2, Double(attempt - 1)))
                * Double.random(in: 0.8...1.2)
            status = .reconnecting(attempt: attempt, retryIn: backoff)
            try? await Task.sleep(for: .seconds(backoff))
        }
    }

    /// Runs one connection until it ends: the brain's close code, if any, and whether it got live.
    private func serve(_ task: URLSessionWebSocketTask, token: String) async -> (Int?, Bool) {
        lastReceived = clock()
        var wasLive = false
        let watchdog = Task { [weak self] in
            var lastBeat = -TimeInterval.infinity
            while !Task.isCancelled {
                try? await Task.sleep(for: .milliseconds(200))
                guard let self else { return }
                let now = self.clock()
                if now - self.lastReceived > Self.silenceLimit {
                    task.cancel(with: .goingAway, reason: nil)
                    return
                }
                if self.status == .live, now - lastBeat >= Self.heartbeatInterval {
                    lastBeat = now
                    task.send(.string(ClientMessage.heartbeat(now).json)) { _ in }
                }
            }
        }
        defer { watchdog.cancel() }
        do {
            try await task.send(.string(ClientMessage.auth(token: token).json))
            while !Task.isCancelled {
                let raw = try await task.receive()
                lastReceived = clock()
                let message: ServerMessage
                do {
                    switch raw {
                    case .string(let text): message = try ServerMessage.decode(text: text)
                    case .data(let data): message = try ServerMessage.decode(binary: data)
                    @unknown default: continue
                    }
                } catch {
                    continue  // one bad message is not a reason to drop the link
                }
                if case .hello = message {
                    wasLive = true
                    status = .live
                }
                if case .pong(let sent?) = message { onPong(clock() - sent) }
                onMessage(message)
            }
        } catch {
            let code = task.closeCode.rawValue
            return (code == 0 ? nil : code, wasLive)
        }
        return (nil, wasLive)
    }
}
