// Protocol.swift — Component BT-001.1
//
// Defines all IPC message types exchanged between osm-bt (Swift) and osm-core (Python)
// over the Unix domain socket at /tmp/osmphone.sock.
//
// Protocol: JSON-over-newline. Each message is one JSON object terminated by \n.
// Direction: Events flow from osm-bt -> osm-core. Commands flow osm-core -> osm-bt.
//
// IMPORTANT: Both sides (Swift and Python) must agree on these type strings.
// If you add a new event/command here, also update:
//   - osm-core/osm_core/bt_bridge.py (register handler for the new event)
//   - ARCHITECTURE.md IPC Protocol tables
//   - TEST_PLAN.md test cases
//
// All payload structs are Codable. EventBuilder serializes them to JSON + newline.
// CommandParser deserializes incoming JSON lines into (id, type, payload) tuples.

import Foundation

// MARK: - Message Envelope

/// Every IPC message has an id, type, and payload.
/// The id enables request-response correlation (not used yet, but available).
struct IPCMessage: Codable {
    let id: String
    let type: String
    let payload: [String: AnyCodable]
}

// MARK: - Events (osm-bt -> osm-core)

enum EventType: String, Codable {
    case deviceFound = "device_found"
    case scanComplete = "scan_complete"
    case paired = "paired"
    case pairFailed = "pair_failed"
    case pairConfirm = "pair_confirm"
    case hfpConnected = "hfp_connected"
    case hfpDisconnected = "hfp_disconnected"
    case incomingCall = "incoming_call"
    case callActive = "call_active"
    case callEnded = "call_ended"
    case scoOpened = "sco_opened"
    case scoClosed = "sco_closed"
    case scoAudio = "sco_audio"
    case smsReceived = "sms_received"
    case smsSent = "sms_sent"
    case signalUpdate = "signal_update"
    case batteryUpdate = "battery_update"
    case error = "error"
}

// MARK: - Commands (osm-core -> osm-bt)

enum CommandType: String, Codable {
    case scanStart = "scan_start"
    case scanStop = "scan_stop"
    case pair = "pair"
    case pairConfirm = "pair_confirm"
    case connectHFP = "connect_hfp"
    case disconnectHFP = "disconnect_hfp"
    case answerCall = "answer_call"
    case rejectCall = "reject_call"
    case endCall = "end_call"
    case dial = "dial"
    case sendSMS = "send_sms"
    case injectAudio = "inject_audio"
    case transferAudio = "transfer_audio"
    case sendDTMF = "send_dtmf"
}

// MARK: - Event Payloads

struct DeviceFoundPayload: Codable {
    let address: String
    let name: String
    let rssi: Int
}

struct PairedPayload: Codable {
    let address: String
    let name: String
}

struct PairConfirmPayload: Codable {
    let address: String
    let name: String
    let numericValue: UInt32
}

struct HFPConnectedPayload: Codable {
    let address: String
    let signal: Int
    let battery: Int
    let service: Bool
}

struct IncomingCallPayload: Codable {
    let from: String
    let name: String?
}

struct CallEndedPayload: Codable {
    let reason: String  // local_hangup, remote_hangup, rejected, missed
}

struct SCOOpenedPayload: Codable {
    let codec: String   // CVSD or mSBC
    let sampleRate: Int // 8000 or 16000
}

struct SCOAudioPayload: Codable {
    let codec: String
    let sampleRate: Int
    let data: String    // base64-encoded PCM
}

struct SMSReceivedPayload: Codable {
    let from: String
    let body: String
    let timestamp: String
}

struct ErrorPayload: Codable {
    let code: String
    let message: String
}

// MARK: - Command Payloads

struct PairCommandPayload: Codable {
    let address: String
}

struct PairConfirmCommandPayload: Codable {
    let address: String
    let confirmed: Bool
}

struct ConnectHFPPayload: Codable {
    let address: String
}

struct DialPayload: Codable {
    let number: String
}

struct SendSMSPayload: Codable {
    let to: String
    let body: String
}

struct InjectAudioPayload: Codable {
    let sampleRate: Int
    let data: String    // base64-encoded PCM
}

struct TransferAudioPayload: Codable {
    let target: String  // "computer" or "phone"
}

struct SendDTMFPayload: Codable {
    let digit: String
}

// MARK: - AnyCodable (for flexible payload encoding)

/// Type-erased Codable wrapper for heterogeneous JSON payloads.
struct AnyCodable: Codable {
    let value: Any

    init(_ value: Any) {
        self.value = value
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if container.decodeNil() {
            value = NSNull()
        } else if let bool = try? container.decode(Bool.self) {
            value = bool
        } else if let int = try? container.decode(Int.self) {
            value = int
        } else if let double = try? container.decode(Double.self) {
            value = double
        } else if let string = try? container.decode(String.self) {
            value = string
        } else if let array = try? container.decode([AnyCodable].self) {
            value = array.map { $0.value }
        } else if let dict = try? container.decode([String: AnyCodable].self) {
            value = dict.mapValues { $0.value }
        } else {
            throw DecodingError.dataCorruptedError(in: container, debugDescription: "Unsupported type")
        }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.singleValueContainer()
        switch value {
        case is NSNull:
            try container.encodeNil()
        case let bool as Bool:
            try container.encode(bool)
        case let int as Int:
            try container.encode(int)
        case let double as Double:
            try container.encode(double)
        case let string as String:
            try container.encode(string)
        case let array as [Any]:
            try container.encode(array.map { AnyCodable($0) })
        case let dict as [String: Any]:
            try container.encode(dict.mapValues { AnyCodable($0) })
        default:
            throw EncodingError.invalidValue(value, .init(codingPath: encoder.codingPath, debugDescription: "Unsupported type"))
        }
    }
}

// MARK: - Helper to build event JSON

struct EventBuilder {
    private static var counter = 0

    static func nextID() -> String {
        counter += 1
        return "evt-\(counter)"
    }

    static func build<P: Encodable>(type: EventType, payload: P) throws -> Data {
        let encoder = JSONEncoder()
        let payloadData = try encoder.encode(payload)
        let payloadDict = try JSONSerialization.jsonObject(with: payloadData) as? [String: Any] ?? [:]
        let message: [String: Any] = [
            "id": nextID(),
            "type": type.rawValue,
            "payload": payloadDict
        ]
        var data = try JSONSerialization.data(withJSONObject: message)
        data.append(0x0A) // newline
        return data
    }
}

// MARK: - Helper to parse command JSON

struct CommandParser {
    static func parse(_ data: Data) throws -> (id: String, type: CommandType, payload: [String: Any]) {
        guard let json = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw ProtocolError.invalidJSON
        }
        guard let id = json["id"] as? String else {
            throw ProtocolError.missingField("id")
        }
        guard let typeStr = json["type"] as? String else {
            throw ProtocolError.missingField("type")
        }
        guard let type = CommandType(rawValue: typeStr) else {
            throw ProtocolError.unknownCommand(typeStr)
        }
        let payload = json["payload"] as? [String: Any] ?? [:]
        return (id, type, payload)
    }
}

enum ProtocolError: Error, CustomStringConvertible {
    case invalidJSON
    case missingField(String)
    case unknownCommand(String)

    var description: String {
        switch self {
        case .invalidJSON: return "Invalid JSON"
        case .missingField(let f): return "Missing field: \(f)"
        case .unknownCommand(let c): return "Unknown command: \(c)"
        }
    }
}
