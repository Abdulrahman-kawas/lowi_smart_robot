import SwiftUI

struct SettingsView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.dismiss) private var dismiss
    @Environment(\.openURL) private var openURL
    @State private var confirmUnpair = false

    var body: some View {
        @Bindable var model = model
        NavigationStack {
            ZStack(alignment: .bottomTrailing) {
                Form {
                    Section("This device") {
                        LabeledContent("Name", value: model.deviceName)
                        LabeledContent("Brain", value: model.address?.base.host() ?? "-")
                        if let robot = model.robotId {
                            LabeledContent("Robot", value: robot)
                        }
                    }
                    Section {
                        Toggle("Haptics", isOn: $model.hapticsOn)
                            .accessibilityIdentifier("hapticsToggle")
                        Button("Language") {
                            if let url = URL(string: UIApplication.openSettingsURLString) {
                                openURL(url)
                            }
                        }
                    } footer: {
                        Text("The app follows the language you choose for it in iOS Settings.")
                    }
                    Section {
                        Button("Unpair this device", role: .destructive) { confirmUnpair = true }
                            .accessibilityIdentifier("unpair")
                    } footer: {
                        Text("Forgets the token on this device. To cut it off on the server as well, run `spider-brain devices revoke \"\(model.deviceName)\"`.")
                    }
                }
                .scrollContentBackground(.hidden)
                .background(Theme.background)
                StopButton()
                    .padding(20)
            }
            .navigationTitle("Settings")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }
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
}
