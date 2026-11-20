import SwiftUI

/// iPad: the camera stage large on the left, a sidebar on the right. In portrait the sidebar
/// moves under the camera.
struct PadDriveLayout: View {
    @Environment(AppModel.self) private var model
    var now: TimeInterval
    var block: DriveBlock?
    @Binding var showSettings: Bool
    @Binding var showMoves: Bool
    @State private var landscape = true

    var body: some View {
        Group {
            if landscape {
                HStack(spacing: 0) {
                    CameraStage(now: now, block: block, showSettings: $showSettings,
                                showMoves: $showMoves, compact: false)
                    ScrollView {
                        Sidebar(columns: 1, showMoves: $showMoves).padding(14)
                    }
                    .frame(width: 360)
                    .background(Theme.background)
                }
            } else {
                VStack(spacing: 0) {
                    CameraStage(now: now, block: block, showSettings: $showSettings,
                                showMoves: $showMoves, compact: false)
                        .frame(maxHeight: .infinity)
                        .layoutPriority(1)
                    ScrollView {
                        Sidebar(columns: 2, showMoves: $showMoves).padding(14)
                    }
                    .frame(height: 380)
                    .background(Theme.background)
                }
            }
        }
        .onGeometryChange(for: Bool.self) { $0.size.width > $0.size.height } action: {
            landscape = $0
        }
    }
}

struct Sidebar: View {
    @Environment(AppModel.self) private var model
    var columns: Int
    @Binding var showMoves: Bool

    // Plain stacks, not a lazy grid: the sidebar is short, and a lazy grid holding a growing text
    // field hung the layout while scrolling.
    var body: some View {
        if columns == 1 {
            VStack(spacing: 14) {
                surroundings
                robot
                moves
                photo
                talk
                events
                InputHints()
            }
        } else {
            HStack(alignment: .top, spacing: 14) {
                VStack(spacing: 14) {
                    surroundings
                    robot
                    moves
                }
                VStack(spacing: 14) {
                    photo
                    talk
                    events
                    InputHints()
                }
            }
        }
    }

    private var surroundings: some View {
        SideCard(title: "Surroundings", systemImage: "dot.radiowaves.left.and.right") {
            LidarRadar(scan: model.lidar)
                .frame(maxWidth: 300)
                .frame(maxWidth: .infinity)
            Text(LidarRadar.summary(model.lidar))
                .font(.footnote)
                .foregroundStyle(Theme.muted)
        }
    }

    private var robot: some View {
        SideCard(title: "Robot", systemImage: "info.circle") { RobotStatePanel() }
    }

    private var moves: some View {
        SideCard(title: "Moves", systemImage: "figure.dance") {
            MovesSideCard(showMoves: $showMoves)
        }
    }

    private var photo: some View {
        SideCard(title: "Photo", systemImage: "camera") { PhotoPanel() }
    }

    private var talk: some View {
        SideCard(title: "Talk", systemImage: "mic") { TalkPanel() }
    }

    private var events: some View {
        SideCard(title: "Events", systemImage: "list.bullet.rectangle") { EventLog() }
    }
}

struct SideCard<Content: View>: View {
    var title: LocalizedStringKey
    var systemImage: String
    @ViewBuilder var content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Label(title, systemImage: systemImage)
                .font(.headline)
                .foregroundStyle(Theme.text)
                .accessibilityAddTraits(.isHeader)
            content
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 14).fill(Theme.panel))
        .overlay(RoundedRectangle(cornerRadius: 14).stroke(Theme.panelLine, lineWidth: 1))
    }
}

struct RobotStatePanel: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let brain = model.brain
        let robot = brain?.robot
        Grid(alignment: .leading, horizontalSpacing: 12, verticalSpacing: 6) {
            row("Mode", robot.map { RobotMode.name($0.mode) } ?? "-")
            row("E-stop", robot.map { $0.estop ? String(localized: "latched") : String(localized: "off") } ?? "-",
                tint: robot?.estop == true ? Theme.red : Theme.text)
            row("Speed", robot.map { speed($0) } ?? "-")
            row("Tilt", robot.map { tilt($0) } ?? "-")
            row("Limiter", robot?.limiter ?? String(localized: "none"),
                tint: robot?.limiter == nil ? Theme.text : Theme.amber)
            row("Motion owner", brain?.gateway.owner ?? String(localized: "nobody"))
            row("Driving", brain?.drive.holder ?? String(localized: "nobody"))
            row("Phone ↔ brain", ms(model.appRttMs))
            row("Brain ↔ robot", ms(brain?.latency.robotCmdRttMs ?? brain?.latency.frameRttMs))
        }
        .font(.footnote.monospacedDigit())
        .accessibilityElement(children: .contain)
    }

    private func row(_ label: LocalizedStringKey, _ value: String, tint: Color = Theme.text) -> some View {
        GridRow {
            Text(label).foregroundStyle(Theme.muted)
            Text(value).foregroundStyle(tint).lineLimit(2)
        }
        .accessibilityElement(children: .combine)
    }

    private func speed(_ robot: RobotStatus) -> String {
        let linear = (robot.vx * robot.vx + robot.vy * robot.vy).squareRoot()
        let turn = robot.wz * 180 / .pi
        return String(localized: "\(linear.formatted(.number.precision(.fractionLength(2)))) m/s, \(turn.formatted(.number.precision(.fractionLength(0)))) °/s")
    }

    private func tilt(_ robot: RobotStatus) -> String {
        guard let roll = robot.rollDeg, let pitch = robot.pitchDeg else {
            return String(localized: "unknown")
        }
        return String(localized: "roll \(roll.formatted(.number.precision(.fractionLength(0))))°, pitch \(pitch.formatted(.number.precision(.fractionLength(0))))°")
    }

    private func ms(_ value: Double?) -> String {
        value.map { "\(Int($0.rounded())) ms" } ?? "-"
    }
}

struct EventLog: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        let recent = Array(model.events.suffix(40).reversed())
        VStack(alignment: .leading, spacing: 6) {
            if recent.isEmpty {
                Text("Nothing yet").font(.footnote).foregroundStyle(Theme.muted)
            }
            ForEach(recent) { item in
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Text(item.at, format: .dateTime.hour().minute().second())
                        .font(.caption2.monospacedDigit())
                        .foregroundStyle(Theme.muted)
                    Image(systemName: icon(item.event))
                        .font(.caption2)
                        .foregroundStyle(color(item.event))
                    Text(item.event.text)
                        .font(.caption)
                        .foregroundStyle(Theme.text)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .accessibilityElement(children: .combine)
            }
        }
        .accessibilityIdentifier("eventLog")
    }

    private func icon(_ event: BrainEvent) -> String {
        event.level == "alert" ? "exclamationmark.triangle.fill"
            : event.refusal ? "hand.raised.fill" : "circle.fill"
    }

    private func color(_ event: BrainEvent) -> Color {
        event.level == "alert" ? Theme.red : event.refusal || event.level == "warn" ? Theme.amber
            : Theme.muted
    }
}

/// Which hardware is ready to drive, and its keys.
struct InputHints: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            if model.hasKeyboard {
                Label("W S forward, back · A D sideways · Q E turn · Space stop · Esc E-stop",
                      systemImage: "keyboard")
            }
            if let name = model.controllerName {
                Label("\(name): left stick drives, right stick turns, B stops, Y E-stops",
                      systemImage: "gamecontroller")
            }
        }
        .font(.caption)
        .foregroundStyle(Theme.muted)
    }
}
