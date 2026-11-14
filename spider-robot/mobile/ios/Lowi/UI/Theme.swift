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

/// A small rounded label in the top bar.
struct Chip<Content: View>: View {
    var tint: Color = Theme.muted
    @ViewBuilder var content: Content

    var body: some View {
        HStack(spacing: 6) { content }
            .lineLimit(1)
            .fixedSize()
            .font(.caption.weight(.semibold).monospacedDigit())
            .foregroundStyle(tint)
            .padding(.horizontal, 10)
            .padding(.vertical, 6)
            .background(Capsule().fill(Theme.panel.opacity(0.85)))
            .overlay(Capsule().stroke(Theme.panelLine, lineWidth: 1))
    }
}
