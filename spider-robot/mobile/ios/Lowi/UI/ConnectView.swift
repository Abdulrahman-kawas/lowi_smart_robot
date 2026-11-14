import SwiftUI

/// Brain address, connection test, pairing code. STOP is here too: before pairing it explains
/// how else to stop the robot, because the brain will not take orders from an unpaired phone.
struct ConnectView: View {
    @Environment(AppModel.self) private var model
    @State private var check: ConnectionCheck?
    @State private var checking = false
    @State private var code = ""
    @State private var pairError: String?
    @State private var pairing = false
    @FocusState private var focus: Field?
    @State private var wide = true

    private enum Field { case address, code, name }

    var body: some View {
        @Bindable var model = model
        ZStack(alignment: .bottomTrailing) {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Connect to Lowi")
                            .font(.largeTitle.weight(.bold))
                            .foregroundStyle(Theme.text)
                        Text("The app talks only to the brain on your home server, over Tailscale.")
                            .font(.subheadline)
                            .foregroundStyle(Theme.muted)
                    }
                    if wide {
                        HStack(alignment: .top, spacing: 18) {
                            addressCard(model: model)
                            pairCard(model: model)
                        }
                    } else {
                        VStack(alignment: .leading, spacing: 18) {
                            addressCard(model: model)
                            pairCard(model: model)
                        }
                    }
                    if let notice = model.notice {
                        NoticeView(text: notice) { model.notice = nil }
                    }
                }
                .padding(24)
                .padding(.trailing, 110)  // room for STOP
            }
            .onGeometryChange(for: Bool.self) { $0.size.width >= 680 } action: { wide = $0 }
            .scrollDismissesKeyboard(.interactively)
            StopButton()
                .padding(20)
        }
        .toolbar {
            ToolbarItemGroup(placement: .keyboard) {
                Spacer()
                Button("Done") { focus = nil }  // the number pad has no return key
                    .accessibilityIdentifier("keyboardDone")
            }
        }
    }

    private func addressCard(model: AppModel) -> some View {
        @Bindable var model = model
        return Card(title: "1. Brain address") {
            TextField("home-server.tailnet.ts.net", text: $model.addressText)
                .textContentType(.URL)
                .keyboardType(.URL)
                .autocorrectionDisabled()
                .textInputAutocapitalization(.never)
                .focused($focus, equals: .address)
                .submitLabel(.go)
                .onSubmit { test() }
                .fieldStyle()
                .accessibilityLabel(Text("Brain address"))
                .accessibilityIdentifier("address")
            Text("The server's Tailscale name. In the iOS Simulator, use 127.0.0.1.")
                .font(.caption)
                .foregroundStyle(Theme.muted)
            Button(action: test) {
                HStack {
                    if checking { ProgressView().controlSize(.small) }
                    Text("Test connection")
                }
                .frame(maxWidth: .infinity)
            }
            .buttonStyle(.bordered)
            .disabled(checking || model.addressText.isEmpty)
            .accessibilityIdentifier("testConnection")
            if let check {
                CheckResult(check: check)
            }
        }
    }

    private func pairCard(model: AppModel) -> some View {
        @Bindable var model = model
        return Card(title: "2. Pair this device") {
            Text("On the server, run `spider-brain pair`. Enter the 6-digit code it prints or sends you on Telegram.")
                .font(.caption)
                .foregroundStyle(Theme.muted)
                .fixedSize(horizontal: false, vertical: true)
            TextField("123456", text: $code)
                .keyboardType(.numberPad)
                .textContentType(.oneTimeCode)
                .font(.title2.monospacedDigit().weight(.semibold))
                .focused($focus, equals: .code)
                .onChange(of: code) { _, new in code = String(new.filter(\.isNumber).prefix(6)) }
                .fieldStyle()
                .accessibilityLabel(Text("Pairing code"))
                .accessibilityIdentifier("pairCode")
            TextField("Device name", text: $model.deviceName)
                .focused($focus, equals: .name)
                .fieldStyle()
                .accessibilityLabel(Text("Device name"))
                .accessibilityIdentifier("deviceName")
            Button(action: pair) {
                HStack {
                    if pairing { ProgressView().controlSize(.small) }
                    Text("Pair")
                }
                .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)
            .disabled(pairing || code.count != 6 || model.addressText.isEmpty
                      || model.deviceName.trimmingCharacters(in: .whitespaces).isEmpty)
            .accessibilityIdentifier("pair")
            if let pairError {
                Label(pairError, systemImage: "xmark.octagon.fill")
                    .font(.footnote)
                    .foregroundStyle(Theme.red)
            }
        }
    }

    private func test() {
        focus = nil
        checking = true
        Task {
            check = await model.checkConnection()
            checking = false
        }
    }

    private func pair() {
        focus = nil
        pairing = true
        pairError = nil
        Task {
            pairError = await model.pair(code: code)
            pairing = false
            if pairError != nil, model.hapticsOn { Haptics.refusal() }
        }
    }
}

private struct CheckResult: View {
    var check: ConnectionCheck

    var body: some View {
        switch check {
        case .reachable:
            Label("The brain answered.", systemImage: "checkmark.circle.fill")
                .foregroundStyle(Theme.green)
                .font(.footnote.weight(.semibold))
                .accessibilityIdentifier("checkResult")
        case .badAddress:
            Label("That is not an address.", systemImage: "xmark.octagon.fill")
                .foregroundStyle(Theme.red)
                .font(.footnote)
                .accessibilityIdentifier("checkResult")
        case .unreachable(let reason, let tailscaleOff):
            VStack(alignment: .leading, spacing: 6) {
                if tailscaleOff {
                    Label("Tailscale is off on this device. Turn it on in the Tailscale app, then test again.",
                          systemImage: "network.slash")
                        .foregroundStyle(Theme.amber)
                        .font(.footnote.weight(.semibold))
                }
                Label(reason, systemImage: "xmark.octagon.fill")
                    .foregroundStyle(Theme.red)
                    .font(.footnote)
            }
            .accessibilityElement(children: .combine)
            .accessibilityIdentifier("checkResult")
        }
    }
}

struct Card<Content: View>: View {
    var title: LocalizedStringKey
    @ViewBuilder var content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(title)
                .font(.headline)
                .foregroundStyle(Theme.text)
                .accessibilityAddTraits(.isHeader)
            content
        }
        .padding(18)
        .frame(maxWidth: 420, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 16).fill(Theme.panel))
        .overlay(RoundedRectangle(cornerRadius: 16).stroke(Theme.panelLine, lineWidth: 1))
    }
}

extension View {
    func fieldStyle() -> some View {
        padding(.horizontal, 12)
            .padding(.vertical, 10)
            .background(RoundedRectangle(cornerRadius: 10).fill(Theme.background))
            .overlay(RoundedRectangle(cornerRadius: 10).stroke(Theme.panelLine, lineWidth: 1))
            .foregroundStyle(Theme.text)
    }
}
