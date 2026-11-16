import SwiftUI

/// Take a photo, optionally with a question for the vision model on the server. The answer is
/// shown only: like every vision answer, it never moves the robot.
struct PhotoPanel: View {
    @Environment(AppModel.self) private var model
    @State private var question = ""
    @State private var image: UIImage?
    @State private var answer: String?
    @State private var problem: String?
    @State private var taking = false
    @FocusState private var editing: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            TextField("Ask about the photo (optional)", text: $question, axis: .vertical)
                .lineLimit(1...3)
                .focused($editing)
                .submitLabel(.send)
                .onSubmit(take)
                .fieldStyle()
                .accessibilityIdentifier("photoQuestion")
            Button(action: take) {
                HStack {
                    if taking { ProgressView().controlSize(.small) }
                    Image(systemName: "camera.fill")
                    Text(question.isEmpty ? "Take photo" : "Take photo and ask")
                }
                .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .disabled(taking || !model.isPaired)
            .accessibilityIdentifier("takePhoto")
            if let image {
                Image(uiImage: image)
                    .resizable()
                    .scaledToFit()
                    .clipShape(RoundedRectangle(cornerRadius: 10))
                    .accessibilityLabel(Text("Photo from the robot"))
            }
            if let answer {
                Text(answer)
                    .font(.callout)
                    .foregroundStyle(Theme.text)
                    .textSelection(.enabled)
                    .accessibilityIdentifier("photoAnswer")
            }
            if let problem {
                Label(problem, systemImage: "exclamationmark.triangle.fill")
                    .font(.footnote)
                    .foregroundStyle(Theme.amber)
            }
        }
        .onChange(of: editing) { _, now in model.textEditing = now }
    }

    private func take() {
        guard !taking else { return }
        editing = false
        taking = true
        problem = nil
        let asked = question.trimmingCharacters(in: .whitespacesAndNewlines)
        Task {
            do {
                let result = try await model.takePhoto(question: asked.isEmpty ? nil : asked)
                image = Data(base64Encoded: result.frameJpeg).flatMap(UIImage.init(data:))
                answer = result.answer
                if let error = result.visionError, !asked.isEmpty {
                    problem = String(localized: "No answer from vision: \(error)")
                }
            } catch {
                problem = error.localizedDescription
                if model.hapticsOn { Haptics.refusal() }
            }
            taking = false
        }
    }
}

/// iPhone: the photo panel as its own screen, with its own STOP.
struct PhotoSheet: View {
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ScrollView {
                PhotoPanel().padding(20)
            }
            .background(Theme.background)
            .safeAreaInset(edge: .trailing, spacing: 8) { StopColumn(id: "stop.photo") }
            .navigationTitle("Photo")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }
                        .accessibilityIdentifier("closePhoto")
                }
            }
        }
    }
}
