import SwiftUI

/// STOP: on every screen, never disabled, fires the moment a finger touches it.
struct StopButton: View {
    var id = "stop"  // one per screen, so UI tests can tell the one in front
    @Environment(AppModel.self) private var model
    @ScaledMetric(relativeTo: .largeTitle) private var size: CGFloat = 92
    // GestureState goes back to false when a touch ends AND when the system cancels it (a sheet
    // appearing, Notification Center, a call). A plain @State cleared in onEnded can stay true
    // after a cancelled touch, and STOP would then ignore every later touch.
    @GestureState private var down = false

    var body: some View {
        let side = min(size, 140)
        Text("STOP")
            .font(.system(size: side * 0.25, weight: .heavy, design: .rounded))
            .minimumScaleFactor(0.5)
            .lineLimit(1)
            .foregroundStyle(.white)
            .frame(width: side, height: side)
            .background(Circle().fill(down ? Theme.stopFill.opacity(0.8) : Theme.stopFill))
            .overlay(Circle().stroke(.white, lineWidth: 3))
            .contentShape(Circle())
            .highPriorityGesture(
                DragGesture(minimumDistance: 0)  // reports the touch-down itself
                    .updating($down) { _, touching, _ in touching = true }
            )
            .onChange(of: down) { _, touching in
                if touching { model.pressStop() }  // once per touch, on the way down
            }
            .accessibilityElement()
            .accessibilityLabel(Text("Stop the robot"))
            .accessibilityAddTraits(.isButton)
            .accessibilityAction { model.pressStop() }
            .accessibilityIdentifier(id)
            #if DEBUG
            // UI tests read how many times STOP fired; release builds have no value here.
            .accessibilityValue(UITestFakes.isOn ? Text(verbatim: "\(model.stopPresses)") : Text(""))
            #endif
    }
}

/// STOP in a column at the right edge of a screen or sheet, in every language: the content lays
/// out beside it, never under it, at any text size, and the thumb finds it where it is on the drive
/// screen. The content itself still follows the layout direction.
struct StopSide: ViewModifier {
    var id: String
    @Environment(\.layoutDirection) private var direction

    func body(content: Content) -> some View {
        content
            .environment(\.layoutDirection, direction)
            .safeAreaInset(edge: .trailing, spacing: 8) { StopColumn(id: id) }
            .environment(\.layoutDirection, .leftToRight)
    }
}

extension View {
    func stopSide(id: String) -> some View {
        modifier(StopSide(id: id))
    }
}

/// STOP in its own column at the trailing edge of a sheet: the sheet's content lays out beside
/// it, never under it, even in a short landscape sheet on iPhone.
struct StopColumn: View {
    var id: String

    var body: some View {
        VStack {
            Spacer(minLength: 0)
            StopButton(id: id)
        }
        .padding(.trailing, 16)
        .padding(.bottom, 12)
    }
}

/// E-STOP: one tap latches it. Releasing is never one tap (see ConfirmView).
struct EStopButton: View {
    @Environment(AppModel.self) private var model

    var body: some View {
        Button {
            model.pressEstop()
        } label: {
            Text("E-STOP")
                .font(.caption.weight(.heavy))
                .foregroundStyle(Theme.red)
                .padding(.horizontal, 12)
                .padding(.vertical, 7)
                .background(Capsule().fill(Theme.red.opacity(0.15)))
                .overlay(Capsule().stroke(Theme.red, lineWidth: 1.5))
        }
        .buttonStyle(.plain)
        .accessibilityLabel(Text("Emergency stop"))
        .accessibilityHint(Text("Latches the E-stop. Releasing it needs a fresh photo and a long press."))
        .accessibilityIdentifier("estop")
    }
}
