import Foundation

// Messages of the brain's /v1 API (spider-robot/mobile/README.md). Unknown fields are ignored,
// so the brain can add fields without breaking older apps.

struct Caps: Codable, Sendable, Equatable {
    var maxSpeedMps: Double
    var maxWzRps: Double
    var moveS: Double
    var moves: [String]

    enum CodingKeys: String, CodingKey {
        case maxSpeedMps
        case maxWzRps
        case moveS
        case moves
    }

    init(maxSpeedMps: Double, maxWzRps: Double, moveS: Double, moves: [String] = []) {
        self.maxSpeedMps = maxSpeedMps
        self.maxWzRps = maxWzRps
        self.moveS = moveS
        self.moves = moves
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        maxSpeedMps = try container.decode(Double.self, forKey: .maxSpeedMps)
        maxWzRps = try container.decode(Double.self, forKey: .maxWzRps)
        moveS = try container.decode(Double.self, forKey: .moveS)
        moves = try container.decodeIfPresent([String].self, forKey: .moves) ?? []
    }
}

struct RobotStatus: Decodable, Sendable, Equatable {
    var mode: String
    var estop: Bool
    var vx: Double
    var vy: Double
    var wz: Double
    var limiter: String?
    var linkOk: Bool?
    var rollDeg: Double?
    var pitchDeg: Double?
    var cameraPanDeg: Double?
    var perform: String?

    /// The body accepts moves only while standing or already walking.
    var canWalk: Bool { mode == "standing" || mode == "walking" }
}

struct MovesState: Decodable, Sendable, Equatable {
    var voice: Bool
    var remote: Bool

    private enum CodingKeys: String, CodingKey {
        case voice
        case remote
    }

    init(voice: Bool = true, remote: Bool = false) {
        self.voice = voice
        self.remote = remote
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        voice = try container.decodeIfPresent(Bool.self, forKey: .voice) ?? true
        remote = try container.decodeIfPresent(Bool.self, forKey: .remote) ?? false
    }
}

struct GatewayView: Decodable, Sendable, Equatable {
    var online: Bool
    var owner: String?
    var estop: Bool?
    var remoteAlive: Bool
    var moves: MovesState? = nil
}

struct DriveView: Decodable, Sendable, Equatable {
    var holder: String?
}

struct LatencyView: Decodable, Sendable, Equatable {
    var robotCmdRttMs: Double?
    var frameRttMs: Double?
}

struct BrainState: Decodable, Sendable, Equatable {
    var robot: RobotStatus?
    var robotAgeMs: Double?
    var online: Bool
    var gateway: GatewayView
    var drive: DriveView
    var latency: LatencyView
    var frameAgeMs: Double?
    var caps: Caps
}

struct LidarScan: Decodable, Sendable, Equatable {
    var sectorDeg: Double
    var sectorsM: [Double]
    var nearestM: Double
    var nearestBearingDeg: Double
    var ageMs: Double?
}

struct BrainEvent: Decodable, Sendable, Equatable {
    var kind: String
    var detail: String
    var level: String
    var refusal: Bool
    var holdId: String?
}

struct Hello: Decodable, Sendable, Equatable {
    var api: Int
    var device: String
    var robotId: String
    var caps: Caps
}

struct FrameHeader: Decodable, Sendable, Equatable {
    var n: Int
    var ageMs: Double
}

enum ProtocolError: Error, Equatable {
    case malformed(String)
}

enum ServerMessage: Sendable, Equatable {
    case hello(Hello)
    case state(BrainState)
    case lidar(LidarScan)
    case event(BrainEvent)
    case pong(Double?)
    case frame(FrameHeader, Data)
    case unknown(String)

    static var decoder: JSONDecoder {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return decoder
    }

    private struct Envelope: Decodable { var type: String }
    private struct Pong: Decodable { var t: Double? }

    static func decode(text: String) throws -> ServerMessage {
        let data = Data(text.utf8)
        let type = try decoder.decode(Envelope.self, from: data).type
        switch type {
        case "hello": return .hello(try decoder.decode(Hello.self, from: data))
        case "state": return .state(try decoder.decode(BrainState.self, from: data))
        case "lidar": return .lidar(try decoder.decode(LidarScan.self, from: data))
        case "event": return .event(try decoder.decode(BrainEvent.self, from: data))
        case "pong": return .pong(try decoder.decode(Pong.self, from: data).t)
        default: return .unknown(type)
        }
    }

    /// One binary message: [u32 big-endian header length][header JSON][JPEG].
    static func decode(binary data: Data) throws -> ServerMessage {
        let bytes = [UInt8](data)
        guard bytes.count >= 4 else { throw ProtocolError.malformed("frame shorter than 4 bytes") }
        let length = bytes[0..<4].reduce(0) { Int($0) << 8 | Int($1) }
        guard length > 0, bytes.count >= 4 + length else {
            throw ProtocolError.malformed("frame header length \(length) of \(bytes.count) bytes")
        }
        let header = try decoder.decode(FrameHeader.self, from: Data(bytes[4..<(4 + length)]))
        return .frame(header, Data(bytes[(4 + length)...]))
    }
}

/// What the app sends on /v1/live.
enum ClientMessage: Sendable, Equatable {
    case auth(token: String)
    case drive(DriveInput, holdId: String)
    case stop
    case estop
    case look(panDeg: Double, speed: Double)
    case perform(name: String, speed: Double, leg: String?)
    case movesSwitch(voice: Bool?, remote: Bool?)
    case posture(String)
    case video(Bool)
    case heartbeat(Double)

    var json: String {
        var object: [String: Any]
        switch self {
        case .auth(let token): object = ["type": "auth", "token": token]
        case .drive(let input, let holdId):
            object = ["type": "drive", "x": input.x, "y": input.y, "turn": input.turn,
                      "hold_id": holdId]
        case .stop: object = ["type": "stop"]
        case .estop: object = ["type": "estop"]
        case .look(let pan, let speed): object = ["type": "look", "pan_deg": pan, "speed": speed]
        case .perform(let name, let speed, let leg):
            object = ["type": "perform", "name": name, "speed": speed]
            if let leg { object["leg"] = leg }
        case .movesSwitch(let voice, let remote):
            object = ["type": "moves_switch"]
            if let voice { object["voice"] = voice }
            if let remote { object["remote"] = remote }
        case .posture(let posture): object = ["type": "posture", "posture": posture]
        case .video(let on): object = ["type": "video", "on": on]
        case .heartbeat(let t): object = ["type": "heartbeat", "t": t]
        }
        let data = (try? JSONSerialization.data(withJSONObject: object, options: [.sortedKeys]))
            ?? Data("{}".utf8)
        return String(decoding: data, as: UTF8.self)
    }
}
