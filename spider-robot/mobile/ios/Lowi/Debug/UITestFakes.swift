#if DEBUG
import UIKit

/// Debug builds only: lets UI tests open every screen without a brain or a robot. Launched with
/// -uiTestFake, the app is paired with a fake token, shows a standing robot with a latched E-stop,
/// and HTTP calls to the fake address are answered here.
enum UITestFakes {
    static var isOn: Bool { ProcessInfo.processInfo.arguments.contains("-uiTestFake") }
    static let address = "127.0.0.1:9"  // the discard port: nothing real ever answers there

    @MainActor static var jpeg = Data()

    @MainActor
    static func install() {
        jpeg = UIGraphicsImageRenderer(size: CGSize(width: 640, height: 480)).jpegData(
            withCompressionQuality: 0.7) { context in
            UIColor(white: 0.24, alpha: 1).setFill()
            context.fill(CGRect(x: 0, y: 0, width: 640, height: 480))
            UIColor(red: 0.86, green: 0.47, blue: 0.16, alpha: 1).setFill()
            context.fill(CGRect(x: 200, y: 150, width: 240, height: 250))
            ("UI TEST" as NSString).draw(at: CGPoint(x: 20, y: 20), withAttributes: [
                .font: UIFont.boldSystemFont(ofSize: 28), .foregroundColor: UIColor.white,
            ])
        }
        FakeBrainProtocol.jpegBase64 = jpeg.base64EncodedString()
        URLProtocol.registerClass(FakeBrainProtocol.self)
    }

    static let state = BrainState(
        robot: RobotStatus(mode: "estop", estop: true, vx: 0, vy: 0, wz: 0,
                           limiter: "slowing: obstacle 0.40 m from the legs", linkOk: true,
                           rollDeg: 0.4, pitchDeg: -1.2, cameraPanDeg: 0),
        robotAgeMs: 40, online: true,
        gateway: GatewayView(online: true, owner: nil, estop: true, remoteAlive: true),
        drive: DriveView(holder: nil),
        latency: LatencyView(robotCmdRttMs: 4.5, frameRttMs: 6.0),
        frameAgeMs: 120, caps: Caps(maxSpeedMps: 0.05, maxWzRps: 0.3, moveS: 1.0))

    static let lidar: LidarScan = {
        var sectors = (0..<36).map { i in 1.4 + 0.5 * sin(Double(i) / 3) }
        sectors[2] = 0.42  // front-left
        sectors[3] = 0.55
        sectors[18] = 8.0  // nothing behind
        return LidarScan(sectorDeg: 10, sectorsM: sectors, nearestM: 0.42,
                         nearestBearingDeg: 20, ageMs: 100)
    }()

    static let events = [
        BrainEvent(kind: "limiter", detail: "slowing: obstacle 0.40 m from the legs",
                   level: "info", refusal: false),
        BrainEvent(kind: "estop", detail: "latched", level: "alert", refusal: false),
    ]
}

/// Answers the fake brain address like the real /v1 API would.
final class FakeBrainProtocol: URLProtocol {
    nonisolated(unsafe) static var jpegBase64 = ""

    override class func canInit(with request: URLRequest) -> Bool {
        request.url?.host() == "127.0.0.1" && request.url?.port == 9
    }

    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        let path = request.url?.path() ?? ""
        let challenge: (String) -> [String: Any] = { action in
            ["challenge_id": "fake-challenge", "action": action, "ttl_s": 30,
             "frame_jpeg": Self.jpegBase64, "frame_age_ms": 150]
        }
        var status = 200
        let body: [String: Any] = switch path {
        case "/v1/hello": ["service": "spider-brain", "api": 1]
        case "/v1/stop", "/v1/estop": ["sent": true]
        case "/v1/estop/release": challenge("estop_release")
        case "/v1/wake": challenge("wake_from_limp")
        case "/v1/confirm": ["result": "cancelled", "detail": ""]
        case "/v1/photo": ["frame_jpeg": Self.jpegBase64,
                           "answer": "An orange box, about a metre ahead.", "vision_error": NSNull()]
        case "/v1/talk": ["heard": "What is in front of you?",
                          "reply": "An orange box, about a metre ahead.", "action": "answer",
                          "provider": "fake", "elapsed_ms": 850]
        default: ["detail": "not faked"]
        }
        if body["detail"] as? String == "not faked" { status = 404 }
        let data = (try? JSONSerialization.data(withJSONObject: body)) ?? Data()
        let response = HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: "HTTP/1.1",
                                       headerFields: ["Content-Type": "application/json"])!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: data)
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}
}
#endif
