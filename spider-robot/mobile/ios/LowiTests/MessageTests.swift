import Foundation
import Testing
@testable import Lowi

struct MessageTests {
    @Test func stateFromTheBrainDecodes() throws {
        let text = """
         {"type":"state","robot":{"v":3,"robot_id":"spider-01","ts":1.0,"mode":"standing",
          "vx":0.05,"vy":0.0,"wz":-0.3,"move_remaining_s":0.4,"roll_deg":0.1,"pitch_deg":null,
          "camera_pan_deg":12.5,

         "lidar_age_s":0.1,"last_seq":7,"link_ok":true,"estop":false,
         "limiter":"slowing: obstacle 0.40 m from the legs","loop_overruns":0,"loop_max_ms":0.3,
         "rt_ok":false,"perform":null},
         "robot_age_ms":40,"online":true,
         "gateway":{"online":true,"owner":"remote","owner_remaining_s":0.8,"estop":false,
                    "remote_alive":true,"moves":{"voice":true,"remote":false},
                    "remote_limits":{"max_speed_mps":0.08,"max_wz_rps":0.4,
                                     "ceiling_speed_mps":0.12,"ceiling_wz_rps":0.6}},
         "drive":{"holder":"iPhone"},"latency":{"robot_cmd_rtt_ms":4.5,"frame_rtt_ms":null},
          "frame_age_ms":310,"caps":{"max_speed_mps":0.05,"max_wz_rps":0.3,"move_s":1.0,
          "moves":["wave","dance","hi"]}}

        """
        guard case .state(let state) = try ServerMessage.decode(text: text) else {
            Issue.record("not a state message")
            return
        }
        #expect(state.robot?.mode == "standing" && state.robot?.canWalk == true)
        #expect(state.robot?.cameraPanDeg == 12.5)
        #expect(state.robot?.limiter == "slowing: obstacle 0.40 m from the legs")
        #expect(state.gateway.owner == "remote" && state.drive.holder == "iPhone")
        #expect(state.gateway.moves == MovesState(voice: true, remote: false))
        #expect(state.gateway.remoteLimits == RemoteLimits(
            maxSpeedMps: 0.08, maxWzRps: 0.4, ceilingSpeedMps: 0.12, ceilingWzRps: 0.6))
        #expect(state.latency.robotCmdRttMs == 4.5 && state.latency.frameRttMs == nil)
        #expect(state.caps == Caps(maxSpeedMps: 0.05, maxWzRps: 0.3, moveS: 1.0,
                                   moves: ["wave", "dance", "hi"]))
    }

    @Test func olderStateWithoutMovesStillDecodes() throws {
        let text = """
        {"type":"state","online":true,"gateway":{"online":true,"remote_alive":true},
         "drive":{},"latency":{},
         "caps":{"max_speed_mps":0.05,"max_wz_rps":0.3,"move_s":1.0}}
        """
        guard case .state(let state) = try ServerMessage.decode(text: text) else {
            Issue.record("not a state message")
            return
        }
        #expect(state.gateway.moves == nil && state.gateway.remoteLimits == nil)
    }

    @Test func eventsCarryTheHoldTheyEnd() throws {
        let text = #"{"type":"event","kind":"drive_ended","detail":"dead-man","level":"warn","refusal":true,"hold_id":"ab-3"}"#
        #expect(try ServerMessage.decode(text: text) == .event(BrainEvent(
            kind: "drive_ended", detail: "dead-man", level: "warn", refusal: true, holdId: "ab-3")))
        #expect(try ServerMessage.decode(text: #"{"type":"pong","t":12.5}"#) == .pong(12.5))
        #expect(try ServerMessage.decode(text: #"{"type":"later"}"#) == .unknown("later"))
    }

    @Test func binaryFramesSplitIntoHeaderAndJPEG() throws {
        let header = Data(#"{"type":"frame","n":7,"age_ms":120.5}"#.utf8)
        let jpeg = Data([0xFF, 0xD8, 0xFF, 0xE0, 0x00])
        var message = Data([0, 0, 0, UInt8(header.count)])
        message.append(header)
        message.append(jpeg)
        #expect(try ServerMessage.decode(binary: message) == .frame(FrameHeader(n: 7, ageMs: 120.5), jpeg))
        #expect(throws: ProtocolError.self) { try ServerMessage.decode(binary: Data([0, 0, 1])) }
        #expect(throws: ProtocolError.self) {
            try ServerMessage.decode(binary: Data([0, 0, 0, 99]) + header)
        }
    }

    @Test func clientMessagesAreWhatTheBrainExpects() throws {
        let drive = ClientMessage.drive(DriveInput(x: 1, y: -0.5, turn: 0.25), holdId: "h-1").json
        let object = try #require(try JSONSerialization.jsonObject(with: Data(drive.utf8)) as? [String: Any])
        #expect(object["type"] as? String == "drive" && object["hold_id"] as? String == "h-1")
        #expect(object["x"] as? Double == 1 && object["y"] as? Double == -0.5)
        #expect(object["turn"] as? Double == 0.25)
        #expect(object["speed"] as? Double == 1 && object["turn_speed"] as? Double == 1)
        let slow = ClientMessage.drive(DriveInput(x: 1), holdId: "h-2", speed: 0.4, turnSpeed: 0.7).json
        let slowObject = try #require(try JSONSerialization.jsonObject(with: Data(slow.utf8)) as? [String: Any])
        #expect(slowObject["speed"] as? Double == 0.4 && slowObject["turn_speed"] as? Double == 0.7)
        let limit = ClientMessage.speedLimit(maxSpeedMps: 0.08, maxWzRps: 0.4).json
        let limitObject = try #require(try JSONSerialization.jsonObject(with: Data(limit.utf8)) as? [String: Any])
        #expect(limitObject["type"] as? String == "speed_limit")
        #expect(limitObject["max_speed_mps"] as? Double == 0.08)
        #expect(limitObject["max_wz_rps"] as? Double == 0.4)
        let look = ClientMessage.look(panDeg: -40, speed: 0.5).json
        let lookObject = try #require(try JSONSerialization.jsonObject(with: Data(look.utf8)) as? [String: Any])
        #expect(lookObject["type"] as? String == "look")
        #expect(lookObject["pan_deg"] as? Double == -40)
        #expect(lookObject["speed"] as? Double == 0.5)
        let perform = ClientMessage.perform(name: "wave", speed: 0.75, leg: "RF").json
        let performObject = try #require(try JSONSerialization.jsonObject(with: Data(perform.utf8)) as? [String: Any])
        #expect(performObject["type"] as? String == "perform")
        #expect(performObject["name"] as? String == "wave")
        #expect(performObject["speed"] as? Double == 0.75)
        #expect(performObject["leg"] as? String == "RF")
        let noLeg = ClientMessage.perform(name: "dance", speed: 0.5, leg: nil).json
        let noLegObject = try #require(try JSONSerialization.jsonObject(with: Data(noLeg.utf8)) as? [String: Any])
        #expect(noLegObject["leg"] == nil)
        let moves = ClientMessage.movesSwitch(voice: true, remote: false).json
        let movesObject = try #require(try JSONSerialization.jsonObject(with: Data(moves.utf8)) as? [String: Any])
        #expect(movesObject["type"] as? String == "moves_switch")
        #expect(movesObject["voice"] as? Bool == true)
        #expect(movesObject["remote"] as? Bool == false)
        let voiceOnly = ClientMessage.movesSwitch(voice: true, remote: nil).json
        let voiceOnlyObject = try #require(try JSONSerialization.jsonObject(with: Data(voiceOnly.utf8)) as? [String: Any])
        #expect(voiceOnlyObject["remote"] == nil)
        #expect(ClientMessage.stop.json == #"{"type":"stop"}"#)
        #expect(ClientMessage.auth(token: "t").json == #"{"token":"t","type":"auth"}"#)
    }

    @Test func addressesBecomeTheRightURLs() throws {
        let sim = try #require(BrainAddress("127.0.0.1"))
        #expect(sim.base.absoluteString == "http://127.0.0.1:8765" && sim.isLoopback)
        #expect(sim.liveURL.absoluteString == "ws://127.0.0.1:8765/v1/live")
        let server = try #require(BrainAddress(" home-server.tail1234.ts.net "))
        #expect(server.base.absoluteString == "https://home-server.tail1234.ts.net")
        #expect(server.liveURL.absoluteString == "wss://home-server.tail1234.ts.net/v1/live")
        #expect(!server.isLoopback)
        #expect(BrainAddress("localhost:9000")?.base.absoluteString == "http://localhost:9000")
        #expect(BrainAddress("") == nil && BrainAddress("two words") == nil)
        #expect(BrainAddress("ftp://x") == nil)
    }

    @Test func tailnetRangeIs100_64Slash10() {
        #expect(TailscaleCheck.isTailnet(0x6440_0001))  // 100.64.0.1
        #expect(TailscaleCheck.isTailnet(0x647F_FFFE))  // 100.127.255.254
        #expect(!TailscaleCheck.isTailnet(0x6480_0001))  // 100.128.0.1
        #expect(!TailscaleCheck.isTailnet(0xC0A8_0001))  // 192.168.0.1
    }
}
