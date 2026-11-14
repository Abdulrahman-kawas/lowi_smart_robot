import UIKit

/// A firm thump on STOP and E-stop, a warning buzz on every refusal.
@MainActor
enum Haptics {
    static func stop() {
        UIImpactFeedbackGenerator(style: .heavy).impactOccurred()
    }

    static func refusal() {
        UINotificationFeedbackGenerator().notificationOccurred(.warning)
    }

    static func success() {
        UINotificationFeedbackGenerator().notificationOccurred(.success)
    }
}
