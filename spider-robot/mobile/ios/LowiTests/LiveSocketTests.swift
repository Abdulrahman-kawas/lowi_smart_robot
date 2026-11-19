import Foundation
import Network
import Testing
@testable import Lowi

/// A WebSocket server on 127.0.0.1 that plays the brain, built on Network.framework.
@MainActor
final class FakeBrain {
    private let listener: NWListener
    private(set) var port: UInt16 = 0
    private(set) var texts: [String] = []
    private(set) var connections: [NWConnection] = []
    var onText: (String, NWConnection) -> Void = { _, _ in }

    init() throws {
        let parameters = NWParameters.tcp
        let websocket = NWProtocolWebSocket.Options()
        websocket.autoReplyPing = true
        parameters.defaultProtocolStack.applicationProtocols.insert(websocket, at: 0)
        parameters.requiredLocalEndpoint = .hostPort(host: "127.0.0.1", port: .any)
        listener = try NWListener(using: parameters)
        listener.newConnectionHandler = { [weak self] connection in
            MainActor.assumeIsolated { self?.accept(connection) }
        }
    }

    func start() async throws {
        listener.start(queue: .main)
        for _ in 0..<200 where listener.port == nil || listener.port?.rawValue == 0 {
            try await Task.sleep(for: .milliseconds(10))
        }
        port = try #require(listener.port?.rawValue)
    }

    var url: URL { URL(string: "ws://127.0.0.1:\(port)/v1/live")! }

    func shutdown() {
        connections.forEach { $0.cancel() }
        listener.cancel()
    }

    private func accept(_ connection: NWConnection) {
        connections.append(connection)
        connection.start(queue: .main)
        receive(on: connection)
    }

    private func receive(on connection: NWConnection) {
        connection.receiveMessage { [weak self] data, context, _, error in
            MainActor.assumeIsolated {
                guard let self, error == nil else { return }
                let metadata = context?.protocolMetadata(definition: NWProtocolWebSocket.definition)
                    as? NWProtocolWebSocket.Metadata
                if let data, metadata?.opcode == .text {
                    let text = String(decoding: data, as: UTF8.self)
                    self.texts.append(text)
                    self.onText(text, connection)
                }
                self.receive(on: connection)
            }
        }
    }

    func send(_ text: String, on connection: NWConnection) {
        send(Data(text.utf8), opcode: .text, on: connection)
    }

    func send(binary: Data, on connection: NWConnection) {
        send(binary, opcode: .binary, on: connection)
    }

    func close(_ connection: NWConnection, code: UInt16) {
        let metadata = NWProtocolWebSocket.Metadata(opcode: .close)
        metadata.closeCode = .privateCode(code)
        let context = NWConnection.ContentContext(identifier: "close", metadata: [metadata])
        connection.send(content: nil, contentContext: context, isComplete: true,
                        completion: .contentProcessed { _ in })
    }

    private func send(_ data: Data, opcode: NWProtocolWebSocket.Opcode, on connection: NWConnection) {
        let metadata = NWProtocolWebSocket.Metadata(opcode: opcode)
        let context = NWConnection.ContentContext(identifier: "message", metadata: [metadata])
        connection.send(content: data, contentContext: context, isComplete: true,
                        completion: .contentProcessed { _ in })
    }

    /// Answers auth like the brain: hello, then one state message.
    func greet() {
        onText = { [weak self] text, connection in
            guard let self, text.contains(#""type":"auth""#) else { return }
            self.send(#"{"type":"hello","api":1,"device":"test","robot_id":"spider-01","caps":{"max_speed_mps":0.05,"max_wz_rps":0.3,"move_s":1.0}}"#, on: connection)
        }
    }
}

@MainActor
private func until(_ seconds: Double, _ condition: () -> Bool) async -> Bool {
    let end = Date().addingTimeInterval(seconds)
    while Date() < end {
        if condition() { return true }
        try? await Task.sleep(for: .milliseconds(20))
    }
    return condition()
}

@MainActor
@Suite(.serialized)
struct LiveSocketTests {
    @Test func authGoesFirstThenTheLinkIsLiveAndHeartbeatsFlow() async throws {
        let brain = try FakeBrain()
        try await brain.start()
        defer { brain.shutdown() }
        brain.greet()
        let socket = LiveSocket()
        socket.start(url: brain.url, token: "secret")
        defer { socket.stop() }
        #expect(await until(3) { socket.status == .live })
        #expect(brain.texts.first == #"{"token":"secret","type":"auth"}"#)
        #expect(await until(3) { brain.texts.filter { $0.contains("heartbeat") }.count >= 2 })
        #expect(socket.send(.stop))
        #expect(await until(2) { brain.texts.contains(#"{"type":"stop"}"#) })
    }

    @Test func framesAndStateReachTheApp() async throws {
        let brain = try FakeBrain()
        try await brain.start()
        defer { brain.shutdown() }
        brain.greet()
        let socket = LiveSocket()
        var frames: [FrameHeader] = []
        socket.onMessage = { if case .frame(let header, _) = $0 { frames.append(header) } }
        socket.start(url: brain.url, token: "secret")
        defer { socket.stop() }
        #expect(await until(3) { socket.status == .live })
        let header = Data(#"{"type":"frame","n":3,"age_ms":40}"#.utf8)
        var message = Data([0, 0, 0, UInt8(header.count)])
        message.append(header)
        message.append(Data([0xFF, 0xD8, 0xFF, 0xD9]))
        brain.send(binary: message, on: try #require(brain.connections.last))
        #expect(await until(2) { frames == [FrameHeader(n: 3, ageMs: 40)] })
    }

    @Test func aRevokedTokenStopsReconnecting() async throws {
        let brain = try FakeBrain()
        try await brain.start()
        defer { brain.shutdown() }
        brain.onText = { [weak brain] _, connection in brain?.close(connection, code: 4401) }
        let socket = LiveSocket()
        socket.start(url: brain.url, token: "revoked")
        defer { socket.stop() }
        #expect(await until(3) { socket.status == .unauthorized })
        try await Task.sleep(for: .seconds(1.5))
        #expect(brain.connections.count == 1)  // no retry loop against a revoked token
    }

    @Test func aDroppedLinkReconnectsWithBackoff() async throws {
        let brain = try FakeBrain()
        try await brain.start()
        defer { brain.shutdown() }
        brain.greet()
        let socket = LiveSocket()
        var seen: [LiveSocket.Status] = []
        socket.onStatus = { seen.append($0) }
        socket.start(url: brain.url, token: "secret")
        defer { socket.stop() }
        #expect(await until(3) { socket.status == .live })
        brain.connections.last?.cancel()
        #expect(await until(3) { if case .reconnecting = socket.status { true } else { false } })
        #expect(await until(4) { socket.status == .live && brain.connections.count == 2 })
        #expect(seen.contains { if case .reconnecting(1, let wait) = $0 { wait <= 0.6 } else { false } })
    }

    @Test func aSilentBrainIsNoticedWithinAboutThreeSeconds() async throws {
        let brain = try FakeBrain()
        try await brain.start()
        defer { brain.shutdown() }
        brain.greet()  // hello, then nothing at all: no state, no pong
        let socket = LiveSocket()
        socket.start(url: brain.url, token: "secret")
        defer { socket.stop() }
        #expect(await until(3) { socket.status == .live })
        let start = Date()
        #expect(await until(5) { socket.status != .live })
        #expect(Date().timeIntervalSince(start) < LiveSocket.silenceLimit + 1)
    }
}
