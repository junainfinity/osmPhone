import XCTest
@testable import OsmBT

final class ProtocolTests: XCTestCase {

    // UT-BT-001.1-01: Encode event to JSON
    func testEncodeEvent() throws {
        let payload = DeviceFoundPayload(address: "AA:BB:CC:DD:EE:FF", name: "iPhone 15", rssi: -45)
        let data = try EventBuilder.build(type: .deviceFound, payload: payload)
        let json = try JSONSerialization.jsonObject(with: data) as! [String: Any]

        XCTAssertEqual(json["type"] as? String, "device_found")
        XCTAssertNotNil(json["id"] as? String)
        let eventPayload = json["payload"] as? [String: Any]
        XCTAssertEqual(eventPayload?["address"] as? String, "AA:BB:CC:DD:EE:FF")
        XCTAssertEqual(eventPayload?["name"] as? String, "iPhone 15")
        XCTAssertEqual(eventPayload?["rssi"] as? Int, -45)
    }

    // UT-BT-001.1-02: Decode command from JSON
    func testDecodeCommand() throws {
        let jsonStr = #"{"id":"cmd-1","type":"scan_start","payload":{}}"#
        let data = jsonStr.data(using: .utf8)!
        let (id, type, payload) = try CommandParser.parse(data)

        XCTAssertEqual(id, "cmd-1")
        XCTAssertEqual(type, .scanStart)
        XCTAssertTrue(payload.isEmpty)
    }

    // UT-BT-001.1-03: Reject malformed JSON
    func testRejectMalformedJSON() {
        let jsonStr = #"{"type":}"#
        let data = jsonStr.data(using: .utf8)!
        XCTAssertThrowsError(try CommandParser.parse(data))
    }

    // UT-BT-001.1-04: Reject unknown command type
    func testRejectUnknownCommand() {
        let jsonStr = #"{"id":"x","type":"fly","payload":{}}"#
        let data = jsonStr.data(using: .utf8)!
        XCTAssertThrowsError(try CommandParser.parse(data)) { error in
            guard case ProtocolError.unknownCommand("fly") = error else {
                XCTFail("Expected unknownCommand error")
                return
            }
        }
    }

    // UT-BT-001.1-05: Round-trip encode/decode event payload
    func testRoundTrip() throws {
        let original = SMSReceivedPayload(from: "+1234", body: "Hello", timestamp: "2026-04-09T10:00:00Z")
        let data = try EventBuilder.build(type: .smsReceived, payload: original)

        // Parse as generic JSON
        let json = try JSONSerialization.jsonObject(with: data) as! [String: Any]
        let payload = json["payload"] as! [String: Any]

        XCTAssertEqual(payload["from"] as? String, "+1234")
        XCTAssertEqual(payload["body"] as? String, "Hello")
        XCTAssertEqual(payload["timestamp"] as? String, "2026-04-09T10:00:00Z")
    }

    // Test decode command with payload
    func testDecodeDialCommand() throws {
        let jsonStr = #"{"id":"cmd-5","type":"dial","payload":{"number":"+14155551234"}}"#
        let data = jsonStr.data(using: .utf8)!
        let (id, type, payload) = try CommandParser.parse(data)

        XCTAssertEqual(id, "cmd-5")
        XCTAssertEqual(type, .dial)
        XCTAssertEqual(payload["number"] as? String, "+14155551234")
    }

    // Test all command types parse
    func testAllCommandTypesValid() {
        let types = ["scan_start", "scan_stop", "pair", "pair_confirm", "connect_hfp",
                     "disconnect_hfp", "answer_call", "reject_call", "end_call",
                     "dial", "send_sms", "inject_audio", "transfer_audio", "send_dtmf"]

        for typeStr in types {
            XCTAssertNotNil(CommandType(rawValue: typeStr), "Missing CommandType: \(typeStr)")
        }
    }

    // Test all event types valid
    func testAllEventTypesValid() {
        let types = ["device_found", "scan_complete", "paired", "pair_failed",
                     "pair_confirm", "hfp_connected", "hfp_disconnected",
                     "incoming_call", "call_active", "call_ended",
                     "sco_opened", "sco_closed", "sco_audio",
                     "sms_received", "sms_sent", "signal_update",
                     "battery_update", "error"]

        for typeStr in types {
            XCTAssertNotNil(EventType(rawValue: typeStr), "Missing EventType: \(typeStr)")
        }
    }

    // Test event data ends with newline
    func testEventEndsWithNewline() throws {
        let payload = DeviceFoundPayload(address: "AA:BB", name: "Test", rssi: -30)
        let data = try EventBuilder.build(type: .deviceFound, payload: payload)
        XCTAssertEqual(data.last, 0x0A, "Event data should end with newline")
    }
}
