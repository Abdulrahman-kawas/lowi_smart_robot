import CoreGraphics
import Foundation

/// Robot-frame drive request, each axis from -1 to 1. The brain scales it to the remote caps.
struct DriveInput: Equatable, Sendable {
    var x = 0.0     // forward
    var y = 0.0     // left
    var turn = 0.0  // counter-clockwise, to the left

    static let zero = DriveInput()

    var isZero: Bool { x == 0 && y == 0 && turn == 0 }
}

/// Thumb controls to a DriveInput.
///
/// Controls report screen vectors: x to the right, y down, length 1 at the edge of the control.
/// Screen up is the robot's forward and screen left is the robot's left, in every language: the
/// drive controls never mirror for right-to-left layouts.
enum DriveMapping {
    static let deadzone = 0.12
    static let exponent = 1.5  // finer control near the centre

    static func input(stick: CGVector?, turn: CGFloat?) -> DriveInput {
        var result = DriveInput.zero
        if let stick {
            let dx = Double(stick.dx), dy = Double(stick.dy)
            let length = (dx * dx + dy * dy).squareRoot()
            if length > 0 {
                let magnitude = shape(length)
                result.x = -dy / length * magnitude
                result.y = -dx / length * magnitude
            }
        }
        if let turn {
            let t = Double(turn)
            result.turn = t == 0 ? 0 : -(t / abs(t)) * shape(abs(t))
        }
        return result
    }

    /// 0 inside the dead zone, 1 at the edge and beyond, a gentle curve in between.
    static func shape(_ value: Double) -> Double {
        let v = min(max(value, 0), 1)
        guard v > deadzone else { return 0 }
        return pow((v - deadzone) / (1 - deadzone), exponent)
    }

    /// Keys or a controller pad: each axis -1, 0 or 1, full speed on that axis.
    static func input(forward: Int, left: Int, turnLeft: Int) -> DriveInput {
        var x = Double(forward.signum()), y = Double(left.signum())
        let length = (x * x + y * y).squareRoot()
        if length > 1 { x /= length; y /= length }
        return DriveInput(x: x, y: y, turn: Double(turnLeft.signum()))
    }
}
