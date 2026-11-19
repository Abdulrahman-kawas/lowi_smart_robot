import SwiftUI

/// The fresh frame the gateway bound the challenge to, what will happen, and a long press.
/// Releasing an E-stop or waking a limp robot is never one tap.
struct ConfirmView: View {
    @Environment(AppModel.self) private var model
    var prompt: ConfirmPrompt
    @State private var width: CGFloat = 800

    var body: some View {
        TimelineView(.periodic(from: .now, by: 0.5)) { _ in
            let left = max(0, prompt.expiresAt - model.clock())
            let age = prompt.photoAge(at: model.clock())
            Group {
                    if width >= 520 {
                        // The photo takes the space that is left; the question and the button
                        // are always on screen next to it.
                        HStack(alignment: .top, spacing: 24) {
                            photo(age: age)
                                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
                            ScrollView {
                                details(left: left)
                                    .padding(.bottom, 20)
                            }
                            .frame(width: min(340, width / 2))
                        }
                    } else {
                        ScrollView {
                            VStack(alignment: .leading, spacing: 18) {
                                photo(age: age).frame(maxHeight: 280)
                                details(left: left)
                            }
                            .padding(.bottom, 20)
                        }
                    }
                }
                .padding(.horizontal, 24)
                .padding(.top, 16)
                .onGeometryChange(for: CGFloat.self) { $0.size.width } action: { width = $0 }
                .stopSide(id: "stop.confirm")
                .background(Theme.background.ignoresSafeArea())
        }
    }

    private func photo(age: TimeInterval) -> some View {
        let caption = Chip(tint: Theme.text, wraps: true) {
            Image(systemName: "camera.fill")
            if age < 1 {
                Text("Photo taken just now")
            } else {
                Text("Photo taken \(Int(age)) s ago")
            }
        }
        return Group {
            if let image = prompt.image {
                Image(uiImage: image)
                    .resizable()
                    .scaledToFit()
                    .clipShape(RoundedRectangle(cornerRadius: 12))
                    .overlay(alignment: .bottomLeading) {
                        caption
                            .dynamicTypeSize(...DynamicTypeSize.accessibility1)
                            .padding(8)
                    }
                    .accessibilityElement(children: .combine)
                    .accessibilityLabel(Text("Photo the robot took just now"))
            } else {
                caption
            }
        }
        .frame(maxWidth: 720, maxHeight: .infinity, alignment: .top)
    }

    private func details(left: TimeInterval) -> some View {
        let release = prompt.action == "estop_release"
        return VStack(alignment: .leading, spacing: 14) {
            Text(release ? "Release the E-stop?" : "Stand the robot up?")
                .font(.title.weight(.bold))
                .foregroundStyle(Theme.text)
            Text(release
                 ? "The robot can move again once it is released. Look at the photo: is the area around it clear, and is nobody touching it?"
                 : "The robot is limp and will push itself up on its legs. Look at the photo: is the area around it clear, and is nobody touching it?")
                .font(.body)
                .foregroundStyle(Theme.text)
                .fixedSize(horizontal: false, vertical: true)
            Text("This confirmation works once and expires in \(Int(left.rounded(.up))) s.")
                .font(.footnote)
                .foregroundStyle(left < 5 ? Theme.amber : Theme.muted)
            HoldToConfirm(title: release ? "Hold to release" : "Hold to stand up",
                          enabled: left > 0) {
                Task { await model.answer(prompt, approved: true) }
            }
            Button("Cancel", role: .cancel) {
                Task { await model.answer(prompt, approved: false) }
            }
            .buttonStyle(.bordered)
            .accessibilityIdentifier("cancelConfirm")
        }
        .frame(maxWidth: 420, alignment: .leading)
    }
}

/// Fills while pressed; fires only after the full duration. Lifting early cancels.
struct HoldToConfirm: View {
    var title: LocalizedStringKey
    var duration: Double = 1.5
    var enabled = true
    var action: () -> Void
    @State private var progress = 0.0

    private func label(_ color: Color) -> some View {
        Text(title).font(.headline).foregroundStyle(color)
    }

    var body: some View {
        ZStack {
            // Amber text on the empty track, black text where the fill has reached.
            Capsule().fill(Theme.panel)
            Capsule().stroke(Theme.amber, lineWidth: 2)
            label(Theme.amber)
            ZStack {
                Capsule().fill(Theme.amber)
                label(.black)
            }
            .mask(alignment: .leading) {
                GeometryReader { geo in
                    Rectangle().frame(width: geo.size.width * progress)
                }
            }
        }
        .frame(maxWidth: .infinity, minHeight: 54)
            .opacity(enabled ? 1 : 0.4)
            .contentShape(Capsule())
            .onLongPressGesture(minimumDuration: duration, maximumDistance: 30) {
                guard enabled else { return }
                Haptics.success()
                action()
            } onPressingChanged: { pressing in
                withAnimation(pressing ? .linear(duration: duration) : .easeOut(duration: 0.2)) {
                    progress = pressing && enabled ? 1 : 0
                }
            }
            .accessibilityElement()
            .accessibilityLabel(Text(title))
            .accessibilityHint(Text("Double-tap and hold until it fills."))
            .accessibilityAddTraits(.isButton)
            .accessibilityIdentifier("holdToConfirm")
    }
}
