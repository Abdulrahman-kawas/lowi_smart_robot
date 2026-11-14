import SwiftUI

/// STOP: on every screen, never disabled, fires the moment a finger touches it.
struct StopButton: View {
    @Environment(AppModel.self) private var model
    @ScaledMetric(relativeTo: .largeTitle) private var size: CGFloat = 92
    @State private var down = false

    var body: some View {
        let side = min(size, 140)
        Text("STOP")
            .font(.system(size: side * 0.25, weight: .heavy, design: .rounded))
            .minimumScaleFactor(0.5)
            .lineLimit(1)
            .foregroundStyle(.white)
            .frame(width: side, height: side)
            .background(Circle().fill(down ? Theme.red.opacity(0.75) : Theme.red))
            .overlay(Circle().stroke(.white.opacity(0.9), lineWidth: 3))
            .shadow(color: Theme.red.opacity(0.5), radius: 10)
            .contentShape(Circle())
            .highPriorityGesture(
                DragGesture(minimumDistance: 0)  // reports the touch-down itself
                    .onChanged { _ in
                        guard !down else { return }
                        down = true
                        model.pressStop()
                    }
                    .onEnded { _ in down = false }
            )
            .accessibilityElement()
            .accessibilityLabel(Text("Stop the robot"))
            .accessibilityAddTraits(.isButton)
            .accessibilityAction { model.pressStop() }
            .accessibilityIdentifier("stop")
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
