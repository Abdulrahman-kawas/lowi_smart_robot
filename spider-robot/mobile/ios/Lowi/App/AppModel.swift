import Observation
import SwiftUI

struct EventItem: Identifiable, Equatable {
    let id: Int
    let at: Date
    let event: BrainEvent
}

/// A fresh frame from the robot and the one-time challenge bound to it, waiting for a long press.
struct ConfirmPrompt: Identifiable, Equatable {
    let id: String  // the challenge id
    let action: String  // estop_release or wake_from_limp
    let image: UIImage?
    let cameraPanDeg: Double?  // where the camera pointed for this photo
    let frameAgeMs: Double  // when it reached this phone
    let receivedAt: TimeInterval
    let expiresAt: TimeInterval

    func photoAge(at now: TimeInterval) -> TimeInterval { frameAgeMs / 1000 + (now - receivedAt) }
}

enum ConnectionCheck: Equatable {
    case reachable(api: Int)
    case unreachable(String, tailscaleOff: Bool)
    case badAddress
}

/// Everything the screens show and every command the app sends.
@MainActor
@Observable
final class AppModel {
    static let maxFrameAge: TimeInterval = 2.0
    static let lookGap: TimeInterval = 0.25

    // MARK: settings, kept between launches
    var addressText: String { didSet { defaults.set(addressText, forKey: Keys.address) } }
    var deviceName: String { didSet { defaults.set(deviceName, forKey: Keys.device) } }
    var hapticsOn: Bool { didSet { defaults.set(hapticsOn, forKey: Keys.haptics) } }
    var speakAnswers: Bool { didSet { defaults.set(speakAnswers, forKey: Keys.speak) } }
    var moveSpeed: Double { didSet { defaults.set(moveSpeed, forKey: Keys.moveSpeed) } }
    private(set) var token: String?

    // MARK: live state
    private(set) var link: LiveSocket.Status = .idle
    private(set) var brain: BrainState?
    private(set) var lidar: LidarScan?
    private(set) var frame: UIImage?
    private(set) var frameAgeAtReceipt: TimeInterval = 0
    private(set) var frameReceivedAt: TimeInterval?
    private(set) var events: [EventItem] = []
    private(set) var toast: EventItem?
    private(set) var appRttMs: Double?
    private(set) var robotId: String?
    var prompt: ConfirmPrompt?
    var notice: String? {
        didSet {
            guard let notice else { return }
            Task { [weak self] in  // a notice is read once and fades; the event log keeps it
                try? await Task.sleep(for: .seconds(6))
                if self?.notice == notice { self?.notice = nil }
            }
        }
    }
    private(set) var busy = false
    private(set) var stopPresses = 0

    // MARK: inputs
    private(set) var stick: CGVector?
    private(set) var turnDx: CGFloat?
    var hasKeyboard = false
    var controllerName: String?
    var textEditing = false  // a text field has the keyboard: keys type, they do not drive
    var isActive = true {
        didSet {
            if !isActive { hardware?.reset() }
            tick()
            updateVideo()
        }
    }
    var driveScreenVisible = false { didSet { updateVideo() } }
    var sheetOpen = false { didSet { tick() } }  // Settings or Photo over the drive screen

    @ObservationIgnored private var deadMan = DeadMan()
    @ObservationIgnored private var keyAxes = DriveMapping.KeyAxes.none
    @ObservationIgnored private var padStick: CGVector?
    @ObservationIgnored private var padTurn: CGFloat?
    @ObservationIgnored private var pendingLook: Double?
    @ObservationIgnored private var lastLookAt: TimeInterval = 0
    @ObservationIgnored private var hardware: HardwareInput?
    @ObservationIgnored private let socket = LiveSocket()
    @ObservationIgnored private var ticker: Task<Void, Never>?
    @ObservationIgnored private var eventCounter = 0
    @ObservationIgnored private let defaults: UserDefaults
    @ObservationIgnored let clock: @Sendable () -> TimeInterval
    @ObservationIgnored let speaker = Speaker()  // here, so an answer keeps playing after a sheet closes

    private enum Keys {
        static let address = "brainAddress"
        static let device = "deviceName"
        static let haptics = "haptics"
        static let speak = "speakAnswers"
        static let moveSpeed = "moveSpeed"
        static let token = "deviceToken"
    }

    init(defaults: UserDefaults = .standard,
         clock: @escaping @Sendable () -> TimeInterval = { ProcessInfo.processInfo.systemUptime }) {
        self.defaults = defaults
        self.clock = clock
        if ProcessInfo.processInfo.arguments.contains("-resetPairing") {
            Keychain.delete(Keys.token)
            defaults.removeObject(forKey: Keys.address)
        }
        addressText = defaults.string(forKey: Keys.address) ?? ""
        deviceName = defaults.string(forKey: Keys.device) ?? UIDevice.current.name
        hapticsOn = defaults.object(forKey: Keys.haptics) as? Bool ?? true
        speakAnswers = defaults.object(forKey: Keys.speak) as? Bool ?? true
        moveSpeed = defaults.object(forKey: Keys.moveSpeed) as? Double ?? 0.5
        token = Keychain.read(Keys.token)
        socket.onStatus = { [weak self] status in self?.linkChanged(status) }
        socket.onMessage = { [weak self] message in self?.handle(message) }
        socket.onPong = { [weak self] rtt in self?.appRttMs = rtt * 1000 }
        ticker = Task { [weak self] in
            while !Task.isCancelled {
                guard let self else { return }
                self.tick()
                try? await Task.sleep(for: .milliseconds(100))
            }
        }
        hardware = HardwareInput(model: self)
        #if DEBUG
        if UITestFakes.isOn {
            startUITestFake()
            return
        }
        #endif
        connect()
    }

    var isPaired: Bool { token != nil }
    var address: BrainAddress? { BrainAddress(addressText) }
    var api: APIClient? { address.map { APIClient(address: $0, token: token) } }
    var isLive: Bool { link == .live }
    var moveSpeedLabel: LocalizedStringKey {
        switch moveSpeed {
        case 0.75: "Lively"
        case 1.0: "Fast"
        default: "Normal"
        }
    }
    var moveSpeedText: LocalizedStringKey {
        switch moveSpeed {
        case 0.75: "Speed: Lively"
        case 1.0: "Speed: Fast"
        default: "Speed: Normal"
        }
    }

    // MARK: derived

    func frameAge(at now: TimeInterval) -> TimeInterval? {
        frameReceivedAt.map { frameAgeAtReceipt + (now - $0) }
    }

    /// Why the drive controls are off right now, or nil when the owner may drive.
    func driveBlock(at now: TimeInterval) -> DriveBlock? {
        guard isPaired else { return .notPaired }
        guard isActive else { return .background }
        if prompt != nil || sheetOpen { return .covered }
        guard isLive else { return .linkLost }
        guard let brain, brain.online, let robot = brain.robot else { return .robotOffline }
        if robot.estop { return .estop }
        if !robot.canWalk { return .notStanding(mode: robot.mode) }
        if let holder = brain.drive.holder, holder != deviceName {
            return .otherDriver(name: holder)
        }
        guard let age = frameAge(at: now) else { return .noFrame }
        if age > Self.maxFrameAge { return .frameStale(seconds: age) }
        return nil
    }

    var isDriving: Bool { deadMan.isDriving }

    // MARK: thumb controls

    func setStick(_ vector: CGVector?) {
        stick = vector
        tick()
    }

    func setTurn(_ dx: CGFloat?) {
        turnDx = dx
        tick()
    }

    func setKeys(_ axes: DriveMapping.KeyAxes) {
        keyAxes = axes
        tick()
    }

    func setPad(stick: CGVector?, turn: CGFloat?) {
        padStick = stick
        padTurn = turn
        tick()
    }

    /// Touch first, then keys, then a controller: whichever is held drives, one at a time.
    func tick() {
        let now = clock()
        let touch = stick != nil || turnDx != nil
        let pad = padStick != nil || padTurn != nil
        let input = touch ? DriveMapping.input(stick: stick, turn: turnDx)
            : keyAxes.isHeld ? DriveMapping.input(forward: keyAxes.forward, left: keyAxes.left,
                                                  turnLeft: keyAxes.turnLeft)
            : DriveMapping.input(stick: padStick, turn: padTurn)
        perform(deadMan.update(held: touch || keyAxes.isHeld || pad, input: input,
                               block: driveBlock(at: now), now: now))
        flushLook(force: false)
    }

    private func perform(_ commands: [DriveCommand]) {
        for command in commands {
            switch command {
            case .drive(let input, let holdId):
                socket.send(.drive(input, holdId: holdId))
            case .stop:
                if !socket.send(.stop) { Task { try? await api?.stop() } }
            }
        }
    }

    // MARK: buttons that never wait

    /// STOP goes out on the socket and over HTTP at once: whichever path still works delivers it.
    func pressStop() {
        stopPresses += 1
        if hapticsOn { Haptics.stop() }
        deadMan.cancel()
        guard isPaired, let api else {
            notice = String(localized: "Not paired yet. Say “stop” to the robot or send /stop in Telegram.")
            return
        }
        socket.send(.stop)
        Task { try? await api.stop() }
    }

    func pressEstop() {
        if hapticsOn { Haptics.stop() }
        deadMan.cancel()
        guard isPaired, let api else {
            notice = String(localized: "Not paired yet. Say “stop” to the robot or send /estop in Telegram.")
            return
        }
        socket.send(.estop)
        Task { try? await api.estop() }
    }

    func posture(_ posture: String) {
        if !socket.send(.posture(posture)) {
            notice = String(localized: "Not connected to the brain.")
        }
    }

    func startMove(_ name: String, leg: String?) {
        if !socket.send(.perform(name: name, speed: moveSpeed, leg: leg)) {
            notice = String(localized: "Not connected to the brain.")
        }
    }

    /// Dragging the camera slider coalesces into one Look every 0.25 s; release always sends.
    func look(_ panDeg: Double, final: Bool = false) {
        pendingLook = panDeg
        if final {
            flushLook(force: true)
        } else {
            tick()
        }
    }

    private func flushLook(force: Bool) {
        guard let pan = pendingLook else { return }
        let now = clock()
        guard force || now - lastLookAt >= Self.lookGap else { return }
        guard socket.send(.look(panDeg: pan, speed: 0.5)) else {
            pendingLook = nil
            notice = String(localized: "Not connected to the brain.")
            return
        }
        pendingLook = nil
        lastLookAt = now
    }

    func takePhoto(question: String?) async throws -> PhotoResult {
        guard let api, isPaired else { throw APIError.unauthorized(String(localized: "Not paired")) }
        return try await api.photo(question: question)
    }

    /// Sends what the owner said and returns the brain's answer. The reply is shown and spoken
    /// only; nothing here sends motion. A stop word was already acted on by the brain.
    func talk(wav: Data) async throws -> TalkReply {
        guard let api, isPaired else { throw APIError.unauthorized(String(localized: "Not paired")) }
        let reply = try await api.talk(wav: wav)
        if reply.stoppedRobot, hapticsOn { Haptics.stop() }
        if speakAnswers {
            if let audio = reply.audio, speaker.play(audio) {
                // Lowi's own voice from the brain
            } else {
                speaker.say(reply.reply)
            }
        }
        return reply
    }

    // MARK: confirmed actions

    func requestRelease() async {
        await startConfirm { try await $0.releaseEstop() }
    }

    func requestWake(posture: String) async {
        await startConfirm { try await $0.wake(posture: posture) }
    }

    private func startConfirm(_ call: (APIClient) async throws -> Challenge) async {
        guard let api, !busy else { return }
        busy = true
        defer { busy = false }
        do {
            let challenge = try await call(api)
            let now = clock()
            prompt = ConfirmPrompt(
                id: challenge.challengeId, action: challenge.action,
                image: challenge.jpeg.flatMap(UIImage.init(data:)),
                cameraPanDeg: brain?.robot?.cameraPanDeg,
                frameAgeMs: challenge.frameAgeMs, receivedAt: now, expiresAt: now + challenge.ttlS)
        } catch {
            refuse(error.localizedDescription)
        }
    }

    func answer(_ prompt: ConfirmPrompt, approved: Bool) async {
        guard let api else { return }
        self.prompt = nil
        do {
            let result = try await api.confirm(challengeId: prompt.id, approved: approved)
            switch result.result {
            case "released": notice = String(localized: "E-stop released.")
            case "posture_sent": notice = String(localized: "Posture sent.")
            case "cancelled": break
            default: refuse(result.detail)
            }
        } catch {
            refuse(error.localizedDescription)
        }
    }

    // MARK: pairing

    func checkConnection() async -> ConnectionCheck {
        guard let address else { return .badAddress }
        do {
            let info = try await APIClient(address: address).hello()
            return .reachable(api: info.api)
        } catch {
            let off = !address.isLoopback && !TailscaleCheck.hasTailnetAddress()
            return .unreachable(error.localizedDescription, tailscaleOff: off)
        }
    }

    /// Returns an error to show, or nil once paired.
    func pair(code: String) async -> String? {
        guard let address else { return String(localized: "Enter the brain's address first.") }
        do {
            let result = try await APIClient(address: address)
                .pair(code: code, deviceName: deviceName)
            Keychain.write(Keys.token, result.token)
            token = result.token
            deviceName = result.deviceName
            robotId = result.robotId
            notice = nil
            connect()
            return nil
        } catch {
            return error.localizedDescription
        }
    }

    func unpair() {
        socket.stop()
        Keychain.delete(Keys.token)
        token = nil
        brain = nil
        lidar = nil
        frame = nil
        frameReceivedAt = nil
        events = []
        toast = nil
    }

    func connect() {
        guard let token, let address else { return }
        socket.start(url: address.liveURL, token: token)
    }

    // MARK: from the brain

    private func linkChanged(_ status: LiveSocket.Status) {
        link = status
        switch status {
        case .live:
            updateVideo()
        case .unauthorized:
            unpair()
            notice = String(localized: "This phone is no longer paired with the brain. Pair it again.")
        case .connecting, .reconnecting, .idle:
            break
        }
        tick()  // a lost link stops any drive at once
    }

    private func updateVideo() {
        socket.send(.video(driveScreenVisible && isActive))
    }

    func handle(_ message: ServerMessage) {
        switch message {
        case .hello(let hello):
            robotId = hello.robotId
        case .state(let state):
            brain = state
        case .lidar(let scan):
            lidar = scan
        case .event(let event):
            record(event)
        case .frame(let header, let jpeg):
            guard let image = UIImage(data: jpeg) else { return }
            frame = image
            frameAgeAtReceipt = header.ageMs / 1000
            frameReceivedAt = clock()
        case .pong, .unknown:
            break
        }
    }

    private func record(_ event: BrainEvent) {
        eventCounter += 1
        let item = EventItem(id: eventCounter, at: Date(), event: event)
        events.append(item)
        if events.count > 100 { events.removeFirst(events.count - 100) }
        if event.kind == "drive_ended" || event.kind == "drive_refused" {
            deadMan.ended(holdId: event.holdId)
        }
        if event.refusal, hapticsOn { Haptics.refusal() }
        if event.kind == "needs_confirm" {
            let posture = event.detail.split(separator: ":").last.map(String.init) ?? "stand"
            Task { await requestWake(posture: posture) }
            return
        }
        if event.level != "info" || event.refusal {
            showToast(item)
        }
    }

    private func showToast(_ item: EventItem) {
        toast = item
        announce(item.event.text)
        Task { [weak self] in
            try? await Task.sleep(for: .seconds(4))
            if self?.toast?.id == item.id { self?.toast = nil }
        }
    }

    private func refuse(_ message: String) {
        if hapticsOn { Haptics.refusal() }
        notice = message.isEmpty ? String(localized: "Refused, with no reason given.") : message
        announce(notice ?? message)
    }

    /// VoiceOver users hear refusals and alerts, which sighted users see as banners.
    private func announce(_ text: String) {
        guard UIAccessibility.isVoiceOverRunning else { return }
        AccessibilityNotification.Announcement(text).post()
    }

    #if DEBUG
    /// UI tests: a paired phone and a robot with a latched E-stop, without a brain. HTTP calls
    /// are answered by UITestFakes; there is no socket, so the link reads "offline".
    private func startUITestFake() {
        UITestFakes.install()
        if ProcessInfo.processInfo.arguments.contains("-uiTestUnpaired") { return }  // Connect
        token = "ui-test"
        addressText = UITestFakes.address
        deviceName = "UI test"
        robotId = "spider-01"
        brain = UITestFakes.state
        lidar = UITestFakes.lidar
        for event in UITestFakes.events { record(event) }
        toast = nil
        Task { [weak self] in
            while !Task.isCancelled {  // keep the frame fresh, as the live view would
                self?.handle(.frame(FrameHeader(n: 1, ageMs: 120), UITestFakes.jpeg))
                try? await Task.sleep(for: .seconds(0.6))
            }
        }
    }
    #endif
}

extension DriveBlock {
    var message: String {
        switch self {
        case .notPaired: String(localized: "Not paired")
        case .linkLost: String(localized: "No link to the brain")
        case .background: String(localized: "App in the background")
        case .covered: String(localized: "Close the window on top to drive")
        case .robotOffline: String(localized: "Robot offline")
        case .noFrame: String(localized: "Waiting for the camera")
        case .frameStale(let seconds):
            String(localized: "Camera frame \(seconds.formatted(.number.precision(.fractionLength(1)))) s old")
        case .estop: String(localized: "E-stop is latched")
        case .notStanding(let mode): String(localized: "Robot is \(RobotMode.name(mode)): stand it up first")
        case .otherDriver(let name): String(localized: "\(name) is driving")
        }
    }
}

extension BrainEvent {
    /// "E-stop: latched", "Refused: busy: voice is in control", or the detail alone.
    var text: String {
        if kind == "needs_confirm" {
            return String(localized: "The robot is limp: standing it up needs a fresh photo and a long press")
        }
        let title: String? = switch kind {
        case "estop": String(localized: "E-stop")
        case "obstacle_stop": String(localized: "Obstacle stop")
        case "tilt": String(localized: "Tilt")
        case "fallen": String(localized: "Fallen")
        case "link_lost": String(localized: "Link lost")
        case "offline": String(localized: "Robot offline")
        case "health": String(localized: "Health")
        case "rejected": String(localized: "Refused")
        case "preempted": String(localized: "Taken over")
        case "drive_refused": String(localized: "Drive refused")
        case "drive_ended": String(localized: "Drive ended")
        case "perform_started": String(localized: "Move started")
        case "perform_done": String(localized: "Move done")
        case "perform_rejected": String(localized: "Move refused")
        case "clamped": String(localized: "Limited")
        case "video_slowed", "video_failed", "video_ok": String(localized: "Live view")
        default: nil
        }
        guard let title else { return detail.isEmpty ? kind : detail }
        return detail.isEmpty ? title : "\(title): \(detail)"
    }
}

enum RobotMode {
    static func name(_ mode: String) -> String {
        switch mode {
        case "relaxed": String(localized: "relaxed")
        case "sitting": String(localized: "sitting")
        case "standing": String(localized: "standing")
        case "walking": String(localized: "walking")
        case "estop": String(localized: "E-stopped")
        case "fallen": String(localized: "fallen")
        default: mode
        }
    }
}
