// main.swift — Component BT-001.7
//
// Entry point for the osm-bt Swift process. Creates and wires all components:
//   SocketServer <-> AppCoordinator <-> BluetoothManager
//                                   <-> HandsFreeController
//                                   <-> SMSController
//                                   <-> SCOAudioBridge
//
// AppCoordinator is the central hub — it implements all delegate protocols
// and translates between socket commands/events and Bluetooth actions.
//
// Lifecycle:
//   1. Start socket server on /tmp/osmphone.sock
//   2. Wait for osm-core (Python) to connect
//   3. Process commands from osm-core, emit events back
//   4. RunLoop.main.run() keeps the process alive (required for IOBluetooth delegates)
//   5. SIGINT/SIGTERM triggers clean shutdown
//
// To run: cd osm-bt && swift run OsmBT
// To build release: cd osm-bt && swift build -c release

import Foundation
import IOBluetooth

/// osmPhone Bluetooth Helper
/// Runs as a daemon, exposing Bluetooth HFP functionality over a Unix domain socket.
/// Protocol: JSON-over-newline on /tmp/osmphone.sock

print("=== osm-bt: osmPhone Bluetooth Helper ===")

// MARK: - App Coordinator

class AppCoordinator: NSObject, SocketServerDelegate, BluetoothManagerDelegate, HandsFreeControllerDelegate {
    let socketServer: SocketServer
    let bluetoothManager: BluetoothManager
    let handsFreeController: HandsFreeController
    let smsController: SMSController
    let audioBridge: SCOAudioBridge

    override init() {
        socketServer = SocketServer()
        bluetoothManager = BluetoothManager()
        handsFreeController = HandsFreeController()
        smsController = SMSController(controller: handsFreeController)
        audioBridge = SCOAudioBridge()

        super.init()

        socketServer.delegate = self
        bluetoothManager.delegate = self
        handsFreeController.delegate = self

        audioBridge.onAudioCaptured = { [weak self] data, sampleRate in
            self?.handleCapturedAudio(data: data, sampleRate: sampleRate)
        }
    }

    func start() throws {
        try socketServer.start()
        print("[App] Ready. Waiting for osm-core to connect...")
    }

    func stop() {
        audioBridge.stopCapture()
        handsFreeController.disconnect()
        socketServer.stop()
        print("[App] Stopped")
    }

    // MARK: - Audio Handling

    private func handleCapturedAudio(data: Data, sampleRate: Int) {
        let payload = SCOAudioPayload(
            codec: "CVSD",
            sampleRate: sampleRate,
            data: data.base64EncodedString()
        )
        if let eventData = try? EventBuilder.build(type: .scoAudio, payload: payload) {
            socketServer.sendEvent(eventData)
        }
    }

    // MARK: - SocketServerDelegate

    func socketServer(_ server: SocketServer, didReceiveCommand id: String, type: CommandType, payload: [String: Any]) {
        switch type {
        case .scanStart:
            bluetoothManager.startScan()

        case .scanStop:
            bluetoothManager.stopScan()

        case .pair:
            if let address = payload["address"] as? String {
                bluetoothManager.pairDevice(address: address)
            }

        case .pairConfirm:
            if let address = payload["address"] as? String,
               let confirmed = payload["confirmed"] as? Bool {
                bluetoothManager.confirmPairing(address: address, confirmed: confirmed)
            }

        case .connectHFP:
            if let address = payload["address"] as? String,
               let device = bluetoothManager.pairedDevice(address: address) {
                handsFreeController.connect(device: device)
            }

        case .disconnectHFP:
            handsFreeController.disconnect()

        case .answerCall:
            handsFreeController.answerCall()
            handsFreeController.transferAudioToComputer()

        case .rejectCall:
            handsFreeController.rejectCall()

        case .endCall:
            handsFreeController.endCall()

        case .dial:
            if let number = payload["number"] as? String {
                handsFreeController.dial(number: number)
            }

        case .sendSMS:
            if let to = payload["to"] as? String,
               let body = payload["body"] as? String {
                smsController.send(to: to, body: body)
            }

        case .injectAudio:
            if let dataStr = payload["data"] as? String,
               let data = Data(base64Encoded: dataStr),
               let sampleRate = payload["sample_rate"] as? Int {
                audioBridge.injectAudio(pcmData: data, sampleRate: sampleRate)
            }

        case .transferAudio:
            if let target = payload["target"] as? String {
                if target == "computer" {
                    handsFreeController.transferAudioToComputer()
                } else {
                    handsFreeController.transferAudioToPhone()
                }
            }

        case .sendDTMF:
            if let digit = payload["digit"] as? String {
                handsFreeController.sendDTMF(digit: digit)
            }
        }
    }

    func socketServerClientConnected(_ server: SocketServer) {
        print("[App] osm-core connected")
    }

    func socketServerClientDisconnected(_ server: SocketServer) {
        print("[App] osm-core disconnected")
    }

    // MARK: - BluetoothManagerDelegate

    func bluetoothManager(_ manager: BluetoothManager, didFindDevice address: String, name: String, rssi: Int) {
        let payload = DeviceFoundPayload(address: address, name: name, rssi: rssi)
        if let data = try? EventBuilder.build(type: .deviceFound, payload: payload) {
            socketServer.sendEvent(data)
        }
    }

    func bluetoothManagerScanComplete(_ manager: BluetoothManager) {
        if let data = try? EventBuilder.build(type: .scanComplete, payload: [String: String]()) {
            socketServer.sendEvent(data)
        }
    }

    func bluetoothManager(_ manager: BluetoothManager, didPairDevice address: String, name: String) {
        let payload = PairedPayload(address: address, name: name)
        if let data = try? EventBuilder.build(type: .paired, payload: payload) {
            socketServer.sendEvent(data)
        }
    }

    func bluetoothManager(_ manager: BluetoothManager, pairFailedForDevice address: String, error: String) {
        let payload = ErrorPayload(code: "PAIR_FAILED", message: error)
        if let data = try? EventBuilder.build(type: .pairFailed, payload: payload) {
            socketServer.sendEvent(data)
        }
    }

    func bluetoothManager(_ manager: BluetoothManager, pairConfirmRequired address: String, name: String, numericValue: UInt32) {
        let payload = PairConfirmPayload(address: address, name: name, numericValue: numericValue)
        if let data = try? EventBuilder.build(type: .pairConfirm, payload: payload) {
            socketServer.sendEvent(data)
        }
    }

    // MARK: - HandsFreeControllerDelegate

    func handsFreeDidConnect(_ controller: HandsFreeController, signal: Int, battery: Int) {
        let payload = HFPConnectedPayload(address: "", signal: signal, battery: battery, service: true)
        if let data = try? EventBuilder.build(type: .hfpConnected, payload: payload) {
            socketServer.sendEvent(data)
        }
    }

    func handsFreeDidDisconnect(_ controller: HandsFreeController, reason: String) {
        let payload: [String: String] = ["reason": reason]
        if let data = try? EventBuilder.build(type: .hfpDisconnected, payload: payload) {
            socketServer.sendEvent(data)
        }
    }

    func handsFreeIncomingCall(_ controller: HandsFreeController, from: String, name: String?) {
        let payload = IncomingCallPayload(from: from, name: name)
        if let data = try? EventBuilder.build(type: .incomingCall, payload: payload) {
            socketServer.sendEvent(data)
        }
    }

    func handsFreeCallActive(_ controller: HandsFreeController, from: String) {
        let payload: [String: String] = ["from": from]
        if let data = try? EventBuilder.build(type: .callActive, payload: payload) {
            socketServer.sendEvent(data)
        }
    }

    func handsFreeCallEnded(_ controller: HandsFreeController, reason: String) {
        let payload = CallEndedPayload(reason: reason)
        if let data = try? EventBuilder.build(type: .callEnded, payload: payload) {
            socketServer.sendEvent(data)
        }
    }

    func handsFreeIncomingSMS(_ controller: HandsFreeController, from: String, body: String, timestamp: String) {
        let payload = SMSReceivedPayload(from: from, body: body, timestamp: timestamp)
        if let data = try? EventBuilder.build(type: .smsReceived, payload: payload) {
            socketServer.sendEvent(data)
        }
    }

    func handsFreeSignalUpdate(_ controller: HandsFreeController, level: Int) {
        let payload: [String: Int] = ["level": level]
        if let data = try? EventBuilder.build(type: .signalUpdate, payload: payload) {
            socketServer.sendEvent(data)
        }
    }

    func handsFreeBatteryUpdate(_ controller: HandsFreeController, level: Int) {
        let payload: [String: Int] = ["level": level]
        if let data = try? EventBuilder.build(type: .batteryUpdate, payload: payload) {
            socketServer.sendEvent(data)
        }
    }

    func handsFreeError(_ controller: HandsFreeController, code: String, message: String) {
        let payload = ErrorPayload(code: code, message: message)
        if let data = try? EventBuilder.build(type: .error, payload: payload) {
            socketServer.sendEvent(data)
        }
    }

    func handsFree(_ controller: HandsFreeController, scoOpened codec: String, sampleRate: Int) {
        let payload = SCOOpenedPayload(codec: codec, sampleRate: sampleRate)
        if let data = try? EventBuilder.build(type: .scoOpened, payload: payload) {
            socketServer.sendEvent(data)
        }
        audioBridge.startCapture(sampleRate: sampleRate)
    }

    func handsFree(_ controller: HandsFreeController, scoClosed: Bool) {
        if let data = try? EventBuilder.build(type: .scoClosed, payload: [String: String]()) {
            socketServer.sendEvent(data)
        }
        audioBridge.stopCapture()
    }
}

// MARK: - Signal handling

let coordinator = AppCoordinator()

signal(SIGINT) { _ in
    coordinator.stop()
    exit(0)
}
signal(SIGTERM) { _ in
    coordinator.stop()
    exit(0)
}

// Start
do {
    try coordinator.start()
} catch {
    print("[App] Failed to start: \(error)")
    exit(1)
}

// Run the main RunLoop (required for IOBluetooth delegate callbacks)
RunLoop.main.run()
