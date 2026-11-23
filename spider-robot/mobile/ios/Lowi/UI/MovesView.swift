import SwiftUI
import UIKit

private struct MoveOption: Identifiable, Sendable {
    let name: String
    let title: String
    let symbol: String
    var id: String { name }
}

private struct MoveGroup: Identifiable, Sendable {
    let id: String
    let title: String
    let moves: [MoveOption]
}

private let moveGroups: [MoveGroup] = [
    MoveGroup(id: "greetings", title: "Greetings", moves: [
        MoveOption(name: "wave", title: "Wave", symbol: "hand.wave"),
        MoveOption(name: "hi", title: "Hi", symbol: "hand.raised"),
        MoveOption(name: "double_hi", title: "Double hi", symbol: "hands.clap"),
        MoveOption(name: "offer_hand", title: "Shake hands", symbol: "hand.point.right"),
        MoveOption(name: "bow", title: "Bow", symbol: "arrow.down.circle"),
    ]),
    MoveGroup(id: "dance", title: "Dance and fun", moves: [
        MoveOption(name: "dance", title: "Dance", symbol: "figure.dance"),
        MoveOption(name: "body_wave", title: "Body wave", symbol: "water.waves"),
        MoveOption(name: "shimmy", title: "Shimmy", symbol: "arrow.left.and.right"),
        MoveOption(name: "leg_ripple", title: "Leg ripple", symbol: "wave.3.right"),
        MoveOption(name: "stomp", title: "Stomp", symbol: "shoeprints.fill"),
        MoveOption(name: "crab_sway", title: "Crab sway", symbol: "arrow.left.arrow.right"),
        MoveOption(name: "celebrate", title: "Celebrate", symbol: "party.popper"),
    ]),
    MoveGroup(id: "stances", title: "Stances", moves: [
        MoveOption(name: "attack_stance", title: "Attack stance", symbol: "bolt.fill"),
        MoveOption(name: "defense_stance", title: "Defense stance", symbol: "shield.fill"),
        MoveOption(name: "alert", title: "Alert", symbol: "exclamationmark.triangle"),
        MoveOption(name: "stretch", title: "Stretch", symbol: "figure.flexibility"),
        MoveOption(name: "sleep", title: "Sleep", symbol: "moon.zzz.fill"),
    ]),
]

private let allMoves = moveGroups.flatMap(\.moves)
private let legMoves = Set(["wave", "hi", "offer_hand"])
private let resultKinds = Set(["perform_started", "perform_done", "perform_rejected", "rejected",
                              "clamped"])

struct MovesPanel: View {
    @Environment(AppModel.self) private var model
    @State private var leg = "LF"
    @State private var selected = "wave"
    var onOpenSettings: (() -> Void)? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            status
                .font(.footnote)
                .foregroundStyle(Theme.text)
                .frame(maxWidth: .infinity, alignment: .leading)
                .accessibilityIdentifier("moveStatus")
            if let onOpenSettings {
                Button(action: onOpenSettings) { speed }
                    .buttonStyle(.plain)
                    .accessibilityHint(Text("Open moves settings"))
                    .accessibilityIdentifier("moveSpeedLine")
            } else {
                speed
            }
            if let reason = blockReason {
                Label(reason, systemImage: "exclamationmark.triangle")
                    .font(.footnote)
                    .foregroundStyle(Theme.amber)
            }
            if appMovesOff {
                VStack(alignment: .leading, spacing: 6) {
                    Label("Moves from the app are switched off", systemImage: "exclamationmark.triangle")
                        .font(.footnote)
                        .foregroundStyle(Theme.amber)
                        .accessibilityIdentifier("movesSwitchOff")
                    if let onOpenSettings {
                        Button("Open moves settings", action: onOpenSettings)
                            .buttonStyle(.bordered)
                            .accessibilityIdentifier("movesOpenSettings")
                    }
                }
            }
            if legMoves.contains(selected) {
                Picker("Leading leg", selection: $leg) {
                    Text("Left").tag("LF")
                    Text("Right").tag("RF")
                }
                .pickerStyle(.segmented)
                .accessibilityIdentifier("moveLeg")
            }
            ForEach(moveGroups) { group in
                VStack(alignment: .leading, spacing: 6) {
                    Text(LocalizedStringKey(group.title))
                        .font(.caption.weight(.bold))
                        .foregroundStyle(Theme.muted)
                        .accessibilityAddTraits(.isHeader)
                    LazyVGrid(columns: [GridItem(.adaptive(minimum: 110), spacing: 8)], spacing: 8) {
                        ForEach(group.moves) { move in
                            Button {
                                selected = move.name
                                model.startMove(move.name, leg: legMoves.contains(move.name) ? leg : nil)
                            } label: {
                                VStack(spacing: 6) {
                                    Image(systemName: symbol(move.symbol))
                                    Text(LocalizedStringKey(move.title))
                                        .font(.caption)
                                        .minimumScaleFactor(0.8)
                                        .lineLimit(1...3)
                                }
                                .frame(maxWidth: .infinity, minHeight: 64)
                            }
                            .buttonStyle(.bordered)
                            .disabled(isDisabled(move))
                            .accessibilityHint(Text(hint(move)))
                            .accessibilityIdentifier("move_\(move.name)")
                        }
                        .opacity(appMovesOff ? 0.4 : 1)
                    }
                }
            }
            if heldPose {
                Text("Stopped mid-move: press Stand to return to the stand pose")
                    .font(.footnote)
                    .foregroundStyle(Theme.amber)
                Button("Stand") { model.posture("stand") }
                    .buttonStyle(.borderedProminent)
                    .accessibilityIdentifier("moveStand")
            }
        }
        .dynamicTypeSize(...DynamicTypeSize.accessibility1)
    }

    private var speed: some View {
        HStack {
            Text(model.moveSpeedText)
            Spacer()
            Image(systemName: "speedometer")
        }
        .font(.callout)
        .foregroundStyle(Theme.text)
    }

    @ViewBuilder
    private var status: some View {
        if let running = model.brain?.robot?.perform, !running.isEmpty {
            HStack(spacing: 4) {
                Text("Running")
                Text(":")
                Text(title(running))
            }
        } else if let last = model.events.reversed()
            .first(where: { resultKinds.contains($0.event.kind) }) {
            Text(last.event.detail)
        } else {
            Text("No move yet")
        }
    }

    private var appMovesOff: Bool { !model.movesState.remote }

    private var blockReason: String? {
        guard model.isPaired else { return String(localized: "Not paired") }
        guard model.isLive else { return String(localized: "No link to the brain") }
        guard let robot = model.brain?.robot else { return String(localized: "Robot offline") }
        if robot.estop { return String(localized: "E-stop is latched") }
        if robot.mode != "standing" { return String(localized: "Stand the robot up first") }
        if robot.perform != nil && !(robot.perform ?? "").isEmpty {
            return String(localized: "Wait for the current move")
        }
        return nil
    }

    private var heldPose: Bool {
        guard let limiter = model.brain?.robot?.limiter else { return false }
        return limiter.localizedCaseInsensitiveContains("move")
            || limiter.localizedCaseInsensitiveContains("pose")
    }

    private func isDisabled(_ move: MoveOption) -> Bool {
        if appMovesOff { return true }
        if blockReason != nil { return true }
        guard let moves = model.brain?.caps.moves else { return true }
        return !moves.contains(move.name)
    }

    private func hint(_ move: MoveOption) -> String {
        var parts: [String] = []
        if appMovesOff { parts.append(String(localized: "Moves from the app are switched off")) }
        if let reason = blockReason { parts.append(reason) }
        if !(model.brain?.caps.moves ?? []).contains(move.name) {
            parts.append(String(localized: "Move not available"))
        }
        if move.name == "offer_hand",
           model.events.contains(where: { $0.event.detail.contains("cannot reach its foot point") }) {
            parts.append(String(localized: "Set moves.offer_hand_ahead_m to 0.06 in robot.yaml"))
        }
        return parts.joined(separator: " ")
    }

    private func title(_ name: String) -> LocalizedStringKey {
        LocalizedStringKey(allMoves.first { $0.name == name }?.title ?? name)
    }

    private func symbol(_ name: String) -> String {
        UIImage(systemName: name) == nil ? "sparkles" : name
    }
}

struct MovesSheet: View {
    @Environment(\.dismiss) private var dismiss
    @Binding var showSettings: Bool

    var body: some View {
        NavigationStack {
            ScrollView {
                MovesPanel { showSettings = true }
                    .padding(20)
            }
            .background(Theme.background)
            .stopSide(id: "stop.moves")
            .navigationTitle("Moves")
            .navigationBarTitleDisplayMode(.inline)
            .sheetBar()
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }
                        .accessibilityIdentifier("closeMoves")
                }
            }
        }
    }
}

struct MovesSideCard: View {
    @Environment(AppModel.self) private var model
    @Binding var showMoves: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(model.moveSpeedText)
                .font(.footnote)
                .foregroundStyle(Theme.muted)
            Button("Open every move") { showMoves = true }
                .buttonStyle(.bordered)
                .accessibilityIdentifier("openMoves")
        }
    }
}
