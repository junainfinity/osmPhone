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
import os.log

let btLog = OSLog(subsystem: "com.osmphone.bt", category: "general")

// File logger — writes to /tmp/osmbt.log so we can see output when launched via `open`
let logFile = fopen("/tmp/osmbt.log", "w")
func btPrint(_ msg: String) {
    let line = "[\(ISO8601DateFormatter().string(from: Date()))] \(msg)\n"
    print(msg)
    if let f = logFile {
        fputs(line, f)
        fflush(f)
    }
}

/// osmPhone Bluetooth Helper
/// Runs as a daemon, exposing Bluetooth HFP functionality over a Unix domain socket.
/// Protocol: JSON-over-newline on /tmp/osmphone.sock

os_log("=== osm-bt starting ===", log: btLog, type: .default)
btPrint("=== osm-bt: osmPhone Bluetooth Helper ===")

// MARK: - App Coordinator

class AppCoordinator: NSObject, SocketServerDelegate, BluetoothManagerDelegate, HandsFreeControllerDelegate {
    let socketServer: SocketServer
    let bluetoothManager: BluetoothManager
    let handsFreeController: HandsFreeController
    let rfcommHFP: RFCOMMHandsFreeController
    let smsController: SMSController
    let audioBridge: SCOAudioBridge

    // Toggle between RFCOMM (raw) and IOBluetooth (framework) HFP controllers
    let useRFCOMM = true  // Try IOBluetooth again with fresh pairing

    override init() {
        socketServer = SocketServer()
        bluetoothManager = BluetoothManager()
        handsFreeController = HandsFreeController()
        rfcommHFP = RFCOMMHandsFreeController()
        smsController = SMSController(controller: handsFreeController)
        audioBridge = SCOAudioBridge()

        super.init()

        socketServer.delegate = self
        bluetoothManager.delegate = self
        handsFreeController.delegate = self
        rfcommHFP.delegate = self

        audioBridge.onAudioCaptured = { [weak self] data, sampleRate in
            self?.handleCapturedAudio(data: data, sampleRate: sampleRate)
        }
    }

    func start() throws {
        try socketServer.start()

        // Try to set device class to Audio/Headset
        btPrint("[App] Attempting to set Bluetooth device class to Audio/Headset...")
        let classChanged = trySetAudioDeviceClass()
        btPrint("[App] Device class change: \(classChanged ? "SUCCESS" : "FAILED (will try anyway)")")

        // Start RFCOMM HFP advertising (makes Mac visible as a headset)
        if useRFCOMM {
            btPrint("[App] Starting RFCOMM-based HFP (Mac advertises as headset)...")
            let ok = rfcommHFP.startAdvertising()
            btPrint("[App] RFCOMM HFP advertising: \(ok ? "ACTIVE" : "FAILED")")
        }

        // List already-paired devices at startup
        if let paired = IOBluetoothDevice.pairedDevices() as? [IOBluetoothDevice] {
            print("[App] Found \(paired.count) paired device(s):")
            for d in paired {
                print("  - \(d.name ?? "?") (\(d.addressString ?? "?")) paired=\(d.isPaired())")
            }
        } else {
            print("[App] No paired devices found")
        }

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
            print("[App] scan_start received")
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
            if let address = payload["address"] as? String {
                btPrint("[App] connect_hfp requested for \(address) (mode: \(useRFCOMM ? "RFCOMM" : "IOBluetooth"))")

                // Find the device
                let device: IOBluetoothDevice?
                if let d = bluetoothManager.pairedDevice(address: address) {
                    btPrint("[App] Device via pairedDevice(): name=\(d.name ?? "?"), paired=\(d.isPaired()), connected=\(d.isConnected())")
                    device = d
                } else if let d = IOBluetoothDevice(addressString: address) {
                    btPrint("[App] Device via direct lookup: name=\(d.name ?? "?"), paired=\(d.isPaired()), connected=\(d.isConnected())")
                    device = d
                } else {
                    btPrint("[App] Device not found at \(address)")
                    let errPayload = ErrorPayload(code: "DEVICE_NOT_FOUND", message: "No device at \(address)")
                    if let data = try? EventBuilder.build(type: .error, payload: errPayload) {
                        socketServer.sendEvent(data)
                    }
                    device = nil
                }

                if let device = device {
                    if useRFCOMM {
                        // RFCOMM mode: Mac advertises as headset, iPhone connects to us
                        // The connect() call opens ACL to prompt iPhone's service discovery
                        rfcommHFP.connect(device: device)
                    } else {
                        handsFreeController.connect(device: device)
                    }
                }
            }

        case .disconnectHFP:
            if useRFCOMM { rfcommHFP.disconnect() } else { handsFreeController.disconnect() }

        case .answerCall:
            if useRFCOMM { rfcommHFP.answerCall() } else { handsFreeController.answerCall(); handsFreeController.transferAudioToComputer() }

        case .rejectCall:
            if useRFCOMM { rfcommHFP.rejectCall() } else { handsFreeController.rejectCall() }

        case .endCall:
            if useRFCOMM { rfcommHFP.endCall() } else { handsFreeController.endCall() }

        case .dial:
            if let number = payload["number"] as? String {
                if useRFCOMM { rfcommHFP.dial(number: number) } else { handsFreeController.dial(number: number) }
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

        case .unpair:
            if let address = payload["address"] as? String {
                if let device = IOBluetoothDevice(addressString: address) {
                    let result = device.removeFromFavorites()
                    print("[App] removeFromFavorites for \(address): \(result)")
                    // Also try to close any open connections
                    device.closeConnection()
                    let payload = ["address": address, "result": "\(result)"]
                    if let data = try? EventBuilder.build(type: .paired, payload: payload) {
                        socketServer.sendEvent(data)
                    }
                }
            }

        case .listPaired:
            if let paired = IOBluetoothDevice.pairedDevices() as? [IOBluetoothDevice] {
                for d in paired {
                    let payload = DeviceFoundPayload(
                        address: d.addressString ?? "?",
                        name: d.name ?? "Unknown",
                        rssi: Int(d.rawRSSI())
                    )
                    if let data = try? EventBuilder.build(type: .deviceFound, payload: payload) {
                        socketServer.sendEvent(data)
                    }
                }
            }
            if let data = try? EventBuilder.build(type: .scanComplete, payload: [String: String]()) {
                socketServer.sendEvent(data)
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

    func handsFreeDidConnect(_ controller: AnyObject, signal: Int, battery: Int) {
        let payload = HFPConnectedPayload(address: "", signal: signal, battery: battery, service: true)
        if let data = try? EventBuilder.build(type: .hfpConnected, payload: payload) {
            socketServer.sendEvent(data)
        }
    }

    func handsFreeDidDisconnect(_ controller: AnyObject, reason: String) {
        let payload: [String: String] = ["reason": reason]
        if let data = try? EventBuilder.build(type: .hfpDisconnected, payload: payload) {
            socketServer.sendEvent(data)
        }
    }

    func handsFreeIncomingCall(_ controller: AnyObject, from: String, name: String?) {
        let payload = IncomingCallPayload(from: from, name: name)
        if let data = try? EventBuilder.build(type: .incomingCall, payload: payload) {
            socketServer.sendEvent(data)
        }
    }

    func handsFreeCallActive(_ controller: AnyObject, from: String) {
        let payload: [String: String] = ["from": from]
        if let data = try? EventBuilder.build(type: .callActive, payload: payload) {
            socketServer.sendEvent(data)
        }
    }

    func handsFreeCallEnded(_ controller: AnyObject, reason: String) {
        let payload = CallEndedPayload(reason: reason)
        if let data = try? EventBuilder.build(type: .callEnded, payload: payload) {
            socketServer.sendEvent(data)
        }
    }

    func handsFreeIncomingSMS(_ controller: AnyObject, from: String, body: String, timestamp: String) {
        let payload = SMSReceivedPayload(from: from, body: body, timestamp: timestamp)
        if let data = try? EventBuilder.build(type: .smsReceived, payload: payload) {
            socketServer.sendEvent(data)
        }
    }

    func handsFreeSignalUpdate(_ controller: AnyObject, level: Int) {
        let payload: [String: Int] = ["level": level]
        if let data = try? EventBuilder.build(type: .signalUpdate, payload: payload) {
            socketServer.sendEvent(data)
        }
    }

    func handsFreeBatteryUpdate(_ controller: AnyObject, level: Int) {
        let payload: [String: Int] = ["level": level]
        if let data = try? EventBuilder.build(type: .batteryUpdate, payload: payload) {
            socketServer.sendEvent(data)
        }
    }

    func handsFreeError(_ controller: AnyObject, code: String, message: String) {
        let payload = ErrorPayload(code: code, message: message)
        if let data = try? EventBuilder.build(type: .error, payload: payload) {
            socketServer.sendEvent(data)
        }
    }

    func handsFree(_ controller: AnyObject, scoOpened codec: String, sampleRate: Int) {
        let payload = SCOOpenedPayload(codec: codec, sampleRate: sampleRate)
        if let data = try? EventBuilder.build(type: .scoOpened, payload: payload) {
            socketServer.sendEvent(data)
        }
        audioBridge.startCapture(sampleRate: sampleRate)
    }

    func handsFree(_ controller: AnyObject, scoClosed: Bool) {
        if let data = try? EventBuilder.build(type: .scoClosed, payload: [String: String]()) {
            socketServer.sendEvent(data)
        }
        audioBridge.stopCapture()
    }

    func handsFreeATLog(_ controller: AnyObject, direction: String, command: String) {
        let payload = ATLogPayload(
            direction: direction,
            command: command,
            timestamp: ISO8601DateFormatter().string(from: Date())
        )
        if let data = try? EventBuilder.build(type: .atLog, payload: payload) {
            socketServer.sendEvent(data)
        }
    }

    func handsFreeReconnecting(_ controller: AnyObject, attempt: Int, maxAttempts: Int) {
        let payload = HFPReconnectingPayload(
            address: "",
            attempt: attempt,
            maxAttempts: maxAttempts
        )
        if let data = try? EventBuilder.build(type: .hfpReconnecting, payload: payload) {
            socketServer.sendEvent(data)
        }
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
