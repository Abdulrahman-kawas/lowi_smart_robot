import SwiftUI

/// iPhone, landscape: the camera fills the screen, the joystick sits under the left thumb, the
/// turn control and STOP under the right one.
struct DriveScreen: View {
    @Environment(AppModel.self) private var model
    @State private var showSettings = false

    var body: some View {
        TimelineView(.periodic(from: .now, by: 0.2)) { _ in
            let now = model.clock()
            let block = model.driveBlock(at: now)
            ZStack {
                CameraView(age: model.frameAge(at: now))
                VStack {
                    LinearGradient(colors: [.black.opacity(0.65), .clear],
                                   startPoint: .top, endPoint: .bottom)
                        .frame(height: 90)
                    Spacer()
                }
                .ignoresSafeArea()
                .allowsHitTesting(false)
                VStack(spacing: 8) {
                    TopBar(now: now, showSettings: $showSettings)
                    if let limiter = model.brain?.robot?.limiter, !limiter.isEmpty {
                        Chip(tint: Theme.amber) {
                            Image(systemName: "tortoise.fill")
                            Text(limiter)
                        }
                        .accessibilityLabel(Text("Motion limited: \(limiter)"))
                    }
                    if let toast = model.toast {
                        ToastView(item: toast)
                    }
                    Spacer()
                    controls(block: block)
                }
                .padding(.horizontal, 12)
                .padding(.vertical, 8)
            }
        }
        .onAppear { model.driveScreenVisible = true }
        .onDisappear { model.driveScreenVisible = false }
        .sheet(isPresented: $showSettings) {
            SettingsView().environment(model)
        }
    }

    @ViewBuilder
    private func controls(block: DriveBlock?) -> some View {
        HStack(alignment: .bottom, spacing: 16) {
            Joystick(enabled: block == nil) { model.setStick($0) }
                .frame(width: 170, height: 170)
            Spacer(minLength: 8)
            VStack(spacing: 10) {
                if let block, block != .notPaired {
                    BlockBanner(block: block)
                }
                if let notice = model.notice {
                    NoticeView(text: notice) { model.notice = nil }
                }
                PostureBar()
            }
            Spacer(minLength: 8)
            HStack(alignment: .bottom, spacing: 16) {
                TurnControl(enabled: block == nil) { model.setTurn($0) }
                    .frame(width: 168, height: 56)
                StopButton()
            }
        }
    }
}

struct CameraView: View {
    @Environment(AppModel.self) private var model
    var age: TimeInterval?

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()
            if let frame = model.frame {
                Image(uiImage: frame)
                    .resizable()
                    .scaledToFit()  // the whole frame: nothing at the edges is hidden
                    .ignoresSafeArea()
                    .saturation((age ?? 99) > AppModel.maxFrameAge ? 0 : 1)
                    .opacity((age ?? 99) > AppModel.maxFrameAge ? 0.45 : 1)
                    .accessibilityLabel(Text("Robot camera"))
            } else {
                VStack(spacing: 10) {
                    ProgressView()
                    Text("Waiting for the camera")
                        .font(.callout)
                        .foregroundStyle(Theme.muted)
                }
            }
        }
    }
}

struct TopBar: View {
    @Environment(AppModel.self) private var model
    var now: TimeInterval
    @Binding var showSettings: Bool

    var body: some View {
        HStack(spacing: 8) {
            LinkChip()
            if let latency = latencyMs {
                Chip {
                    Text(model.address?.isLoopback == true ? "Mac" : "Tailscale")
                    Text("\(latency) ms")
                }
                .accessibilityElement(children: .combine)
                .accessibilityLabel(Text("Link latency \(latency) milliseconds"))
            }
            FrameAgeChip(age: model.frameAge(at: now))
            if let robot = model.brain?.robot {
                if robot.mode != "estop" {  // the E-stop chip already says it
                    Chip(tint: robot.canWalk ? Theme.text : Theme.muted) {
                        Text(RobotMode.name(robot.mode))
                    }
                    .accessibilityLabel(Text("Robot is \(RobotMode.name(robot.mode))"))
                }
                Chip(tint: robot.estop ? Theme.red : Theme.muted) {
                    Image(systemName: robot.estop ? "exclamationmark.octagon.fill" : "octagon")
                    Text(robot.estop ? "E-stop latched" : "E-stop off")
                }
                .accessibilityElement(children: .combine)
            }
            Spacer(minLength: 4)
            if model.brain?.robot?.estop == true {
                Button {
                    Task { await model.requestRelease() }
                } label: {
                    Text("Release…")
                        .font(.caption.weight(.bold))
                        .padding(.horizontal, 12)
                        .padding(.vertical, 7)
                        .background(Capsule().fill(Theme.amber.opacity(0.18)))
                        .overlay(Capsule().stroke(Theme.amber, lineWidth: 1.5))
                        .foregroundStyle(Theme.amber)
                }
                .buttonStyle(.plain)
                .disabled(model.busy)
                .accessibilityHint(Text("Shows a fresh photo from the robot, then asks for a long press."))
                .accessibilityIdentifier("release")
            }
            EStopButton()
            Button {
                showSettings = true
            } label: {
                Image(systemName: "gearshape.fill")
                    .font(.body)
                    .foregroundStyle(Theme.muted)
                    .padding(8)
                    .background(Circle().fill(Theme.panel.opacity(0.85)))
            }
            .buttonStyle(.plain)
            .accessibilityLabel(Text("Settings"))
            .accessibilityIdentifier("settings")
        }
    }

    private var latencyMs: Int? {
        guard let app = model.appRttMs, model.isLive else { return nil }
        return Int((app + (model.brain?.latency.robotCmdRttMs ?? 0)).rounded())
    }
}

/// The true state of the link, never a cheerful guess.
struct LinkChip: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let (label, color) = state
        Chip(tint: color) {
            Circle().fill(color).frame(width: 8, height: 8)
            Text(label)
        }
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("link")
    }

    private var state: (String, Color) {
        switch model.link {
        case .live:
            if model.brain?.online == false {
                return (String(localized: "robot offline"), Theme.red)
            }
            return (String(localized: "LIVE"), Theme.green)
        case .connecting:
            return (String(localized: "connecting"), Theme.amber)
        case .reconnecting(let attempt, _):
            return (String(localized: "reconnecting (\(attempt))"), Theme.amber)
        case .unauthorized:
            return (String(localized: "not paired"), Theme.red)
        case .idle:
            return (String(localized: "offline"), Theme.red)
        }
    }
}

struct FrameAgeChip: View {
    var age: TimeInterval?

    var body: some View {
        let tint = age.map { $0 > AppModel.maxFrameAge ? Theme.red : $0 > 1 ? Theme.amber : Theme.muted }
            ?? Theme.muted
        Chip(tint: tint) {
            Image(systemName: "camera.fill")
            if let age {
                Text("frame \(age.formatted(.number.precision(.fractionLength(1)))) s old")
            } else {
                Text("no frame")
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("frameAge")
    }
}

struct BlockBanner: View {
    var block: DriveBlock

    var body: some View {
        Label(block.message, systemImage: "hand.raised.fill")
            .font(.footnote.weight(.semibold))
            .foregroundStyle(Theme.amber)
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .background(Capsule().fill(Theme.panel.opacity(0.9)))
            .overlay(Capsule().stroke(Theme.amber.opacity(0.6), lineWidth: 1))
            .accessibilityLabel(Text("Driving is off: \(block.message)"))
            .accessibilityIdentifier("driveBlock")
    }
}

struct NoticeView: View {
    var text: String
    var dismiss: () -> Void

    var body: some View {
        Button(action: dismiss) {
            HStack(spacing: 8) {
                Image(systemName: "info.circle.fill")
                Text(text).multilineTextAlignment(.leading)
                Image(systemName: "xmark").font(.caption2)
            }
            .font(.footnote)
            .foregroundStyle(Theme.text)
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .background(RoundedRectangle(cornerRadius: 12).fill(Theme.panel.opacity(0.95)))
        }
        .buttonStyle(.plain)
        .accessibilityHint(Text("Dismisses the message"))
    }
}

struct ToastView: View {
    var item: EventItem

    var body: some View {
        let color = item.event.level == "alert" ? Theme.red : Theme.amber
        Label(item.event.text,
              systemImage: item.event.level == "alert" ? "exclamationmark.triangle.fill"
                  : "exclamationmark.circle.fill")
            .font(.footnote.weight(.semibold))
            .foregroundStyle(color)
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .background(Capsule().fill(Theme.panel.opacity(0.95)))
            .overlay(Capsule().stroke(color.opacity(0.6), lineWidth: 1))
            .transition(.opacity)
            .accessibilityIdentifier("toast")
    }
}

struct PostureBar: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        HStack(spacing: 8) {
            pill("Stand", posture: "stand", id: "stand")
            pill("Sit", posture: "sit", id: "sit")
        }
    }

    private func pill(_ title: LocalizedStringKey, posture: String, id: String) -> some View {
        Button {
            model.posture(posture)
        } label: {
            Text(title)
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(Theme.text)
                .padding(.horizontal, 18)
                .padding(.vertical, 9)
                .background(Capsule().fill(Theme.panel.opacity(0.9)))
                .overlay(Capsule().stroke(Theme.blue.opacity(0.7), lineWidth: 1.5))
        }
        .buttonStyle(.plain)
        .disabled(!model.isLive)
        .opacity(model.isLive ? 1 : 0.4)
        .accessibilityIdentifier(id)
    }
}
