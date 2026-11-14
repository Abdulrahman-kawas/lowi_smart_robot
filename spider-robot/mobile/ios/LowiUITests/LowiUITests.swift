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
        app.launch()

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
