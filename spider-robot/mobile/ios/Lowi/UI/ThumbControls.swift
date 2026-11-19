import SwiftUI

/// Left thumb: forward, back and sideways. Reports a screen vector (x right, y down, length 1 at
/// the rim) while held and nil when released. It reports even when driving is off, so the
/// dead-man can tell a press that started while blocked and must be lifted first.
struct Joystick: View {
    var enabled: Bool
    var onChange: (CGVector?) -> Void
    @State private var knob: CGSize = .zero
    @State private var held = false
    // Resets when the touch ends or is cancelled. onEnded alone misses a cancelled touch (a sheet
    // appearing, Notification Center), and the app would keep driving with no finger down.
    @GestureState private var touching = false

    var body: some View {
        GeometryReader { geo in
            let side = min(geo.size.width, geo.size.height)
            let radius = side / 2
            let knobRadius = side * 0.2
            let travel = radius - knobRadius
            ZStack {
                Circle()
                    .fill(Theme.panel.opacity(0.75))
                    .overlay(Circle().stroke(held ? Theme.blue : Theme.panelLine, lineWidth: 2))
                Image(systemName: "chevron.up").offset(y: -radius * 0.72)
                Image(systemName: "chevron.down").offset(y: radius * 0.72)
                Image(systemName: "chevron.left").offset(x: -radius * 0.72)
                Image(systemName: "chevron.right").offset(x: radius * 0.72)
                Circle()
                    .fill(enabled ? Theme.blue : Theme.muted)
                    .frame(width: knobRadius * 2, height: knobRadius * 2)
                    .shadow(color: .black.opacity(0.4), radius: 4)
                    .offset(knob)
            }
            .foregroundStyle(Theme.muted)
            .frame(width: side, height: side)
            .contentShape(Circle())
            .gesture(
                DragGesture(minimumDistance: 0)
                    .updating($touching) { _, state, _ in state = true }
                    .onChanged { value in
                        var dx = value.location.x - radius
                        var dy = value.location.y - radius
                        let length = (dx * dx + dy * dy).squareRoot()
                        if length > travel {
                            dx *= travel / length
                            dy *= travel / length
                        }
                        held = true
                        knob = CGSize(width: dx, height: dy)
                        onChange(CGVector(dx: dx / travel, dy: dy / travel))
                    }
                    .onEnded { _ in release() }
            )
        }
        .aspectRatio(1, contentMode: .fit)
        .opacity(enabled ? 1 : 0.4)
        .environment(\.layoutDirection, .leftToRight)  // left on the stick is the robot's left
        .accessibilityElement()
        .accessibilityLabel(Text("Drive joystick"))
        .accessibilityHint(Text("Touch and hold, then slide to walk forward, back or sideways. With VoiceOver, drive with a keyboard or a game controller."))
        .accessibilityIdentifier("joystick")
        .onChange(of: touching) { _, now in if !now { release() } }
        .onDisappear { release() }
    }

    private func release() {
        guard held else { return }
        held = false
        withAnimation(.spring(duration: 0.2)) { knob = .zero }
        onChange(nil)
    }
}

/// Right thumb: turn left or right. Reports x from -1 (left edge) to 1 while held, nil after.
struct TurnControl: View {
    var enabled: Bool
    var onChange: (CGFloat?) -> Void
    @State private var offset: CGFloat = 0
    @State private var held = false
    @GestureState private var touching = false  // see Joystick

    var body: some View {
        GeometryReader { geo in
            let width = geo.size.width, height = geo.size.height
            let knob = height * 0.8
            let travel = (width - knob) / 2
            ZStack {
                Capsule()
                    .fill(Theme.panel.opacity(0.75))
                    .overlay(Capsule().stroke(held ? Theme.blue : Theme.panelLine, lineWidth: 2))
                HStack {
                    Image(systemName: "arrow.counterclockwise")
                    Spacer()
                    Image(systemName: "arrow.clockwise")
                }
                .padding(.horizontal, height * 0.3)
                .foregroundStyle(Theme.muted)
                Circle()
                    .fill(enabled ? Theme.blue : Theme.muted)
                    .frame(width: knob, height: knob)
                    .shadow(color: .black.opacity(0.4), radius: 4)
                    .offset(x: offset)
            }
            .contentShape(Capsule())
            .gesture(
                DragGesture(minimumDistance: 0)
                    .updating($touching) { _, state, _ in state = true }
                    .onChanged { value in
                        let x = min(max(value.location.x - width / 2, -travel), travel)
                        held = true
                        offset = x
                        onChange(travel > 0 ? x / travel : 0)
                    }
                    .onEnded { _ in release() }
            )
        }
        .aspectRatio(3, contentMode: .fit)
        .opacity(enabled ? 1 : 0.4)
        .environment(\.layoutDirection, .leftToRight)
        .accessibilityElement()
        .accessibilityLabel(Text("Turn control"))
        .accessibilityHint(Text("Touch and hold, then slide left or right to turn. With VoiceOver, use Q and E on a keyboard or the right stick of a game controller."))
        .accessibilityIdentifier("turn")
        .onChange(of: touching) { _, now in if !now { release() } }
        .onDisappear { release() }
    }

    private func release() {
        guard held else { return }
        held = false
        withAnimation(.spring(duration: 0.2)) { offset = 0 }
        onChange(nil)
    }
}
