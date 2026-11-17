import AVFoundation

/// Records the owner's voice while the Talk button is held: 16 kHz, mono, 16-bit PCM, at most
/// 30 seconds, handed over as a plain WAV for POST /v1/talk.
@MainActor
final class TalkRecorder {
    enum Permission { case granted, denied, undetermined }

    enum Failure: Error, LocalizedError {
        case couldNotStart
        case tooShort
        case unreadable

        var errorDescription: String? {
            switch self {
            case .couldNotStart: String(localized: "The microphone could not start.")
            case .tooShort: String(localized: "Hold the button a little longer while you speak.")
            case .unreadable: String(localized: "The recording could not be read. Try again.")
            }
        }
    }

    private var recorder: AVAudioRecorder?
    private var file: URL?
    private(set) var startedAt: Date?

    var isRecording: Bool { startedAt != nil }

    var permission: Permission {
        #if DEBUG
        if UITestFakes.isOn { return .granted }  // UI tests never meet the system prompt
        #endif
        switch AVAudioApplication.shared.recordPermission {
        case .granted: return .granted
        case .denied: return .denied
        default: return .undetermined
        }
    }

    func requestPermission() async -> Bool {
        #if DEBUG
        if UITestFakes.isOn { return true }
        #endif
        return await AVAudioApplication.requestRecordPermission()
    }

    func start() throws {
        #if DEBUG
        if UITestFakes.isOn {
            startedAt = Date()
            return
        }
        #endif
        let session = AVAudioSession.sharedInstance()
        // Speaker, not the earpiece: the spoken answer plays on the same session afterwards.
        try session.setCategory(.playAndRecord, mode: .default, options: [.defaultToSpeaker])
        try session.setActive(true)
        let url = FileManager.default.temporaryDirectory
            .appending(path: "talk-\(UUID().uuidString).wav")
        let settings: [String: Any] = [
            AVFormatIDKey: kAudioFormatLinearPCM,
            AVSampleRateKey: Double(Talk.sampleRate),
            AVNumberOfChannelsKey: 1,
            AVLinearPCMBitDepthKey: 16,
            AVLinearPCMIsFloatKey: false,
            AVLinearPCMIsBigEndianKey: false,
            AVLinearPCMIsNonInterleaved: false,
        ]
        let recorder = try AVAudioRecorder(url: url, settings: settings)
        guard recorder.record(forDuration: Talk.maxSeconds) else {  // the hard stop at 30 s
            try? FileManager.default.removeItem(at: url)
            throw Failure.couldNotStart
        }
        self.recorder = recorder
        file = url
        startedAt = Date()
    }

    /// Stops recording and returns the WAV.
    func finish() throws -> Data {
        let seconds = startedAt.map { Date().timeIntervalSince($0) } ?? 0
        defer { cleanUp() }
        #if DEBUG
        if UITestFakes.isOn { return Talk.wav(pcm: Data(count: Talk.sampleRate * 2)) }  // 1 s
        #endif
        recorder?.stop()
        guard seconds >= 0.3 else { throw Failure.tooShort }
        guard let file else { throw Failure.unreadable }
        return try Self.plainWAV(from: file)
    }

    func cancel() {
        recorder?.stop()
        cleanUp()
    }

    private func cleanUp() {
        if let file { try? FileManager.default.removeItem(at: file) }
        recorder = nil
        file = nil
        startedAt = nil
    }

    /// Reads the recording back as 16-bit samples and writes a plain 44-byte-header WAV, so the
    /// brain never meets the extra chunks Core Audio may add to the file.
    nonisolated static func plainWAV(from url: URL) throws -> Data {
        let audio = try AVAudioFile(forReading: url, commonFormat: .pcmFormatInt16, interleaved: true)
        let frames = AVAudioFrameCount(audio.length)
        guard frames > 0,
              let buffer = AVAudioPCMBuffer(pcmFormat: audio.processingFormat, frameCapacity: frames)
        else { throw Failure.unreadable }
        try audio.read(into: buffer)
        guard audio.processingFormat.channelCount == 1, let samples = buffer.int16ChannelData?[0]
        else { throw Failure.unreadable }
        let pcm = Data(bytes: samples, count: Int(buffer.frameLength) * 2)
        return Talk.wav(pcm: pcm, sampleRate: Int(audio.processingFormat.sampleRate))
    }
}

/// Reads talk replies aloud with the system voices.
@MainActor
final class Speaker {
    private let synthesizer = AVSpeechSynthesizer()

    func say(_ text: String) {
        let text = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        synthesizer.stopSpeaking(at: .immediate)
        let utterance = AVSpeechUtterance(string: text)
        utterance.voice = Self.voice(for: Talk.voiceLanguage(for: text))
        synthesizer.speak(utterance)
    }

    func stop() {
        synthesizer.stopSpeaking(at: .immediate)
    }

    private static func voice(for language: String) -> AVSpeechSynthesisVoice? {
        if let exact = AVSpeechSynthesisVoice(language: language) { return exact }
        let prefix = String(language.prefix(2))
        return AVSpeechSynthesisVoice.speechVoices().first { $0.language.hasPrefix(prefix) }
    }
}
