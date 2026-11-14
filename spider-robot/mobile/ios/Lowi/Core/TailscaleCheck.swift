import Darwin
import Foundation

/// iOS gives apps no way to ask the Tailscale app whether it is on, but its VPN interface gives
/// this device an address in 100.64.0.0/10. No such address means Tailscale is off here.
enum TailscaleCheck {
    static func hasTailnetAddress() -> Bool {
        var first: UnsafeMutablePointer<ifaddrs>?
        guard getifaddrs(&first) == 0 else { return false }
        defer { freeifaddrs(first) }
        var cursor = first
        while let entry = cursor {
            defer { cursor = entry.pointee.ifa_next }
            guard let address = entry.pointee.ifa_addr,
                  address.pointee.sa_family == UInt8(AF_INET) else { continue }
            let ip = address.withMemoryRebound(to: sockaddr_in.self, capacity: 1) {
                UInt32(bigEndian: $0.pointee.sin_addr.s_addr)
            }
            if isTailnet(ip) { return true }
        }
        return false
    }

    /// 100.64.0.0/10, the shared address space Tailscale uses.
    static func isTailnet(_ ip: UInt32) -> Bool { ip & 0xFFC0_0000 == 0x6440_0000 }
}
