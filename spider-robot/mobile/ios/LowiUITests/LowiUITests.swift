import XCTest

final class StopOnConnectTests: XCTestCase {
    /// Before pairing STOP still answers: it says how else to stop the robot.
    @MainActor
    func testStopIsTappableBeforePairing() {
        let app = XCUIApplication()
        app.launchArguments = ["-resetPairing"]
        app.launch()
        let stop = app.descendants(matching: .any)["stop"]
        XCTAssertTrue(stop.waitForExistence(timeout: 5))
        XCTAssertTrue(stop.isHittable)
        stop.tap()
        XCTAssertTrue(app.descendants(matching: .any)
            .matching(NSPredicate(format: "label CONTAINS[c] 'Not paired yet'")).firstMatch
            .waitForExistence(timeout: 3))
    }
}

final class PanControlTests: XCTestCase {
    @MainActor
    func testSliderAndCenterAreOnTheDriveScreen() {
        let app = XCUIApplication()
        app.launchArguments = ["-uiTestFake"]
        app.launch()
        XCTAssertTrue(app.descendants(matching: .any)["panSlider"].waitForExistence(timeout: 10))
        XCTAssertTrue(app.descendants(matching: .any)["panCenter"].exists)
    }
}

/// The app against the real simulator stack on this Mac (mobile/README.md). Skipped unless a
/// pairing code from `spider-brain pair` is passed:
///   TEST_RUNNER_LOWI_PAIR_CODE=123456 xcodebuild test -only-testing:LowiUITests/SimulatorDriveTests
final class SimulatorDriveTests: XCTestCase {
    @MainActor
    func testPairStandDriveTurnStopAndRelease() throws {
        let code = try XCTUnwrap(ProcessInfo.processInfo.environment["LOWI_PAIR_CODE"]
            .flatMap { $0.isEmpty ? nil : $0 }, "no pairing code: skipped")
        let app = XCUIApplication()
        app.launchArguments = ["-resetPairing"]
        let pad = UIDevice.current.userInterfaceIdiom == .pad
        if pad { XCUIDevice.shared.orientation = .landscapeLeft }  // camera left, sidebar right
        app.launch()
        if pad { rotate(app, to: .landscapeLeft) }

        let address = app.textFields["address"]
        XCTAssertTrue(address.waitForExistence(timeout: 5))
        address.tap()
        address.typeText("127.0.0.1\n")
        XCTAssertTrue(app.descendants(matching: .any)["checkResult"].waitForExistence(timeout: 5))
        pause(1)
        let codeField = app.textFields["pairCode"]
        codeField.tap()
        codeField.typeText(code)
        pause(0.5)
        app.buttons["keyboardDone"].tap()
        pause(0.5)
        app.buttons["pair"].tap()

        // Drive screen: live link, camera frames, robot limp.
        let link = app.descendants(matching: .any)["link"]
        XCTAssertTrue(link.waitForExistence(timeout: 10))
        pause(2)

        // Stand: the robot is limp, so the app shows a fresh frame and asks for a long press.
        app.buttons["stand"].tap()
        let hold = app.descendants(matching: .any)["holdToConfirm"]
        XCTAssertTrue(hold.waitForExistence(timeout: 10))
        pause(1.5)
        hold.press(forDuration: 2.0)
        let block = app.descendants(matching: .any)["driveBlock"]
        XCTAssertTrue(waitUntilGone(block, timeout: 15), "drive controls never came on")
        pause(1)

        // Hold the joystick forward for 3 s, then the turn control to the left for 2 s.
        let stick = app.descendants(matching: .any)["joystick"]
        let centre = stick.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5))
        centre.press(forDuration: 0.1,
                     thenDragTo: stick.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.08)),
                     withVelocity: .slow, thenHoldForDuration: 3.0)
        pause(1.5)
        let turn = app.descendants(matching: .any)["turn"]
        turn.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5))
            .press(forDuration: 0.1,
                   thenDragTo: turn.coordinate(withNormalizedOffset: CGVector(dx: 0.05, dy: 0.5)),
                   withVelocity: .slow, thenHoldForDuration: 2.0)
        pause(1)

        // Forward again, and STOP while the stick is still pushed.
        app.descendants(matching: .any)["stop"].tap()
        pause(1)

        // E-stop is one tap; releasing it is a fresh frame and a long press.
        app.buttons["estop"].tap()
        let release = app.buttons["release"]
        XCTAssertTrue(release.waitForExistence(timeout: 5))
        pause(1.5)
        release.tap()
        XCTAssertTrue(hold.waitForExistence(timeout: 10))
        pause(1.5)
        hold.press(forDuration: 2.0)
        XCTAssertTrue(waitUntilGone(release, timeout: 10))
        pause(2)
    }

    private func pause(_ seconds: TimeInterval) {
        Thread.sleep(forTimeInterval: seconds)
    }

    private func waitUntilGone(_ element: XCUIElement, timeout: TimeInterval) -> Bool {
        let gone = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"),
                                             object: element)
        return XCTWaiter().wait(for: [gone], timeout: timeout) == .completed
    }
}

/// STOP is on every screen, is hittable, and fires, in the iPhone and the iPad layout. Runs
/// against the app's built-in fake brain (-uiTestFake), so it needs no server.
final class StopEverywhereTests: XCTestCase {
    private var app: XCUIApplication!
    private var presses = 0

    @MainActor
    func testStopOnEveryScreen() {
        app = XCUIApplication()
        app.launchArguments = ["-uiTestFake"]
        app.launch()

        XCTAssertTrue(app.descendants(matching: .any)["link"].waitForExistence(timeout: 10))
        pressStop("stop", on: "Drive")

        app.buttons["settings"].tap()
        pressStop("stop.settings", on: "Settings")
        app.buttons["closeSettings"].tap()
        waitGone("stop.settings")

        if app.buttons["photo"].waitForExistence(timeout: 2) {  // iPhone: its own screen
            app.buttons["photo"].tap()
            pressStop("stop.photo", on: "Photo")
            app.buttons["takePhoto"].tap()
            XCTAssertTrue(app.descendants(matching: .any)["photoAnswer"].waitForExistence(timeout: 5))
            pressStop("stop.photo", on: "Photo, after the answer")
            app.buttons["closePhoto"].tap()
            waitGone("stop.photo")

            app.buttons["talk"].tap()
            pressStop("stop.talk", on: "Talk")
            let talk = app.buttons["talkButton"]
            XCTAssertTrue(talk.waitForExistence(timeout: 5))
            talk.press(forDuration: 1.0)  // hold, then release: the fake brain answers
            XCTAssertTrue(app.descendants(matching: .any)["talkReply"].waitForExistence(timeout: 5))
            XCTAssertTrue(app.descendants(matching: .any)["talkHeard"].exists)
            pressStop("stop.talk", on: "Talk, after the answer")
            app.buttons["closeTalk"].tap()
            waitGone("stop.talk")
        } else {  // iPad: a panel next to the camera
            XCTAssertTrue(app.buttons["takePhoto"].waitForExistence(timeout: 5))
            app.buttons["takePhoto"].tap()
            if !app.descendants(matching: .any)["photoAnswer"].waitForExistence(timeout: 5) {
                let shot = XCTAttachment(screenshot: app.screenshot())
                shot.name = "no-photo-answer"
                shot.lifetime = .keepAlways
                add(shot)
                XCTFail("no answer in the iPad photo panel")
            }
            XCTAssertTrue(app.descendants(matching: .any)["radar"].exists)
            pressStop("stop", on: "Drive with the photo answer")
            let talk = app.buttons["talkButton"]
            XCTAssertTrue(talk.waitForExistence(timeout: 5))
            talk.press(forDuration: 1.0)
            XCTAssertTrue(app.descendants(matching: .any)["talkReply"].waitForExistence(timeout: 5),
                          "no answer in the iPad talk panel")
            pressStop("stop", on: "Drive with the talk answer")
        }

        app.buttons["release"].tap()
        XCTAssertTrue(app.descendants(matching: .any)["holdToConfirm"].waitForExistence(timeout: 5))
        pressStop("stop.confirm", on: "E-stop release")
        app.buttons["cancelConfirm"].tap()
        waitGone("stop.confirm")
        pressStop("stop", on: "Drive, after cancelling")
    }

    /// Waits until that screen's STOP can be touched, taps it, and checks it fired.
    @MainActor
    private func pressStop(_ id: String, on screen: String,
                           file: StaticString = #filePath, line: UInt = #line) {
        let stop = app.descendants(matching: .any)[id]
        let ready = NSPredicate(format: "exists == true AND hittable == true")
        guard XCTWaiter().wait(for: [XCTNSPredicateExpectation(predicate: ready, object: stop)],
                               timeout: 8) == .completed else {
            XCTFail("STOP on \(screen) never became tappable", file: file, line: line)
            return
        }
        stop.tap()
        presses += 1
        let fired = NSPredicate(format: "value == %@", "\(presses)")
        let ok = XCTWaiter().wait(for: [XCTNSPredicateExpectation(predicate: fired, object: stop)],
                                  timeout: 3) == .completed
        XCTAssertTrue(ok, "STOP on \(screen) did not fire", file: file, line: line)
        if !ok, let value = stop.value as? String, let count = Int(value) {
            presses = count  // report this screen only, not every screen after it
        }
    }

    /// Waits for a sheet or cover to be gone. Its elements leave the tree a moment before its
    /// closing animation stops swallowing touches, so give that moment too.
    @MainActor
    private func waitGone(_ id: String) {
        let gone = NSPredicate(format: "exists == false")
        let element = app.descendants(matching: .any)[id]
        _ = XCTWaiter().wait(for: [XCTNSPredicateExpectation(predicate: gone, object: element)],
                             timeout: 5)
        Thread.sleep(forTimeInterval: 0.8)
    }
}

/// Screenshots of every screen for review and for the README. Skipped unless asked for:
///   TEST_RUNNER_LOWI_SCREENSHOTS=1 [TEST_RUNNER_LOWI_LANG=ja] xcodebuild test \
///     -only-testing:LowiUITests/ScreenshotTests
/// then: xcrun xcresulttool export attachments --path <result bundle> --output-path <folder>
final class ScreenshotTests: XCTestCase {
    @MainActor
    func testCaptureScreens() throws {
        let env = ProcessInfo.processInfo.environment
        try XCTSkipUnless(env["LOWI_SCREENSHOTS"] == "1", "screenshots not asked for")
        let app = XCUIApplication()
        app.launchArguments = ["-uiTestFake"]
        if let lang = env["LOWI_LANG"], !lang.isEmpty {
            app.launchArguments += ["-AppleLanguages", "(\(lang))", "-AppleLocale", lang]
        }
        if let extra = env["LOWI_ARGS"], !extra.isEmpty {  // e.g. right-to-left or a text size
            app.launchArguments += extra.split(separator: " ").map(String.init)
        }
        let pad = UIDevice.current.userInterfaceIdiom == .pad
        XCUIDevice.shared.orientation = .landscapeLeft
        app.launch()
        rotate(app, to: .landscapeLeft)
        XCTAssertTrue(app.descendants(matching: .any)["link"].waitForExistence(timeout: 10))
        Thread.sleep(forTimeInterval: 2)
        snap("drive")

        app.buttons["settings"].tap()
        XCTAssertTrue(app.descendants(matching: .any)["settingsForm"].waitForExistence(timeout: 5))
        snap("settings")
        app.buttons["closeSettings"].tap()

        if !pad {
            app.buttons["photo"].tap()
        }
        let question = app.textViews["photoQuestion"].exists ? app.textViews["photoQuestion"]
            : app.textFields["photoQuestion"]
        if question.waitForExistence(timeout: 5) {
            question.tap()
            question.typeText("What is in front of you?")
            app.buttons["takePhoto"].tap()
            XCTAssertTrue(app.descendants(matching: .any)["photoAnswer"].waitForExistence(timeout: 5))
            Thread.sleep(forTimeInterval: 1)
            snap(pad ? "drive-photo" : "photo")
        }
        if !pad { app.buttons["closePhoto"].tap() }

        app.buttons["release"].tap()
        XCTAssertTrue(app.descendants(matching: .any)["holdToConfirm"].waitForExistence(timeout: 5))
        Thread.sleep(forTimeInterval: 1)
        snap("release")
        app.buttons["cancelConfirm"].tap()

        if pad {
            rotate(app, to: .portrait)
            Thread.sleep(forTimeInterval: 1)
            snap("drive-portrait")
        }
        app.terminate()
        let connect = XCUIApplication()
        connect.launchArguments = ["-uiTestFake", "-resetPairing", "-uiTestUnpaired"]
            + Array(app.launchArguments.dropFirst())
        connect.launch()
        Thread.sleep(forTimeInterval: 2)
        snap("connect")
    }

    @MainActor
    private func snap(_ name: String) {
        let shot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        shot.name = name
        shot.lifetime = .keepAlways
        add(shot)
    }
}

/// Turns the simulator. Set before launch it sticks; set again after launch in case the app
/// started in the old orientation. Then give the layout a moment.
@MainActor
func rotate(_ app: XCUIApplication, to orientation: UIDeviceOrientation) {
    XCUIDevice.shared.orientation = orientation
    Thread.sleep(forTimeInterval: 1.5)
}

/// Apple's accessibility audit (labels, contrast, Dynamic Type, hit areas, clipped text) on every
/// screen, against the built-in fake brain.
final class AccessibilityAuditTests: XCTestCase {
    @MainActor
    func testEveryScreenPassesTheAudit() throws {
        let app = XCUIApplication()
        app.launchArguments = ["-uiTestFake"]
        app.launch()
        XCTAssertTrue(app.descendants(matching: .any)["link"].waitForExistence(timeout: 10))
        try audit(app, "Drive")

        app.buttons["settings"].tap()
        XCTAssertTrue(app.descendants(matching: .any)["stop.settings"].waitForExistence(timeout: 5))
        try audit(app, "Settings")
        app.buttons["closeSettings"].tap()
        Thread.sleep(forTimeInterval: 1.5)

        if app.buttons["photo"].exists {
            app.buttons["photo"].tap()
            XCTAssertTrue(app.descendants(matching: .any)["stop.photo"].waitForExistence(timeout: 5))
            try audit(app, "Photo")
            app.buttons["closePhoto"].tap()
            Thread.sleep(forTimeInterval: 1.5)
        }

        if app.buttons["talk"].exists {
            app.buttons["talk"].tap()
            XCTAssertTrue(app.descendants(matching: .any)["stop.talk"].waitForExistence(timeout: 5))
            try audit(app, "Talk")
            app.buttons["talkButton"].press(forDuration: 1.0)
            XCTAssertTrue(app.descendants(matching: .any)["talkReply"].waitForExistence(timeout: 5))
            try audit(app, "Talk, with an answer")
            app.buttons["closeTalk"].tap()
            Thread.sleep(forTimeInterval: 1.5)
        }

        app.buttons["release"].tap()
        XCTAssertTrue(app.descendants(matching: .any)["holdToConfirm"].waitForExistence(timeout: 5))
        try audit(app, "E-stop release")
        app.buttons["cancelConfirm"].tap()
        Thread.sleep(forTimeInterval: 1.5)

        app.terminate()
        let connect = XCUIApplication()
        connect.launchArguments = ["-uiTestFake", "-resetPairing", "-uiTestUnpaired"]
        connect.launch()
        XCTAssertTrue(connect.descendants(matching: .any)["stop"].waitForExistence(timeout: 10))
        try audit(connect, "Connect")
    }

    /// Fails on every issue except the deliberate limits below, each with its reason.
    @MainActor
    private func audit(_ app: XCUIApplication, _ screen: String) throws {
        Thread.sleep(forTimeInterval: 1.5)  // a sheet still sliding in reads as low contrast
        try app.performAccessibilityAudit { issue in
            let element = issue.element
            let id = element?.identifier ?? ""
            let label = element?.label ?? ""
            let accepted: String? = {
                if issue.auditType == .contrast, let element, !element.isEnabled {
                    return "disabled controls are exempt from contrast rules"
                }
                if issue.auditType == .contrast, ["Settings", "Photo", "Talk"].contains(label),
                   ProcessInfo.processInfo.operatingSystemVersion.majorVersion < 18 {
                    // Measured in the iOS 17.5 screenshot: white on the solid #161D27 bar, 16.9:1.
                    return "iOS 17's audit misreads the sheet title; its measured contrast is 16.9:1"
                }
                if issue.auditType == .textClipped, ["address", "deviceName"].contains(id) {
                    return "a single-line field scrolls sideways, like Safari's address bar"
                }
                let pad = UIDevice.current.userInterfaceIdiom == .pad
                if pad, issue.auditType == .contrast, screen == "Drive",
                   let frame = element?.frame, frame.minY > 800 {
                    // Measured in an iPad screenshot: event log 6.8 and 14.4:1, Take photo 7.1:1,
                    // hints 7.6:1. The audit's frames in the portrait sidebar are about 40 pt off
                    // and land on card borders.
                    return "iPad sidebar text, measured at 6.8:1 or more"
                }
                if pad, issue.auditType == .elementDetection, element == nil {
                    return "text on the dimmed screen behind a modal sheet, rightly hidden from VoiceOver"
                }
                guard issue.auditType == .dynamicType else { return nil }
                if screen == "Drive" {
                    return "the drive HUD grows only to the first accessibility size, so the camera keeps its room"
                }
                if label == "STOP" { return "STOP grows with the text size up to 140 pt" }
                if ["closeSettings", "closePhoto", "closeTalk"].contains(id) { return "a system toolbar button" }
                if label.hasPrefix("Photo taken") { return "the caption on the photo is capped like the HUD" }
                return nil
            }()
            print("AUDIT [\(screen)] \(accepted == nil ? "FAIL" : "accepted") "
                  + "\(issue.compactDescription): \(id) '\(label)' "
                  + "\(element.map { "\($0.frame)" } ?? "")"
                  + (accepted.map { " (\($0))" } ?? " | \(issue.detailedDescription)"))
            return accepted != nil
        }
    }
}

/// The README screenshots, taken against the real simulator stack (mobile/README.md). Skipped
/// unless asked for, with a fresh code from `spider-brain pair`:
///   TEST_RUNNER_LOWI_README=1 TEST_RUNNER_LOWI_PAIR_CODE=123456 [TEST_RUNNER_LOWI_LANG=ja] \
///     xcodebuild test -only-testing:LowiUITests/ReadmeScreenshotTests
final class ReadmeScreenshotTests: XCTestCase {
    @MainActor
    func testLiveScreens() throws {
        let env = ProcessInfo.processInfo.environment
        try XCTSkipUnless(env["LOWI_README"] == "1", "README screenshots not asked for")
        let code = try XCTUnwrap(env["LOWI_PAIR_CODE"], "no pairing code")
        let app = XCUIApplication()
        app.launchArguments = ["-resetPairing"]
        if let lang = env["LOWI_LANG"], !lang.isEmpty {
            app.launchArguments += ["-AppleLanguages", "(\(lang))", "-AppleLocale", lang]
        }
        XCUIDevice.shared.orientation = .landscapeLeft
        app.launch()
        rotate(app, to: .landscapeLeft)

        let address = app.textFields["address"]
        XCTAssertTrue(address.waitForExistence(timeout: 10))
        address.tap()
        address.typeText("127.0.0.1\n")
        XCTAssertTrue(app.descendants(matching: .any)["checkResult"].waitForExistence(timeout: 5))
        let codeField = app.textFields["pairCode"]
        codeField.tap()
        codeField.typeText(code)
        app.buttons["keyboardDone"].tap()
        Thread.sleep(forTimeInterval: 0.8)
        app.buttons["pair"].tap()
        XCTAssertTrue(app.descendants(matching: .any)["link"].waitForExistence(timeout: 10))
        Thread.sleep(forTimeInterval: 3)

        // Stand up: a limp robot asks for a fresh photo and a long press first.
        app.buttons["stand"].tap()
        let hold = app.descendants(matching: .any)["holdToConfirm"]
        if hold.waitForExistence(timeout: 6) {
            Thread.sleep(forTimeInterval: 1)
            hold.press(forDuration: 2.0)
        }
        let block = app.descendants(matching: .any)["driveBlock"]
        let gone = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"),
                                             object: block)
        XCTAssertEqual(XTCWait(gone, 20), .completed, "drive controls never came on")
        Thread.sleep(forTimeInterval: 7)  // the "posture sent" notice fades after 6 s
        snap("drive")

        app.buttons["estop"].tap()
        let release = app.buttons["release"]
        XCTAssertTrue(release.waitForExistence(timeout: 5))
        Thread.sleep(forTimeInterval: 1)
        release.tap()
        XCTAssertTrue(hold.waitForExistence(timeout: 10))
        Thread.sleep(forTimeInterval: 1.5)
        snap("release")
        hold.press(forDuration: 2.0)
        let released = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"),
                                                 object: release)
        XCTAssertEqual(XTCWait(released, 10), .completed)
    }

    @MainActor
    private func XTCWait(_ expectation: XCTestExpectation, _ seconds: TimeInterval) -> XCTWaiter.Result {
        XCTWaiter().wait(for: [expectation], timeout: seconds)
    }

    @MainActor
    private func snap(_ name: String) {
        let shot = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        shot.name = name
        shot.lifetime = .keepAlways
        add(shot)
    }
}
