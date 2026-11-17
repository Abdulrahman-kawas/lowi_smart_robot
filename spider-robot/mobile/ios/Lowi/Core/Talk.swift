import Foundation

/// What the brain answers to POST /v1/talk. Talking never moves the robot: "stop" and "estop"
/// only report that the brain already stopped it because it heard a stop word.
struct TalkReply: Decodable, Sendable, Equatable {
    var heard: String
    var reply: String
    var action: String  // answer, stop, estop, no_speech
    var provider: String
    var elapsedMs: Double

    var stoppedRobot: Bool { action == "stop" || action == "estop" }
    var heardNothing: Bool { action == "no_speech" }
}

/// The talk contract with the brain: the request body, the audio format and the error texts.
enum Talk {
    static let sampleRate = 16_000
    static let maxSeconds: TimeInterval = 30

    /// The JSON body of POST /v1/talk.
    static func body(wav: Data) -> [String: Any] {
        ["audio_b64": wav.base64EncodedString(), "mime": "audio/wav"]
    }

    /// A plain WAV with a 44-byte header: RIFF/WAVE, linear PCM, mono, 16-bit little-endian.
    static func wav(pcm: Data, sampleRate: Int = sampleRate) -> Data {
        var out = Data(capacity: 44 + pcm.count)
        func text(_ value: String) { out.append(contentsOf: Array(value.utf8)) }
        func u32(_ value: UInt32) { withUnsafeBytes(of: value.littleEndian) { out.append(contentsOf: $0) } }
        func u16(_ value: UInt16) { withUnsafeBytes(of: value.littleEndian) { out.append(contentsOf: $0) } }
        text("RIFF"); u32(UInt32(36 + pcm.count)); text("WAVE")
        text("fmt "); u32(16); u16(1); u16(1)                 // PCM, one channel
        u32(UInt32(sampleRate)); u32(UInt32(sampleRate * 2))  // sample rate, bytes per second
        u16(2); u16(16)                                       // bytes per frame, bits per sample
        text("data"); u32(UInt32(pcm.count))
        out.append(pcm)
        return out
    }

    /// Why a talk failed, in words for the owner.
    static func problem(_ error: Error) -> String {
        guard case APIError.refused(let status, let detail) = error else {
            return error.localizedDescription
        }
        switch status {
        case 429:
            return String(localized: "The robot is still answering another question. Try again in a moment.")
        case 413:
            return String(localized: "That was too long. Keep it under 30 seconds.")
        case 400:
            return String(localized: "The recording could not be read. Try again.")
        case 503:
            return detail.isEmpty ? String(localized: "No answer is available right now.")
                : String(localized: "No answer right now: \(detail)")
        default:
            return error.localizedDescription
        }
    }

    /// The voice for a reply: Arabic letters read in Arabic, kana or kanji in Japanese, the rest
    /// in English. Mixed text goes with the script that has more letters.
    static func voiceLanguage(for text: String) -> String {
        var arabic = 0, japanese = 0
        for scalar in text.unicodeScalars {
            switch scalar.value {
            case 0x0600...0x06FF, 0x0750...0x077F, 0x08A0...0x08FF, 0xFB50...0xFDFF, 0xFE70...0xFEFF:
                arabic += 1
            case 0x3040...0x30FF, 0x4E00...0x9FFF, 0xFF66...0xFF9F:
                japanese += 1
            default:
                break
            }
        }
        if arabic == 0 && japanese == 0 { return "en-US" }
        return arabic >= japanese ? "ar-SA" : "ja-JP"
    }
}
