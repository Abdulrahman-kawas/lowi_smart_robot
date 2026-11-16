import Foundation

/// Why driving is off right now. The drive controls are greyed out and show this.
enum DriveBlock: Equatable, Sendable {
    case notPaired
    case linkLost
    case background
    case covered  // a confirmation or a sheet is over the drive controls
    case robotOffline
    case noFrame
    case frameStale(seconds: Double)
    case estop
    case notStanding(mode: String)
    case otherDriver(name: String)
}

enum DriveCommand: Equatable, Sendable {
    case drive(DriveInput, holdId: String)
    case stop
}

/// The phone's half of dead-man driving. The brain enforces the same rules on its side.
///
/// Motion is asked for only while a finger, a key or a controller stick is held, as a 1 s move
/// renewed about every 0.4 s. Releasing, any block (link lost, app in the background, a frame
/// older than 2 s, E-stop, robot not standing) or the brain ending the hold stops renewing and
/// sends Stop. A press that was blocked, or that the brain ended, never drives: the owner has to
/// lift and press again, which gives a new hold id.
struct DeadMan: Sendable {
    static let renewInterval: TimeInterval = 0.4
    static let minGap: TimeInterval = 0.1  // at most 10 drive messages a second
    static let changeThreshold = 0.05

    private(set) var holdId: String?
    private(set) var mustRelease = false
    private var lastSent = -TimeInterval.infinity
    private var lastInput = DriveInput.zero
    private var counter = 0
    private let idPrefix = String(UUID().uuidString.prefix(8))

    var isDriving: Bool { holdId != nil }

    /// Call on every input change and on a timer (about 10 Hz). Returns what to send.
    mutating func update(held: Bool, input: DriveInput, block: DriveBlock?,
                         now: TimeInterval) -> [DriveCommand] {
        if !held { mustRelease = false }
        let blocked = block != nil
        if !held || blocked || mustRelease {
            if held && blocked { mustRelease = true }
            guard holdId != nil else { return [] }
            holdId = nil
            lastSent = -.infinity
            return [.stop]
        }
        guard let id = holdId else {
            counter += 1
            let id = "\(idPrefix)-\(counter)"
            holdId = id
            return [send(input, id, now)]
        }
        let due = now - lastSent >= Self.renewInterval
        let changed = now - lastSent >= Self.minGap && differs(input, lastInput)
        return due || changed ? [send(input, id, now)] : []
    }

    /// The brain ended this press (refusal, safety stop, dead-man). Ignored for older presses.
    mutating func ended(holdId ended: String?) {
        guard let current = holdId, ended == nil || ended == current else { return }
        holdId = nil
        lastSent = -.infinity
        mustRelease = true
    }

    /// STOP was pressed: whatever is held stops counting until it is released.
    mutating func cancel() {
        holdId = nil
        lastSent = -.infinity
        mustRelease = true
    }

    private mutating func send(_ input: DriveInput, _ id: String, _ now: TimeInterval) -> DriveCommand {
        lastSent = now
        lastInput = input
        return .drive(input, holdId: id)
    }

    private func differs(_ a: DriveInput, _ b: DriveInput) -> Bool {
        a.isZero != b.isZero
            || abs(a.x - b.x) > Self.changeThreshold
            || abs(a.y - b.y) > Self.changeThreshold
            || abs(a.turn - b.turn) > Self.changeThreshold
    }
}
