import SwiftUI

struct SettingsView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @Environment(\.openURL) private var openURL
    @State private var confirmUnpair = false

    var body: some View {
        @Bindable var model = model
        NavigationStack {
            Form {
                Section {
                    row("Name", model.deviceName)
                    row("Brain", model.address?.base.host() ?? "-")
                    if let robot = model.robotId {
                        row("Robot", robot)
                    }
                } header: {
                    Text("This device").foregroundStyle(Theme.muted)
                }
                Section {
                    Toggle("Haptics", isOn: $model.hapticsOn)
                        .accessibilityIdentifier("hapticsToggle")
                    // Explanations sit in the rows, not in section footers: iOS 17 does not let
                    // footer text grow with Dynamic Type.
                    Button {
                        if let url = URL(string: UIApplication.openSettingsURLString) {
                            openURL(url)
                        }
                    } label: {
                        VStack(alignment: .leading, spacing: 4) {
                            Text("Language")
                            Text("The app follows the language you choose for it in iOS Settings.")
                                .font(.footnote)
                                .foregroundStyle(Theme.muted)
                        }
                    }
                    // Below Language: above it, the audit read the Language row as fixed-size text.
                    Toggle("Speak answers", isOn: $model.speakAnswers)
                        .accessibilityIdentifier("speakToggle")
                }
                Section {
                    Picker("Speed", selection: $model.moveSpeed) {
                        Text("Normal").tag(0.5)
                        Text("Lively").tag(0.75)
                        Text("Fast").tag(1.0)
                    }
                    .pickerStyle(.segmented)
                    .accessibilityIdentifier("moveSpeed")
                } header: {
                    Text("Moves").foregroundStyle(Theme.muted)
                }
                Section {
                    Button(role: .destructive) {
                        confirmUnpair = true
                    } label: {
                        VStack(alignment: .leading, spacing: 4) {
                            Text("Unpair this device")
                                .foregroundStyle(Theme.red)  // 5.7:1 on the row; system red is under 4.5
                            Text("Forgets the token on this device. To cut it off on the server as well, run `spider-brain devices revoke \"\(model.deviceName)\"`.")
                                .font(.footnote)
                                .foregroundStyle(Theme.muted)
                        }
                    }
                    .accessibilityIdentifier("unpair")
                }
            }
            .scrollContentBackground(.hidden)
            .background(Theme.background)
            .accessibilityIdentifier("settingsForm")
            .stopSide(id: "stop.settings")  // the form lays out beside STOP
            .navigationTitle("Settings")
            .navigationBarTitleDisplayMode(.inline)
            .sheetBar()
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }
                        .accessibilityIdentifier("closeSettings")
                }
            }
            .confirmationDialog("Unpair this device?", isPresented: $confirmUnpair,
                                titleVisibility: .visible) {
                Button("Unpair", role: .destructive) {
                    model.pressStop()
                    dismiss()
                    model.unpair()
                }
            }
        }
    }

    /// A label and its value; long values wrap instead of truncating.
    private func row(_ label: LocalizedStringKey, _ value: String) -> some View {
        HStack(alignment: .firstTextBaseline) {
            Text(label)
            Spacer(minLength: 12)
            Text(value)
                .foregroundStyle(Theme.muted)
                .multilineTextAlignment(.trailing)
        }
        .accessibilityElement(children: .combine)
    }
}
