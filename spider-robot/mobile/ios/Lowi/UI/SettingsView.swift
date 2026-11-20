import SwiftUI

struct SettingsView: View {
    private enum Confirmation: Equatable {
        case unpair
        case protectionOff
    }

    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @Environment(\.openURL) private var openURL
    @State private var confirmation: Confirmation?
    @State private var showConfirmation = false
    @State private var speedDraft: Double?  // cm/s while a finger is on the slider
    @State private var turnDraft: Double?  // degrees/s

    var body: some View {
        @Bindable var model = model
        NavigationStack {
            Form {
                Section {
                    row("Name", model.deviceName)
                    row("Brain", model.address?.base.host() ?? "-")
                    if let robot = model.robotId {
                        row("Robot", robot)
                    }
                } header: {
                    Text("This device").foregroundStyle(Theme.muted)
                }
                Section {
                    Toggle("Haptics", isOn: $model.hapticsOn)
                        .accessibilityIdentifier("hapticsToggle")
                    // Explanations sit in the rows, not in section footers: iOS 17 does not let
                    // footer text grow with Dynamic Type.
                    Button {
                        if let url = URL(string: UIApplication.openSettingsURLString) {
                            openURL(url)
                        }
                    } label: {
                        VStack(alignment: .leading, spacing: 4) {
                            Text("Language")
                            Text("The app follows the language you choose for it in iOS Settings.")
                                .font(.footnote)
                                .foregroundStyle(Theme.muted)
                        }
                    }
                    // Below Language: above it, the audit read the Language row as fixed-size text.
                    Toggle("Speak answers", isOn: $model.speakAnswers)
                        .accessibilityIdentifier("speakToggle")
                }
                speedSection
                Section {
                    Toggle("LiDAR protection", isOn: Binding(
                        get: { model.protectionOn },
                        set: { enabled in
                            if enabled {
                                model.setProtection(true)
                            } else {
                                confirmation = .protectionOff
                                showConfirmation = true
                            }
                        }
                    ))
                    .disabled(!model.isLive || model.brain?.robot?.estop == true)
                    .accessibilityIdentifier("protectionToggle")
                    Text("The robot stops for obstacles while protection is on. Turn it off only for a controlled test.")
                        .font(.footnote)
                        .foregroundStyle(Theme.muted)
                } header: {
                    Text("Safety").foregroundStyle(Theme.muted)
                }
                Section {
                    Toggle("Voice can start moves", isOn: Binding(
                        get: { model.movesState.voice },
                        set: { model.setMoves(voice: $0) }
                    ))
                    .disabled(!model.isLive)
                    .accessibilityIdentifier("voiceMovesToggle")
                    Toggle("This app can start moves", isOn: Binding(
                        get: { model.movesState.remote },
                        set: { model.setMoves(remote: $0) }
                    ))
                    .disabled(!model.isLive)
                    .accessibilityIdentifier("appMovesToggle")
                    Button("Allow both") { model.setMoves(voice: true, remote: true) }
                        .disabled(!model.isLive)
                        .accessibilityIdentifier("allowBothMoves")
                    Button("Block both") { model.setMoves(voice: false, remote: false) }
                        .disabled(!model.isLive)
                        .accessibilityIdentifier("blockBothMoves")
                } header: {
                    Text("Moves").foregroundStyle(Theme.muted)
                }
                Section {
                    Button(role: .destructive) {
                        confirmation = .unpair
                        showConfirmation = true
                    } label: {
                        VStack(alignment: .leading, spacing: 4) {
                            Text("Unpair this device")
                                .foregroundStyle(Theme.red)  // 5.7:1 on the row; system red is under 4.5
                            Text("Forgets the token on this device. To cut it off on the server as well, run `spider-brain devices revoke \"\(model.deviceName)\"`.")
                                .font(.footnote)
                                .foregroundStyle(Theme.muted)
                        }
                    }
                    .accessibilityIdentifier("unpair")
                }
            }
            .scrollContentBackground(.hidden)
            .background(Theme.background)
            .accessibilityIdentifier("settingsForm")
            .stopSide(id: "stop.settings")  // the form lays out beside STOP
            .navigationTitle("Settings")
            .navigationBarTitleDisplayMode(.inline)
            .sheetBar()
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }
                        .accessibilityIdentifier("closeSettings")
                }
            }
            .confirmationDialog(confirmation == .unpair ? Text("Unpair this device?") :
                                    Text("Turn off LiDAR protection?"),
                                isPresented: $showConfirmation,
                                titleVisibility: .visible) {
                if confirmation == .unpair {
                    Button("Unpair", role: .destructive) {
                        model.pressStop()
                        dismiss()
                        model.unpair()
                    }
                } else {
                    Button("Turn off", role: .destructive) { model.setProtection(false) }
                    Button("Cancel", role: .cancel) {}
                }
            } message: {
                if confirmation == .protectionOff {
                    Text("The robot will not stop for obstacles. Protection comes back when the app closes.")
                }
            }
        }
    }

    /// The app's top speed, kept by the gateway (sliders), and how much of it walking, turning
    /// and moves use (kept on this device). Off while not live; the sliders show the gateway's
    /// real value, and it refuses anything above its ceiling.
    private var speedSection: some View {
        @Bindable var model = model
        let top = model.topSpeed
        let limits = model.brain?.gateway.remoteLimits
        let caps = model.brain?.caps
        let speedMax = max(3, min(12, ((limits?.ceilingSpeedMps ?? 0.12) * 100 + 1e-6).rounded(.down)))
        let turnMax = max(11, min(34, (Self.degrees(limits?.ceilingWzRps ?? 0.6) + 1e-6).rounded(.down)))
        let speedNow = speedDraft ?? (top?.speedMps ?? 0.05) * 100
        let turnNow = turnDraft ?? Self.degrees(top?.wzRps ?? 0.3)
        return Section {
            VStack(alignment: .leading, spacing: 6) {
                valueRow("Top speed from the app", top == nil ? "-" : Self.cm(speedNow))
                Slider(value: Binding(get: { speedNow }, set: { speedDraft = $0 }),
                       in: 2...speedMax, step: 1) { editing in
                    if !editing, let cm = speedDraft {
                        model.setTopSpeed(speedMps: cm / 100)
                        speedDraft = nil
                    }
                }
                .accessibilityLabel(Text("Top speed from the app"))
                .accessibilityValue(Text(Self.cm(speedNow)))
                .accessibilityIdentifier("topSpeedSlider")
            }
            .disabled(!model.isLive || top == nil)
            VStack(alignment: .leading, spacing: 6) {
                valueRow("Top turning speed", top == nil ? "-" : Self.deg(turnNow))
                Slider(value: Binding(get: { turnNow }, set: { turnDraft = $0 }),
                       in: 10...turnMax, step: 1) { editing in
                    if !editing, let deg = turnDraft {
                        model.setTopSpeed(wzRps: deg * .pi / 180)
                        turnDraft = nil
                    }
                }
                .accessibilityLabel(Text("Top turning speed"))
                .accessibilityValue(Text(Self.deg(turnNow)))
                .accessibilityIdentifier("topTurnSlider")
                if let limits {
                    Text("Most the robot allows: \(Self.cm(limits.ceilingSpeedMps * 100)), \(Self.deg(Self.degrees(limits.ceilingWzRps)))")
                        .font(.footnote)
                        .foregroundStyle(Theme.muted)
                        .accessibilityIdentifier("speedCeiling")
                }
            }
            .disabled(!model.isLive || top == nil)
            preset("Walking", selection: $model.walkSpeed,
                   value: caps.map { Self.cm($0.maxSpeedMps * model.walkSpeed * 100) },
                   id: "walkSpeed")
            preset("Turning", selection: $model.turnSpeed,
                   value: caps.map { Self.deg(Self.degrees($0.maxWzRps * model.turnSpeed)) },
                   id: "turnSpeed")
            VStack(alignment: .leading, spacing: 8) {
                Text("Moves")
                Picker("Moves", selection: $model.moveSpeed) {
                    Text("Normal").tag(0.5)
                    Text("Lively").tag(0.75)
                    Text("Fast").tag(1.0)
                }
                .pickerStyle(.segmented)
                .accessibilityIdentifier("moveSpeed")
            }
            .disabled(!model.isLive)
        } header: {
            Text("Speed").foregroundStyle(Theme.muted)
        }
    }

    /// Slow, Normal or Fast: 40, 70 or 100 % of the top speed, sent with every drive.
    private func preset(_ title: LocalizedStringKey, selection: Binding<Double>, value: String?,
                        id: String) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            valueRow(title, value ?? "-")
                .accessibilityIdentifier("\(id)Value")
            Picker(title, selection: selection) {
                Text("Slow").tag(0.4)
                Text("Normal").tag(0.7)
                Text("Fast").tag(1.0)
            }
            .pickerStyle(.segmented)
            .accessibilityIdentifier(id)
        }
        .disabled(!model.isLive)
    }

    private func valueRow(_ label: LocalizedStringKey, _ value: String) -> some View {
        HStack(alignment: .firstTextBaseline) {
            Text(label)
            Spacer(minLength: 12)
            Text(value)
                .foregroundStyle(Theme.muted)
                .monospacedDigit()
        }
        .accessibilityElement(children: .combine)
    }

    static func degrees(_ radians: Double) -> Double { radians * 180 / .pi }

    static func cm(_ cmPerSecond: Double) -> String {
        String(localized: "\(cmPerSecond.formatted(.number.precision(.fractionLength(0...1)))) cm/s")
    }

    static func deg(_ degreesPerSecond: Double) -> String {
        String(localized: "\(degreesPerSecond.formatted(.number.precision(.fractionLength(0)))) °/s")
    }

    /// A label and its value; long values wrap instead of truncating.
    private func row(_ label: LocalizedStringKey, _ value: String) -> some View {
        HStack(alignment: .firstTextBaseline) {
            Text(label)
            Spacer(minLength: 12)
            Text(value)
                .foregroundStyle(Theme.muted)
                .multilineTextAlignment(.trailing)
        }
        .accessibilityElement(children: .combine)
    }
}
