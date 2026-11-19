import SwiftUI

/// The main screen. iPhone (landscape): the camera fills the screen, the joystick sits under the
/// left thumb, the turn control and STOP under the right one. iPad: the same camera stage on the
/// left and a sidebar with the LiDAR radar, robot state, photo and event log.
struct DriveScreen: View {
    @Environment(AppModel.self) private var model
    @Environment(\.horizontalSizeClass) private var widthClass
    @Environment(\.verticalSizeClass) private var heightClass
    @State private var showSettings = false
    @State private var showPhoto = false
    @State private var showTalk = false

    var body: some View {
        TimelineView(.periodic(from: .now, by: 0.2)) { _ in
            let now = model.clock()
            let block = model.driveBlock(at: now)
            if widthClass == .regular && heightClass == .regular {
                PadDriveLayout(now: now, block: block, showSettings: $showSettings)
            } else {
                CameraStage(now: now, block: block, showSettings: $showSettings,
                            showPhoto: $showPhoto, showTalk: $showTalk, compact: true)
            }
        }
        .onAppear { model.driveScreenVisible = true }
        .onDisappear { model.driveScreenVisible = false }
        .onChange(of: showSettings || showPhoto || showTalk) { _, open in model.sheetOpen = open }
        .sheet(isPresented: $showSettings) {
            SettingsView().environment(model)
        }
        .sheet(isPresented: $showPhoto) {
            PhotoSheet().environment(model)
        }
        .sheet(isPresented: $showTalk) {
            TalkSheet().environment(model)
        }
    }
}

/// Camera, top bar and thumb controls. The whole screen on iPhone, the left side on iPad.
struct CameraStage: View {
    @Environment(AppModel.self) private var model
    @Environment(\.layoutDirection) private var direction
    var now: TimeInterval
    var block: DriveBlock?
    @Binding var showSettings: Bool
    var showPhoto: Binding<Bool>? = nil
    var showTalk: Binding<Bool>? = nil
    var compact: Bool

    var body: some View {
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
                TopBar(now: now, showSettings: $showSettings, showPhoto: showPhoto,
                       showTalk: showTalk)
                if let limiter = model.brain?.robot?.limiter, !limiter.isEmpty {
                    Chip(tint: Theme.amber, wraps: true) {
                        Image(systemName: "tortoise.fill")
                        Text(limiter)
                    }
                    .accessibilityLabel(Text("Motion limited: \(limiter)"))
                }
                if let toast = model.toast {
                    ToastView(item: toast)
                }
                Spacer()
                controls
            }
            // The camera needs the room: the heads-up text grows with Dynamic Type up to the first
            // accessibility size. Everything here is also in Settings, the iPad sidebar or VoiceOver.
            .dynamicTypeSize(...DynamicTypeSize.accessibility1)
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
        }
    }

    private var controls: some View {
        HStack(alignment: .bottom, spacing: 16) {
            Joystick(enabled: block == nil) { model.setStick($0) }
                .frame(width: compact ? 170 : 200, height: compact ? 170 : 200)
                .layoutPriority(1)
            VStack(spacing: 10) {
                if let block, block != .notPaired {
                    BlockBanner(block: block)
                }
                if let notice = model.notice {
                    NoticeView(text: notice) { model.notice = nil }
                }
                PostureBar()
            }
            .environment(\.layoutDirection, direction)  // text follows the language
            .frame(minWidth: 0, maxWidth: .infinity)  // gives way first: STOP never leaves the screen
            HStack(alignment: .bottom, spacing: 16) {
                TurnControl(enabled: block == nil) { model.setTurn($0) }
                    .frame(width: compact ? 168 : 200, height: compact ? 56 : 66)
                StopButton()
            }
            .fixedSize()
            .layoutPriority(1)
        }
        // The thumbs stay where they are in every language: the joystick under the left thumb,
        // STOP under the right. Only the text in between follows the layout direction.
        .environment(\.layoutDirection, .leftToRight)
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
    var showPhoto: Binding<Bool>? = nil
    var showTalk: Binding<Bool>? = nil

    var body: some View {
        HStack(spacing: 8) {
            ScrollView(.horizontal, showsIndicators: false) {  // chips scroll when text is large
                HStack(spacing: 8) { chips }
            }
            .scrollBounceBehavior(.basedOnSize)
            buttons
                .fixedSize()
                .layoutPriority(1)
        }
    }

    @ViewBuilder
    private var chips: some View {
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
    }

    @ViewBuilder
    private var buttons: some View {
        HStack(spacing: 8) {
            if model.brain?.robot?.estop == true {
                Button {
                    Task { await model.requestRelease() }
                } label: {
                    Text("Release…")
                        .font(.caption.weight(.bold))
                        .padding(.horizontal, 12)
                        .padding(.vertical, 7)
                        .background(Capsule().fill(Theme.panel))
                        .overlay(Capsule().stroke(Theme.amber, lineWidth: 1.5))
                        .foregroundStyle(Theme.amber)
                }
                .buttonStyle(.plain)
                .disabled(model.busy)
                .accessibilityHint(Text("Shows a fresh photo from the robot, then asks for a long press."))
                .accessibilityIdentifier("release")
            }
            EStopButton()
            if let showPhoto {
                RoundIconButton(systemImage: "camera.viewfinder", label: "Photo", id: "photo") {
                    showPhoto.wrappedValue = true
                }
            }
            if let showTalk {
                RoundIconButton(systemImage: "mic.fill", label: "Talk", id: "talk") {
                    showTalk.wrappedValue = true
                }
            }
            RoundIconButton(systemImage: "gearshape.fill", label: "Settings", id: "settings") {
                showSettings = true
            }
        }
    }

    private var latencyMs: Int? {
        guard let app = model.appRttMs, model.isLive else { return nil }
        return Int((app + (model.brain?.latency.robotCmdRttMs ?? 0)).rounded())
    }
}

struct RoundIconButton: View {
    var systemImage: String
    var label: LocalizedStringKey
    var id: String
    var action: () -> Void

    var body: some View {
        Button(action: action) {
            Image(systemName: systemImage)
                .font(.body)
                .foregroundStyle(Theme.muted)
                .padding(8)
                .background(Circle().fill(Theme.panel.opacity(0.85)))
        }
        .buttonStyle(.plain)
        .accessibilityLabel(Text(label))
        .accessibilityIdentifier(id)
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
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(Text("Link to the robot"))
        .accessibilityValue(Text(label))
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
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(Text("Camera frame"))
        .accessibilityValue(age.map {
            Text("\($0.formatted(.number.precision(.fractionLength(1)))) s old")
        } ?? Text("no frame"))
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
            .background(Capsule().fill(Theme.panel))
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
            .background(Capsule().fill(Theme.panel))
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
                .background(Capsule().fill(Theme.panel))
                .overlay(Capsule().stroke(Theme.blue.opacity(0.7), lineWidth: 1.5))
        }
        .buttonStyle(.plain)
        .disabled(!model.isLive)
        .opacity(model.isLive ? 1 : 0.4)
        .accessibilityIdentifier(id)
    }
}
