import CoreGraphics
import Foundation
import Testing
@testable import Lowi

struct DriveMappingTests {
    @Test func upIsForwardScreenLeftIsRobotLeftAndTurnLeftIsPositive() {
        let up = DriveMapping.input(stick: CGVector(dx: 0, dy: -1), turn: nil)
        #expect(up.x == 1 && up.y == 0 && up.turn == 0)
        let back = DriveMapping.input(stick: CGVector(dx: 0, dy: 1), turn: nil)
        #expect(back.x == -1)
        let left = DriveMapping.input(stick: CGVector(dx: -1, dy: 0), turn: nil)
        #expect(left.y == 1 && left.x == 0)
        #expect(DriveMapping.input(stick: nil, turn: -1).turn == 1)
        #expect(DriveMapping.input(stick: nil, turn: 1).turn == -1)
    }

    @Test func deadZoneCentresAndNothingGoesPastFull() {
        #expect(DriveMapping.input(stick: CGVector(dx: 0.05, dy: -0.1), turn: 0.1).isZero)
        let far = DriveMapping.input(stick: CGVector(dx: 3, dy: -4), turn: 7)
        #expect(hypot(far.x, far.y) <= 1 + 1e-9)
        #expect(abs(far.turn) <= 1)
        let diagonal = DriveMapping.input(stick: CGVector(dx: 0.7071, dy: -0.7071), turn: nil)
        #expect(hypot(diagonal.x, diagonal.y) <= 1 + 1e-9)
        #expect(diagonal.x > 0 && diagonal.y < 0)  // forward and to the right
    }

    @Test func curveRisesSmoothlyFromTheDeadZone() {
        let values = stride(from: 0.0, through: 1.0, by: 0.05).map(DriveMapping.shape)
        #expect(values.first == 0 && values.last == 1)
        #expect(zip(values, values.dropFirst()).allSatisfy { $0 <= $1 })
        #expect(DriveMapping.shape(0.5) < 0.5)  // gentler than linear near the centre
    }

    @Test func keysAndPadsGiveFullSpeedOnEachAxis() {
        #expect(DriveMapping.input(forward: 1, left: 0, turnLeft: 0) == DriveInput(x: 1))
        #expect(DriveMapping.input(forward: 0, left: 0, turnLeft: -1) == DriveInput(turn: -1))
        let diagonal = DriveMapping.input(forward: 1, left: 1, turnLeft: 0)
        #expect(abs(hypot(diagonal.x, diagonal.y) - 1) < 1e-9)
    }
}

struct DeadManTests {
    private let forward = DriveInput(x: 1)

    private func drives(_ commands: [DriveCommand]) -> [String] {
        commands.compactMap { if case .drive(_, let id) = $0 { id } else { nil } }
    }

    @Test func renewsAbout0_4sApartWhileHeldAndStopsOnceOnRelease() {
        var deadMan = DeadMan()
        var times: [Double] = []
        for i in 0...30 {  // 3 s at 10 Hz
            let now = Double(i) / 10
            if !drives(deadMan.update(held: true, input: forward, block: nil, now: now)).isEmpty {
                times.append(now)
            }
        }
        let gaps = zip(times, times.dropFirst()).map { $1 - $0 }
        #expect(times.first == 0 && times.count >= 7)
        #expect(gaps.allSatisfy { $0 >= 0.4 - 1e-9 && $0 <= 0.5 + 1e-9 })
        #expect(deadMan.update(held: false, input: .zero, block: nil, now: 3.05) == [.stop])
        #expect(deadMan.update(held: false, input: .zero, block: nil, now: 3.15).isEmpty)
    }

    @Test func aBlockWhileHeldStopsAtOnceAndTheFingerMustLift() {
        var deadMan = DeadMan()
        let first = drives(deadMan.update(held: true, input: forward, block: nil, now: 0))
        #expect(first.count == 1)
        let stale = DriveBlock.frameStale(seconds: 2.1)
        #expect(deadMan.update(held: true, input: forward, block: stale, now: 0.1) == [.stop])
        for i in 2...10 {  // the frame is fresh again but the finger never lifted
            #expect(deadMan.update(held: true, input: forward, block: nil, now: Double(i) / 10).isEmpty)
        }
        #expect(deadMan.update(held: false, input: .zero, block: nil, now: 1.1).isEmpty)
        let again = drives(deadMan.update(held: true, input: forward, block: nil, now: 1.2))
        #expect(again.count == 1 && again != first)  // a new press, a new hold id
    }

    @Test func aPressThatStartsWhileBlockedNeverDrives() {
        var deadMan = DeadMan()
        for block in [DriveBlock.linkLost, .estop, .notStanding(mode: "sitting"), .background] {
            #expect(deadMan.update(held: true, input: forward, block: block, now: 0).isEmpty)
            #expect(deadMan.update(held: true, input: forward, block: nil, now: 0.5).isEmpty)
            #expect(deadMan.update(held: false, input: .zero, block: nil, now: 0.6).isEmpty)
        }
    }

    @Test func theBrainEndingTheHoldNeedsANewPressButOlderPressesAreIgnored() {
        var deadMan = DeadMan()
        let id = drives(deadMan.update(held: true, input: forward, block: nil, now: 0))[0]
        deadMan.ended(holdId: "some-older-press")
        #expect(deadMan.holdId == id)
        deadMan.ended(holdId: id)
        #expect(deadMan.holdId == nil)
        #expect(deadMan.update(held: true, input: forward, block: nil, now: 0.5).isEmpty)
        _ = deadMan.update(held: false, input: .zero, block: nil, now: 0.6)
        #expect(drives(deadMan.update(held: true, input: forward, block: nil, now: 0.7)).count == 1)
    }

    @Test func stopPressedWhileHeldEndsThePress() {
        var deadMan = DeadMan()
        _ = deadMan.update(held: true, input: forward, block: nil, now: 0)
        deadMan.cancel()  // the caller sends Stop itself
        for i in 1...10 {
            #expect(deadMan.update(held: true, input: forward, block: nil, now: Double(i) / 10).isEmpty)
        }
    }

    @Test func changesGoOutAtOnceButNeverMoreThan10ASecond() {
        var deadMan = DeadMan()
        _ = deadMan.update(held: true, input: forward, block: nil, now: 0)
        let turn = DriveInput(x: 1, turn: 1)
        #expect(deadMan.update(held: true, input: turn, block: nil, now: 0.05).isEmpty)
        #expect(drives(deadMan.update(held: true, input: turn, block: nil, now: 0.1)).count == 1)
        let small = DriveInput(x: 0.98, turn: 1)  // below the change threshold: waits for renewal
        #expect(deadMan.update(held: true, input: small, block: nil, now: 0.25).isEmpty)
        #expect(drives(deadMan.update(held: true, input: .zero, block: nil, now: 0.3)).count == 1)
    }
}
