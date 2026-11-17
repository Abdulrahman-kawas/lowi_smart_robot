import Foundation
import Testing
@testable import Lowi

struct TalkTests {
    @Test func replyDecodes() throws {
        let json = #"{"heard":"شو قدامك؟","reply":"في علبة قدامي.","action":"answer","provider":"liquid","elapsed_ms":1840.5}"#
        let reply = try ServerMessage.decoder.decode(TalkReply.self, from: Data(json.utf8))
        #expect(reply == TalkReply(heard: "شو قدامك؟", reply: "في علبة قدامي.", action: "answer",
                                   provider: "liquid", elapsedMs: 1840.5))
        #expect(!reply.stoppedRobot && !reply.heardNothing)
    }

    @Test func stopWordsReportTheStopAndSilenceReportsNothingHeard() throws {
        for action in ["stop", "estop"] {
            let json = #"{"heard":"قف","reply":"وقفت.","action":"\#(action)","provider":"stopwords","elapsed_ms":120}"#
            let reply = try ServerMessage.decoder.decode(TalkReply.self, from: Data(json.utf8))
            #expect(reply.stoppedRobot && !reply.heardNothing)
        }
        let silent = #"{"heard":"","reply":"","action":"no_speech","provider":"whisper-small","elapsed_ms":300}"#
        let reply = try ServerMessage.decoder.decode(TalkReply.self, from: Data(silent.utf8))
        #expect(reply.heardNothing && !reply.stoppedRobot)
    }

    @Test func wavIsMono16Bit16kHz() {
        let pcm = Data([1, 0, 2, 0, 3, 0])
        let wav = Talk.wav(pcm: pcm)
        func u32(_ at: Int) -> UInt32 { wav[at..<at + 4].enumerated().reduce(0) { $0 | UInt32($1.element) << (8 * $1.offset) } }
        func u16(_ at: Int) -> UInt16 { UInt16(wav[at]) | UInt16(wav[at + 1]) << 8 }
        #expect(wav.count == 44 + pcm.count)
        #expect(String(decoding: wav[0..<4], as: UTF8.self) == "RIFF" && u32(4) == UInt32(36 + pcm.count))
        #expect(String(decoding: wav[8..<16], as: UTF8.self) == "WAVEfmt ")
        #expect(u32(16) == 16 && u16(20) == 1 && u16(22) == 1)    // PCM, mono
        #expect(u32(24) == 16_000 && u32(28) == 32_000)           // 16 kHz, bytes per second
        #expect(u16(32) == 2 && u16(34) == 16)                    // block align, 16-bit
        #expect(String(decoding: wav[36..<40], as: UTF8.self) == "data" && u32(40) == UInt32(pcm.count))
        #expect(wav.suffix(pcm.count) == pcm)
    }

    @Test func requestBodyCarriesTheWAVAsBase64() throws {
        let wav = Talk.wav(pcm: Data(count: 32))
        let body = Talk.body(wav: wav)
        #expect(body["mime"] as? String == "audio/wav")
        #expect(Data(base64Encoded: body["audio_b64"] as? String ?? "") == wav)
        #expect(JSONSerialization.isValidJSONObject(body))
    }

    @Test func talkPostsToTheBrainWithTheToken() async throws {
        let session = URLSession(configuration: {
            let config = URLSessionConfiguration.ephemeral
            config.protocolClasses = [TalkStub.self]
            return config
        }())
        let api = APIClient(address: BrainAddress("brain.example.ts.net")!, token: "tok-1", session: session)
        let wav = Talk.wav(pcm: Data(count: 64))
        let reply = try await api.talk(wav: wav)
        #expect(reply.reply == "An orange box." && reply.provider == "stub")
        let seen = try #require(TalkStub.lastRequest)
        #expect(seen.method == "POST" && seen.path == "/v1/talk")
        #expect(seen.authorization == "Bearer tok-1")
        let json = try #require(try JSONSerialization.jsonObject(with: seen.body) as? [String: String])
        #expect(json["mime"] == "audio/wav" && Data(base64Encoded: json["audio_b64"] ?? "") == wav)
    }

    @Test func refusalsAreExplained() {
        #expect(Talk.problem(APIError.refused(status: 429, detail: "busy"))
                == String(localized: "The robot is still answering another question. Try again in a moment."))
        #expect(Talk.problem(APIError.refused(status: 413, detail: "too long"))
                == String(localized: "That was too long. Keep it under 30 seconds."))
        #expect(Talk.problem(APIError.refused(status: 503, detail: "no model configured"))
                .contains("no model configured"))
        #expect(Talk.problem(APIError.unreachable("offline")) == "offline")
    }

    @Test func theVoiceFollowsTheScript() {
        #expect(Talk.voiceLanguage(for: "شو في قدامك؟") == "ar-SA")
        #expect(Talk.voiceLanguage(for: "前に何がありますか？") == "ja-JP")
        #expect(Talk.voiceLanguage(for: "What is in front of you?") == "en-US")
        #expect(Talk.voiceLanguage(for: "في box قدامي") == "ar-SA")
    }
}

/// Answers POST /v1/talk and remembers what it was sent.
final class TalkStub: URLProtocol {
    struct Seen: Sendable {
        var method: String
        var path: String
        var authorization: String?
        var body: Data
    }

    nonisolated(unsafe) static var lastRequest: Seen?

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        Self.lastRequest = Seen(method: request.httpMethod ?? "", path: request.url?.path() ?? "",
                                authorization: request.value(forHTTPHeaderField: "Authorization"),
                                body: request.httpBody ?? Self.read(request.httpBodyStream))
        let body = #"{"heard":"what is that","reply":"An orange box.","action":"answer","provider":"stub","elapsed_ms":12}"#
        let response = HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: "HTTP/1.1",
                                       headerFields: ["Content-Type": "application/json"])!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: Data(body.utf8))
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}

    private static func read(_ stream: InputStream?) -> Data {
        guard let stream else { return Data() }
        stream.open()
        defer { stream.close() }
        var data = Data()
        var buffer = [UInt8](repeating: 0, count: 4096)
        while stream.hasBytesAvailable {
            let count = stream.read(&buffer, maxLength: buffer.count)
            if count <= 0 { break }
            data.append(buffer, count: count)
        }
        return data
    }
}
