import SwiftUI

@main
struct LowiApp: App {
    @State private var model = AppModel(defaults: LowiApp.defaults)

    /// UI tests keep their fake address and name out of the real settings.
    private static var defaults: UserDefaults {
        #if DEBUG
        if UITestFakes.isOn { return UserDefaults(suiteName: "app.lowi.uitests") ?? .standard }
        #endif
        return .standard
    }

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(model)
                .preferredColorScheme(.dark)
                .tint(Theme.blue)
        }
    }
}

struct RootView: View {
    @Environment(AppModel.self) private var model
    @Environment(\.scenePhase) private var phase

    var body: some View {
        @Bindable var model = model
        ZStack {
            Theme.background.ignoresSafeArea()
            if model.isPaired {
                DriveScreen()
            } else {
                ConnectView()
            }
        }
        .onChange(of: phase) { _, newPhase in
            model.isActive = newPhase == .active  // in the background: stop and no video
        }
        .fullScreenCover(item: $model.prompt) { prompt in
            ConfirmView(prompt: prompt)
                .environment(model)
        }
    }
}
