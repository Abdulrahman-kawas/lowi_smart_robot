import SwiftUI

/// The robot from above: one wedge per LiDAR sector, front at the top, left on the left. A wedge
/// reaches as far as the nearest obstacle in it. The nearest obstacle overall is outlined.
struct LidarRadar: View {
    var scan: LidarScan?
    var range = 2.0  // metres to the outer ring; anything farther is drawn as free

    var body: some View {
        Canvas { context, size in
            let radius = min(size.width, size.height) / 2 - 14
            let centre = CGPoint(x: size.width / 2, y: size.height / 2)
            for metres in [0.5, 1.0, 2.0] where metres <= range {
                let r = radius * metres / range
                context.stroke(Path(ellipseIn: CGRect(x: centre.x - r, y: centre.y - r,
                                                      width: 2 * r, height: 2 * r)),
                               with: .color(Theme.panelLine), lineWidth: 1)
            }
            if let scan, !scan.sectorsM.isEmpty {
                let nearest = scan.sectorsM.indices.min { scan.sectorsM[$0] < scan.sectorsM[$1] }
                for (i, distance) in scan.sectorsM.enumerated() {
                    let free = distance >= range
                    let reach = radius * min(distance, range) / range
                    let wedge = Self.wedge(centre: centre, radius: reach, index: i,
                                           sectorDeg: scan.sectorDeg)
                    let color = Self.color(distance)
                    context.fill(wedge, with: .color(free ? Theme.blue.opacity(0.08)
                                                     : color.opacity(i == nearest ? 0.85 : 0.45)))
                    if i == nearest && !free {
                        context.stroke(wedge, with: .color(color), lineWidth: 2)
                    }
                }
                if let i = nearest, scan.sectorsM[i] < range {  // mark the nearest obstacle
                    let bearing = Double(i) * scan.sectorDeg * .pi / 180
                    let reach = radius * scan.sectorsM[i] / range
                    let tip = CGPoint(x: centre.x - reach * sin(bearing),
                                      y: centre.y - reach * cos(bearing))
                    let color = Self.color(scan.sectorsM[i])
                    context.fill(Path(ellipseIn: CGRect(x: tip.x - 5, y: tip.y - 5, width: 10, height: 10)),
                                 with: .color(color))
                    let label = Text("\(scan.sectorsM[i].formatted(.number.precision(.fractionLength(2)))) m")
                        .font(.caption.weight(.bold)).foregroundStyle(color)
                    let outward = CGPoint(x: -sin(bearing) * 26, y: -cos(bearing) * 26)
                    context.draw(label, at: CGPoint(x: tip.x + outward.x, y: tip.y + outward.y))
                }
            }
            // The robot, facing up.
            var body = Path()
            body.addRoundedRect(in: CGRect(x: centre.x - 9, y: centre.y - 12, width: 18, height: 24),
                                cornerSize: CGSize(width: 5, height: 5))
            context.fill(body, with: .color(Theme.text))
            var nose = Path()
            nose.move(to: CGPoint(x: centre.x, y: centre.y - 22))
            nose.addLine(to: CGPoint(x: centre.x - 6, y: centre.y - 13))
            nose.addLine(to: CGPoint(x: centre.x + 6, y: centre.y - 13))
            nose.closeSubpath()
            context.fill(nose, with: .color(Theme.green))
        }
        .aspectRatio(1, contentMode: .fit)
        .overlay(alignment: .top) {
            Text("front").font(.caption2).foregroundStyle(Theme.muted)
        }
        .overlay(alignment: .bottomTrailing) {
            Text("ring \(range.formatted(.number.precision(.fractionLength(0)))) m")
                .font(.caption2).foregroundStyle(Theme.muted)
        }
        .accessibilityElement()
        .accessibilityLabel(Text("LiDAR"))
        .accessibilityValue(Text(Self.summary(scan)))
        .accessibilityIdentifier("radar")
    }

    static func color(_ distance: Double) -> Color {
        distance < 0.3 ? Theme.red : distance < 0.6 ? Theme.amber : Theme.blue
    }

    /// Sector i covers bearings (i ± 0.5) × sectorDeg, counter-clockwise from straight ahead.
    static func wedge(centre: CGPoint, radius: CGFloat, index: Int, sectorDeg: Double) -> Path {
        var path = Path()
        path.move(to: centre)
        let from = (Double(index) - 0.5) * sectorDeg, to = (Double(index) + 0.5) * sectorDeg
        for step in 0...6 {
            let bearing = (from + (to - from) * Double(step) / 6) * .pi / 180
            path.addLine(to: CGPoint(x: centre.x - radius * sin(bearing),
                                     y: centre.y - radius * cos(bearing)))
        }
        path.closeSubpath()
        return path
    }

    /// "Nearest obstacle 0.42 m, front-left", or why there is nothing to say.
    static func summary(_ scan: LidarScan?) -> String {
        guard let scan else { return String(localized: "No LiDAR data") }
        guard scan.nearestM < 8 else { return String(localized: "Nothing seen nearby") }
        let distance = scan.nearestM.formatted(.number.precision(.fractionLength(2)))
        return String(localized: "Nearest obstacle \(distance) m, \(direction(scan.nearestBearingDeg))")
    }

    /// Bearing in degrees, 0 straight ahead and positive to the left, as eight compass words.
    static func direction(_ bearing: Double) -> String {
        let names = [
            String(localized: "front"), String(localized: "front-left"),
            String(localized: "left"), String(localized: "back-left"),
            String(localized: "back"), String(localized: "back-right"),
            String(localized: "right"), String(localized: "front-right"),
        ]
        let normalised = (bearing.truncatingRemainder(dividingBy: 360) + 360)
            .truncatingRemainder(dividingBy: 360)
        return names[Int((normalised + 22.5) / 45) % 8]
    }
}
