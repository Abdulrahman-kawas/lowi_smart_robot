import GameController

/// A hardware keyboard and game controllers, through the GameController framework.
///
/// Keys: W/S forward and back, A/D sideways, Q/E turn, Space STOP, Esc E-stop, the same as the
/// simulator page. Controller: left stick drives, right stick turns, B is STOP, Y is E-stop.
/// Holding a key or a stick out of its dead zone is the dead-man hold. Nothing is read while a
/// text field has the keyboard, so typing a question never drives the robot.
@MainActor
final class HardwareInput {
    private static let keys: [GCKeyCode: Character] = [
        .keyW: "w", .keyS: "s", .keyA: "a", .keyD: "d", .keyQ: "q", .keyE: "e",
    ]

    private weak var model: AppModel?
    private var pressed: Set<Character> = []
    private var observers: [NSObjectProtocol] = []

    init(model: AppModel) {
        self.model = model
        // On any change, look at what is connected now rather than at the notification.
        let center = NotificationCenter.default
        let watch: [(Notification.Name, @MainActor (HardwareInput) -> Void)] = [
            (.GCKeyboardDidConnect, { $0.attach(keyboard: GCKeyboard.coalesced) }),
            (.GCKeyboardDidDisconnect, { $0.keyboardGone() }),
            (.GCControllerDidConnect, { input in
                GCController.controllers().forEach { input.attach(controller: $0) }
            }),
            (.GCControllerDidDisconnect, { $0.controllerGone() }),
        ]
        for (name, handle) in watch {
            observers.append(center.addObserver(forName: name, object: nil, queue: .main) {
                [weak self] _ in
                MainActor.assumeIsolated {
                    if let self { handle(self) }
                }
            })
        }
        attach(keyboard: GCKeyboard.coalesced)
        GCController.controllers().forEach { attach(controller: $0) }
    }

    /// The app left the foreground: forget every key and stick, a key-up may never come.
    func reset() {
        pressed.removeAll()
        model?.setKeys(.none)
        model?.setPad(stick: nil, turn: nil)
    }

    private func attach(keyboard: GCKeyboard?) {
        guard let input = keyboard?.keyboardInput else { return }
        model?.hasKeyboard = true
        input.keyChangedHandler = { [weak self] _, _, code, down in
            MainActor.assumeIsolated { self?.key(code, down: down) }
        }
    }

    private func keyboardGone() {
        model?.hasKeyboard = GCKeyboard.coalesced != nil
        pressed.removeAll()
        model?.setKeys(.none)
    }

    private func key(_ code: GCKeyCode, down: Bool) {
        guard let model else { return }
        if model.textEditing {
            if !pressed.isEmpty {
                pressed.removeAll()
                model.setKeys(.none)
            }
            return
        }
        if code == .spacebar {
            if down { model.pressStop() }
        } else if code == .escape {
            if down { model.pressEstop() }
        } else if let key = Self.keys[code] {
            if down { pressed.insert(key) } else { pressed.remove(key) }
            model.setKeys(DriveMapping.axes(keys: pressed))
        }
    }

    private func attach(controller: GCController?) {
        guard let controller, let pad = controller.extendedGamepad else { return }
        model?.controllerName = controller.vendorName ?? String(localized: "Controller")
        pad.valueChangedHandler = { [weak self] pad, element in
            MainActor.assumeIsolated { self?.read(pad, changed: element) }
        }
    }

    private func controllerGone() {
        let next = GCController.controllers().first { $0.extendedGamepad != nil }
        model?.controllerName = next.map { $0.vendorName ?? String(localized: "Controller") }
        model?.setPad(stick: nil, turn: nil)
    }

    private func read(_ pad: GCExtendedGamepad, changed element: GCControllerElement) {
        guard let model else { return }
        if element === pad.buttonB, pad.buttonB.isPressed { model.pressStop() }
        if element === pad.buttonY, pad.buttonY.isPressed { model.pressEstop() }
        let (stick, turn) = DriveMapping.pad(leftX: pad.leftThumbstick.xAxis.value,
                                             leftY: pad.leftThumbstick.yAxis.value,
                                             rightX: pad.rightThumbstick.xAxis.value)
        model.setPad(stick: stick, turn: turn)
    }
}
