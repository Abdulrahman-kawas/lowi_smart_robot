import SwiftUI

/// Hold to talk with the robot. What it heard and its answer are shown, and read aloud when
/// "Speak answers" is on. Talking never moves the robot: a stop word makes the brain send STOP,
/// and that is all a spoken sentence can do.
struct TalkPanel: View {
    enum Phase: Equatable {
        case idle, listening, thinking
        case problem(String)
    }

    @Environment(AppModel.self) private var model
    @State private var recorder = TalkRecorder()
    @State private var phase = Phase.idle
    @State private var heard: String?
    @State private var reply: String?
    @State private var stopped = false
    @State private var limit: Task<Void, Never>?
    // Back to false when the touch ends AND when the system cancels it, like STOP's.
    @GestureState private var holding = false

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            talkButton
            status
            if let heard {
                VStack(alignment: .leading, spacing: 2) {
                    Text("You said")
                        .font(.caption)
                        .foregroundStyle(Theme.muted)
                    Text(heard)
                        .font(.callout)
                        .foregroundStyle(Theme.text)
                }
                .accessibilityElement(children: .combine)
                .accessibilityIdentifier("talkHeard")
            }
            if stopped {
                Label("The robot was stopped.", systemImage: "octagon.fill")
                    .font(.callout.weight(.semibold))
                    .foregroundStyle(Theme.red)
                    .accessibilityIdentifier("talkStopped")
            }
            if let reply, !reply.isEmpty {
                Text(reply)
                    .font(.callout)
                    .foregroundStyle(Theme.text)
                    .textSelection(.enabled)
                    .accessibilityIdentifier("talkReply")
            }
        }
        .onDisappear {
            limit?.cancel()
            if recorder.isRecording { recorder.cancel() }
        }
    }

    private var talkButton: some View {
        let listening = phase == .listening
        return HStack(spacing: 10) {
            if phase == .thinking {
                ProgressView().controlSize(.small).tint(Theme.background)
            } else {
                Image(systemName: listening ? "waveform" : "mic.fill")
                    .font(.title3)
            }
            Text(listening ? "Release to send" : phase == .thinking ? "Thinking…" : "Hold to talk")
                .font(.headline)
                .multilineTextAlignment(.center)
        }
        .foregroundStyle(Theme.background)  // 7:1 on blue, 9:1 on green
        .frame(maxWidth: .infinity, minHeight: 56)
        .padding(.horizontal, 12)
        .background(RoundedRectangle(cornerRadius: 14).fill(listening ? Theme.green : Theme.blue))
        .contentShape(RoundedRectangle(cornerRadius: 14))
        .highPriorityGesture(
            DragGesture(minimumDistance: 0)  // reports the touch-down itself
                .updating($holding) { _, touching, _ in touching = true }
        )
        .onChange(of: holding) { _, down in
            if down { begin() } else { end() }
        }
        .allowsHitTesting(phase != .thinking)
        .accessibilityElement()
        .accessibilityLabel(Text(listening ? "Send what you said" : "Hold to talk"))
        .accessibilityHint(Text("Hold while you speak and release to send. With VoiceOver, double-tap to start and double-tap again to send."))
        .accessibilityAddTraits(.isButton)
        .accessibilityAction {
            if phase == .listening { end() } else { begin() }
        }
        .accessibilityIdentifier("talkButton")
    }

    @ViewBuilder
    private var status: some View {
        switch phase {
        case .idle:
            Text("Hold the button while you speak. Talking never moves the robot; say “stop” to stop it.")
                .font(.footnote)
                .foregroundStyle(Theme.muted)
        case .listening:
            Label("Listening… release to send", systemImage: "waveform")
                .font(.footnote.weight(.semibold))
                .foregroundStyle(Theme.green)
        case .thinking:
            Text("Thinking…")
                .font(.footnote)
                .foregroundStyle(Theme.muted)
        case .problem(let text):
            Label(text, systemImage: "exclamationmark.triangle.fill")
                .font(.footnote)
                .foregroundStyle(Theme.amber)
                .accessibilityIdentifier("talkProblem")
        }
    }

    private func begin() {
        guard phase != .thinking, !recorder.isRecording, model.isPaired else { return }
        switch recorder.permission {
        case .denied:
            fail(String(localized: "Microphone access is off. Turn it on for Lowi in iOS Settings."))
            return
        case .undetermined:  // this touch only asks; the next one records
            Task {
                let granted = await recorder.requestPermission()
                phase = granted ? .problem(String(localized: "Allow the microphone, then hold the button again."))
                    : .problem(String(localized: "Microphone access is off. Turn it on for Lowi in iOS Settings."))
            }
            return
        case .granted:
            break
        }
        do {
            try recorder.start()
        } catch {
            fail(TalkRecorder.Failure.couldNotStart.localizedDescription)
            return
        }
        model.speaker.stop()  // do not record the previous answer
        stopped = false
        phase = .listening
        limit = Task {
            try? await Task.sleep(for: .seconds(Talk.maxSeconds))
            if !Task.isCancelled { end() }  // the recorder stops itself at the limit too
        }
    }

    private func end() {
        limit?.cancel()
        limit = nil
        guard recorder.isRecording else { return }
        let wav: Data
        do {
            wav = try recorder.finish()
        } catch {
            fail(error.localizedDescription)
            return
        }
        phase = .thinking
        Task {
            do {
                let answer = try await model.talk(wav: wav)
                heard = answer.heardNothing ? nil : answer.heard
                reply = answer.reply
                stopped = answer.stoppedRobot
                if answer.heardNothing && answer.reply.isEmpty {
                    phase = .problem(String(localized: "I did not hear anything. Hold the button and speak."))
                } else {
                    phase = .idle
                }
            } catch {
                fail(Talk.problem(error))
            }
        }
    }

    private func fail(_ text: String) {
        phase = .problem(text)
        if model.hapticsOn { Haptics.refusal() }
    }
}

/// iPhone: the talk panel as its own screen, with its own STOP.
struct TalkSheet: View {
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ScrollView {
                TalkPanel().padding(20)
            }
            .background(Theme.background)
            .stopSide(id: "stop.talk")
            .navigationTitle("Talk")
            .navigationBarTitleDisplayMode(.inline)
            .sheetBar()
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }
                        .accessibilityIdentifier("closeTalk")
                }
            }
        }
    }
}
