import SwiftUI

/// The colours of docs/images: dark background, blue for controls, green for live, amber for
/// caution, red for stop.
enum Theme {
    static let background = Color(hex: 0x0D1117)
    static let panel = Color(hex: 0x161D27)
    static let panelLine = Color(hex: 0x2A3442)
    static let blue = Color(hex: 0x4EA1FF)
    static let green = Color(hex: 0x3ECF8E)
    static let amber = Color(hex: 0xFFB547)
    static let red = Color(hex: 0xFF5D5D)
    static let stopFill = Color(hex: 0xC62828)  // white STOP text on it reaches 5.6:1
    static let text = Color(hex: 0xE8EDF3)
    static let muted = Color(hex: 0x9AA5B4)
}

extension Color {
    init(hex: UInt32) {
        self.init(.sRGB,
                  red: Double((hex >> 16) & 0xFF) / 255,
                  green: Double((hex >> 8) & 0xFF) / 255,
                  blue: Double(hex & 0xFF) / 255)
    }
}

extension View {
    /// A solid dark navigation bar on sheets: the title keeps its contrast whatever is behind it.
    func sheetBar() -> some View {
        toolbarBackground(Theme.panel, for: .navigationBar)
            .toolbarBackground(.visible, for: .navigationBar)
            .toolbarColorScheme(.dark, for: .navigationBar)
    }
}

/// A small rounded label in the top bar.
struct Chip<Content: View>: View {
    var tint: Color = Theme.muted
    var wraps = false  // long text (the limiter reason) wraps to two lines instead of running off
    @ViewBuilder var content: Content

    var body: some View {
        HStack(spacing: 6) { content }
            .lineLimit(wraps ? 2 : 1)
            .fixedSize(horizontal: !wraps, vertical: true)
            .font(.caption.weight(.semibold).monospacedDigit())
            .foregroundStyle(tint)
            .padding(.horizontal, 10)
            .padding(.vertical, 6)
            .background(Capsule().fill(Theme.panel))  // solid: text over a bright frame stays legible
            .overlay(Capsule().stroke(Theme.panelLine, lineWidth: 1))
    }
}
