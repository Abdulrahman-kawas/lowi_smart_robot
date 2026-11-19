import Foundation

/// Where the brain is. A MagicDNS name means HTTPS through `tailscale serve` on port 443;
/// 127.0.0.1 or localhost means the simulator stack on this Mac, plain HTTP on port 8765.
struct BrainAddress: Equatable, Sendable {
    static let simulatorPort = 8765

    let base: URL

    var isLoopback: Bool {
        ["127.0.0.1", "localhost", "::1"].contains(base.host() ?? "")
    }

    var liveURL: URL {
        var parts = URLComponents(url: base, resolvingAgainstBaseURL: false)!
        parts.scheme = base.scheme == "https" ? "wss" : "ws"
        parts.path = "/v1/live"
        return parts.url!
    }

    init?(_ text: String) {
        var text = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty, !text.contains(" ") else { return nil }
        if !text.contains("://") {
            let host = (text.split(separator: ":").first.map(String.init) ?? text).lowercased()
            if ["127.0.0.1", "localhost"].contains(host) {
                text = "http://" + text + (text.contains(":") ? "" : ":\(Self.simulatorPort)")
            } else {
                text = "https://" + text
            }
        }
        guard var parts = URLComponents(string: text),
              let scheme = parts.scheme?.lowercased(), ["http", "https"].contains(scheme),
              let host = parts.host, !host.isEmpty else { return nil }
        parts.path = ""
        parts.query = nil
        parts.fragment = nil
        guard let url = parts.url else { return nil }
        base = url
    }

    func url(_ path: String) -> URL { base.appending(path: path) }
}

struct Challenge: Decodable, Sendable, Equatable {
    var challengeId: String
    var action: String
    var ttlS: Double
    var frameJpeg: String
    var frameAgeMs: Double

    var jpeg: Data? { Data(base64Encoded: frameJpeg) }
}

struct ConfirmResult: Decodable, Sendable, Equatable {
    var result: String  // released, posture_sent, cancelled, refused
    var detail: String
}

struct PairResult: Decodable, Sendable {
    var token: String
    var deviceName: String
    var robotId: String
    var caps: Caps
}

struct PhotoResult: Decodable, Sendable {
    var frameJpeg: String
    var answer: String?
    var visionError: String?
}

struct ServiceInfo: Decodable, Sendable {
    var service: String
    var api: Int
}

enum APIError: Error, Equatable, LocalizedError {
    case unauthorized(String)
    case refused(status: Int, detail: String)
    case unreachable(String)
    case badResponse

    var errorDescription: String? {
        switch self {
        case .unauthorized(let detail), .unreachable(let detail): detail
        case .refused(let status, let detail):
            detail.isEmpty ? String(localized: "The brain refused it (HTTP \(status)).") : detail
        case .badResponse: String(localized: "The brain sent an answer the app does not understand.")
        }
    }
}

/// HTTP calls to the brain. Each call has a short timeout: a stuck call must never hold up STOP.
struct APIClient: Sendable {
    let address: BrainAddress
    var token: String?
    var session: URLSession = .shared

    func hello() async throws -> ServiceInfo { try await call("GET", "/v1/hello", timeout: 5) }

    func pair(code: String, deviceName: String) async throws -> PairResult {
        try await call("POST", "/v1/pair", body: ["code": code, "device_name": deviceName])
    }

    func state() async throws -> BrainState { try await call("GET", "/v1/state", timeout: 5) }

    func stop() async throws {
        let _: [String: Bool] = try await call("POST", "/v1/stop", timeout: 3)
    }

    func estop() async throws {
        let _: [String: Bool] = try await call("POST", "/v1/estop", timeout: 3)
    }

    func releaseEstop() async throws -> Challenge {
        try await call("POST", "/v1/estop/release", timeout: 15)
    }

    func wake(posture: String) async throws -> Challenge {
        try await call("POST", "/v1/wake", body: ["posture": posture], timeout: 15)
    }

    func confirm(challengeId: String, approved: Bool) async throws -> ConfirmResult {
        try await call("POST", "/v1/confirm",
                       body: ["challenge_id": challengeId, "approved": approved], timeout: 10)
    }

    func photo(question: String?) async throws -> PhotoResult {
        let body: [String: Any] = question.map { ["question": $0] } ?? [:]
        return try await call("POST", "/v1/photo", body: body, timeout: 120)
    }

    private struct Detail: Decodable { var detail: String? }

    private func call<T: Decodable>(_ method: String, _ path: String, body: [String: Any]? = nil,
                                    timeout: TimeInterval = 10) async throws -> T {
        var request = URLRequest(url: address.url(path), timeoutInterval: timeout)
        request.httpMethod = method
        if let token { request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        if let body {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
        }
        let data: Data, response: URLResponse
        do {
            (data, response) = try await session.data(for: request)
        } catch {
            throw APIError.unreachable(error.localizedDescription)
        }
        guard let http = response as? HTTPURLResponse else { throw APIError.badResponse }
        let decoder = ServerMessage.decoder
        guard (200..<300).contains(http.statusCode) else {
            let detail = (try? decoder.decode(Detail.self, from: data))?.detail
                ?? HTTPURLResponse.localizedString(forStatusCode: http.statusCode)
            if http.statusCode == 401 { throw APIError.unauthorized(detail) }
            throw APIError.refused(status: http.statusCode, detail: detail)
        }
        do {
            return try decoder.decode(T.self, from: data)
        } catch {
            throw APIError.badResponse
        }
    }
}
