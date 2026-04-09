// HandsFreeController.swift — Component BT-001.4
//
// THE CORE of the Bluetooth layer. Wraps IOBluetoothHandsFreeDevice to:
//   - Connect to a phone as an HFP Hands-Free unit (Mac = headset, phone = AG)
//   - Control calls: answer, reject, hang up, dial
//   - Route audio: transfer to computer (for capture) or phone
//   - Send/receive SMS via HFP AT commands
//
// HFP Roles:
//   - IOBluetoothHandsFreeDevice = Mac acts as HF (headset). This is what we use.
//   - IOBluetoothHandsFreeAudioGateway = Mac acts as AG (phone). NOT what we use.
//
// Delegate gotchas (discovered during development):
//   - connected: and disconnected: use IOBluetoothHandsFree! (base class)
//   - Call-specific delegates use IOBluetoothHandsFreeDevice! (subclass)
//   - Battery indicator constant is IOBluetoothHandsFreeIndicatorBattChg (not Battery)
//   - Signal indicator is IOBluetoothHandsFreeIndicatorSignal
//   - Both return Int32, not Int — cast explicitly
//   - send(atCommand:) was renamed from sendATCommand in a recent SDK
//
// Phone Amego (sustworks.com) insights:
//   - Don't release RFCOMM channel in disconnect() — macOS BT stack double-free bug
//   - Allow up to 40s for connection with patient retries
//   - Avoid loading Bluetooth SCO Audio Device driver (causes crashes)

import Foundation
import IOBluetooth

// Uses btPrint() from main.swift for file-based logging

/// Delegate for HFP call and connection events.
protocol HandsFreeControllerDelegate: AnyObject {
    func handsFreeDidConnect(_ controller: AnyObject, signal: Int, battery: Int)
    func handsFreeDidDisconnect(_ controller: AnyObject, reason: String)
    func handsFreeIncomingCall(_ controller: AnyObject, from: String, name: String?)
    func handsFreeCallActive(_ controller: AnyObject, from: String)
    func handsFreeCallEnded(_ controller: AnyObject, reason: String)
    func handsFreeIncomingSMS(_ controller: AnyObject, from: String, body: String, timestamp: String)
    func handsFreeSignalUpdate(_ controller: AnyObject, level: Int)
    func handsFreeBatteryUpdate(_ controller: AnyObject, level: Int)
    func handsFreeError(_ controller: AnyObject, code: String, message: String)
    func handsFree(_ controller: AnyObject, scoOpened codec: String, sampleRate: Int)
    func handsFree(_ controller: AnyObject, scoClosed: Bool)
    func handsFreeATLog(_ controller: AnyObject, direction: String, command: String)
    func handsFreeReconnecting(_ controller: AnyObject, attempt: Int, maxAttempts: Int)
}

/// Wraps IOBluetoothHandsFreeDevice for HFP connection and call control.
/// The Mac acts as the Hands-Free (HF) unit; the phone is the Audio Gateway (AG).
class HandsFreeController: NSObject {
    weak var delegate: HandsFreeControllerDelegate?

    private var hfDevice: IOBluetoothHandsFreeDevice?
    private var connectedAddress: String?

    // Connection timing for diagnostics
    private var connectTime: Date?

    // Auto-reconnect (Phone Amego allows ~40s with retries)
    private var autoReconnect = true
    private var reconnectAttempts = 0
    private let maxReconnectAttempts = 5
    private var reconnectDevice: IOBluetoothDevice?
    private var reconnectTimer: Timer?
    private var intentionalDisconnect = false

    // Keep-alive timer
    private var keepAliveTimer: Timer?

    // MARK: - Connection

    func connect(device: IOBluetoothDevice) {
        // Cancel any pending reconnect
        reconnectTimer?.invalidate()
        reconnectTimer = nil
        intentionalDisconnect = false
        connectTime = Date()

        // Log SDP services available on the device (HFP AG = 0x111F)
        if let services = device.services as? [IOBluetoothSDPServiceRecord] {
            btPrint("[HFP] Device has \(services.count) SDP service(s):")
            for record in services {
                let name = record.getServiceName() ?? "unnamed"
                btPrint("[HFP]   - \(name)")
            }
        } else {
            btPrint("[HFP] No cached SDP services (will query during connect)")
        }

        hfDevice = IOBluetoothHandsFreeDevice(device: device, delegate: self)

        // Set HFP HF supported features.
        // Phone Amego (sustworks.com) and real car stereos use 0x1F (bits 0-4), NOT 0xFF.
        // Setting bit 7 (codec negotiation) triggers mandatory AT+BAC/AT+BCS exchange that
        // IOBluetoothHandsFreeDevice may not complete, causing iPhone to timeout after 5s.
        // Bits: 0=EC/NR, 1=3-way, 2=CLI, 3=voice-rec, 4=volume-ctrl
        let features: UInt32 = 0x1F  // bits 0-4 only — no codec negotiation
        hfDevice?.supportedFeatures = features
        btPrint("[HFP] Set supported features: 0x\(String(features, radix: 16)) (\(features))")

        reconnectDevice = device

        // Explicitly open baseband (ACL) connection first — some setups require this
        // before IOBluetoothHandsFreeDevice.connect() will attempt RFCOMM
        if !device.isConnected() {
            btPrint("[HFP] Device not connected at baseband level, opening ACL connection...")
            let openResult = device.openConnection()
            btPrint("[HFP] openConnection() returned: \(openResult) (0=success)")
        } else {
            btPrint("[HFP] Device already connected at baseband level")
        }

        // Try to find the HFP AG service's RFCOMM channel from SDP
        var hfpChannelID: BluetoothRFCOMMChannelID = 0
        if let services = device.services as? [IOBluetoothSDPServiceRecord] {
            for record in services {
                let name = record.getServiceName() ?? ""
                if name.contains("Handsfree") || name.contains("HFP") {
                    var channelID: BluetoothRFCOMMChannelID = 0
                    let result = record.getRFCOMMChannelID(&channelID)
                    btPrint("[HFP] Service '\(name)' RFCOMM channel query: result=\(result), channel=\(channelID)")
                    if result == kIOReturnSuccess && channelID > 0 {
                        hfpChannelID = channelID
                    }
                }
            }
        }
        if hfpChannelID > 0 {
            btPrint("[HFP] Found HFP AG on RFCOMM channel \(hfpChannelID)")
        } else {
            btPrint("[HFP] WARNING: Could not find HFP RFCOMM channel from SDP!")
        }

        btPrint("[HFP] Calling hfDevice.connect()...")
        hfDevice?.connect()
        connectedAddress = device.addressString
        btPrint("[HFP] Connecting to \(device.addressString ?? "unknown") (attempt \(reconnectAttempts + 1)/\(maxReconnectAttempts + 1))")
        btPrint("[HFP] hfDevice is \(hfDevice == nil ? "nil" : "non-nil"), delegate is \(hfDevice?.delegate == nil ? "nil" : "set")")

        // Also try opening a raw RFCOMM channel as a diagnostic
        if hfpChannelID > 0 {
            btPrint("[HFP] Also attempting raw RFCOMM open on channel \(hfpChannelID) as diagnostic...")
            var rfcommChannel: IOBluetoothRFCOMMChannel? = nil
            let rfResult = device.openRFCOMMChannelAsync(&rfcommChannel, withChannelID: hfpChannelID, delegate: self)
            btPrint("[HFP] openRFCOMMChannelAsync result: \(rfResult) (0=success), channel=\(rfcommChannel == nil ? "nil" : "created")")
        }
    }

    func disconnect() {
        intentionalDisconnect = true
        autoReconnect = false
        reconnectTimer?.invalidate()
        reconnectTimer = nil
        keepAliveTimer?.invalidate()
        keepAliveTimer = nil

        hfDevice?.disconnect()
        // Do NOT nil hfDevice here — Phone Amego workaround for macOS BT stack
        // double-free bug. Let the disconnected: delegate handle cleanup.
        connectedAddress = nil
    }

    var isConnected: Bool {
        return hfDevice != nil && connectedAddress != nil
    }

    // MARK: - Call Control

    func answerCall() {
        hfDevice?.acceptCall()
    }

    func rejectCall() {
        hfDevice?.endCall()
    }

    func endCall() {
        hfDevice?.endCall()
    }

    func dial(number: String) {
        hfDevice?.dialNumber(number)
    }

    func sendDTMF(digit: String) {
        hfDevice?.sendDTMF(digit)
    }

    // MARK: - Audio

    func transferAudioToComputer() {
        hfDevice?.transferAudioToComputer()
    }

    func transferAudioToPhone() {
        hfDevice?.transferAudioToPhone()
    }

    // MARK: - SMS

    func sendSMS(to: String, body: String) {
        hfDevice?.sendSMS(to, message: body)
    }

    // MARK: - AT Commands

    func sendATCommand(_ command: String) {
        btPrint("[HFP] Sending AT command: \(command)")
        delegate?.handsFreeATLog(self, direction: "HF->AG", command: command)
        hfDevice?.send(atCommand: command)
    }

    // MARK: - Keep-Alive

    private func startKeepAlive() {
        keepAliveTimer?.invalidate()
        keepAliveTimer = Timer.scheduledTimer(withTimeInterval: 30.0, repeats: true) { [weak self] _ in
            guard let self = self, self.isConnected else { return }
            // Query indicators to keep connection alive
            self.hfDevice?.send(atCommand: "AT+CIND?\r")
            btPrint("[HFP] Keep-alive: AT+CIND?")
        }
    }

    // MARK: - Auto-Reconnect

    private func scheduleReconnect() {
        guard autoReconnect,
              !intentionalDisconnect,
              reconnectAttempts < maxReconnectAttempts,
              let device = reconnectDevice else {
            if reconnectAttempts >= maxReconnectAttempts {
                btPrint("[HFP] Max reconnect attempts (\(maxReconnectAttempts)) reached, giving up")
                delegate?.handsFreeError(self, code: "RECONNECT_EXHAUSTED",
                    message: "Failed to maintain SLC after \(maxReconnectAttempts) attempts")
            }
            return
        }

        reconnectAttempts += 1
        // Exponential backoff: 3s, 6s, 9s, 12s, 15s (~45s total, matching Phone Amego's ~40s)
        let delay = Double(reconnectAttempts) * 3.0
        btPrint("[HFP] Scheduling reconnect attempt \(reconnectAttempts)/\(maxReconnectAttempts) in \(delay)s")
        delegate?.handsFreeReconnecting(self, attempt: reconnectAttempts, maxAttempts: maxReconnectAttempts)

        reconnectTimer = Timer.scheduledTimer(withTimeInterval: delay, repeats: false) { [weak self] _ in
            guard let self = self else { return }
            btPrint("[HFP] Reconnect attempt \(self.reconnectAttempts)...")
            self.connect(device: device)
        }
    }
}

// MARK: - IOBluetoothHandsFreeDeviceDelegate

extension HandsFreeController: IOBluetoothHandsFreeDeviceDelegate, IOBluetoothRFCOMMChannelDelegate {
    // Called when HFP Service Level Connection is complete
    func handsFree(_ device: IOBluetoothHandsFree!, connected status: NSNumber!) {
        let elapsed = connectTime.map { Date().timeIntervalSince($0) } ?? -1
        let statusCode = status?.intValue ?? -1
        btPrint("[HFP] SLC connected! status=\(statusCode), elapsed=\(String(format: "%.1f", elapsed))s")

        let signal = Int(device.indicator(IOBluetoothHandsFreeIndicatorSignal))
        let battery = Int(device.indicator(IOBluetoothHandsFreeIndicatorBattChg))
        btPrint("[HFP] Connected (signal: \(signal), battery: \(battery))")

        // Reset reconnect counter on successful connection
        reconnectAttempts = 0

        // Start keep-alive timer
        startKeepAlive()

        delegate?.handsFreeDidConnect(self, signal: signal, battery: battery)
    }

    // Called when HFP Service Level Connection is disconnected
    func handsFree(_ device: IOBluetoothHandsFree!, disconnected status: NSNumber!) {
        let elapsed = connectTime.map { Date().timeIntervalSince($0) } ?? -1
        let statusCode = status?.intValue ?? -1
        btPrint("[HFP] SLC disconnected, status=\(statusCode), elapsed=\(String(format: "%.1f", elapsed))s, intentional=\(intentionalDisconnect)")

        keepAliveTimer?.invalidate()
        keepAliveTimer = nil

        // Now safe to nil out hfDevice (after BT stack is done with it)
        hfDevice = nil

        let reason = intentionalDisconnect
            ? "user_disconnect"
            : "disconnected(status=\(statusCode), elapsed=\(String(format: "%.1f", elapsed))s)"
        delegate?.handsFreeDidDisconnect(self, reason: reason)

        // Auto-reconnect if not intentional
        if !intentionalDisconnect {
            scheduleReconnect()
        }
    }

    func handsFree(_ device: IOBluetoothHandsFreeDevice!, incomingCallFrom number: String!) {
        let from = number ?? "Unknown"
        delegate?.handsFreeIncomingCall(self, from: from, name: nil)
        btPrint("[HFP] Incoming call from \(from)")
    }

    func handsFree(_ device: IOBluetoothHandsFreeDevice!, isCallActive: NSNumber!) {
        if isCallActive?.boolValue == true {
            delegate?.handsFreeCallActive(self, from: connectedAddress ?? "")
        }
    }

    func handsFree(_ device: IOBluetoothHandsFreeDevice!, callSetupMode: NSNumber!) {
        // 0 = no call setup, 1 = incoming, 2 = outgoing dialing, 3 = outgoing ringing
        btPrint("[HFP] Call setup mode: \(callSetupMode?.intValue ?? -1)")
        if callSetupMode?.intValue == 0 {
            delegate?.handsFreeCallEnded(self, reason: "remote_hangup")
        }
    }

    func handsFree(_ device: IOBluetoothHandsFreeDevice!, incomingSMS sms: [AnyHashable: Any]!) {
        guard let sms = sms else { return }
        let from = sms["PhoneNumber"] as? String ?? "Unknown"
        let body = sms["Content"] as? String ?? ""
        let timestamp = ISO8601DateFormatter().string(from: Date())
        delegate?.handsFreeIncomingSMS(self, from: from, body: body, timestamp: timestamp)
        btPrint("[HFP] SMS from \(from): \(body.prefix(50))")
    }

    func handsFree(_ device: IOBluetoothHandsFreeDevice!, signalStrength: NSNumber!) {
        let signal = signalStrength?.intValue ?? 0
        delegate?.handsFreeSignalUpdate(self, level: signal)
    }

    func handsFree(_ device: IOBluetoothHandsFreeDevice!, batteryCharge: NSNumber!) {
        let battery = batteryCharge?.intValue ?? 0
        delegate?.handsFreeBatteryUpdate(self, level: battery)
    }

    func handsFree(_ device: IOBluetoothHandsFree!, scoConnectionOpened status: NSNumber!) {
        delegate?.handsFree(self, scoOpened: "CVSD", sampleRate: 8000)
        btPrint("[HFP] SCO audio channel opened (base)")
    }

    func handsFree(_ device: IOBluetoothHandsFreeDevice!, scoConnectionOpened status: NSNumber!) {
        delegate?.handsFree(self, scoOpened: "CVSD", sampleRate: 8000)
        btPrint("[HFP] SCO audio channel opened (device)")
    }

    func handsFree(_ device: IOBluetoothHandsFree!, scoConnectionClosed status: NSNumber!) {
        delegate?.handsFree(self, scoClosed: true)
        btPrint("[HFP] SCO audio channel closed (base)")
    }

    func handsFree(_ device: IOBluetoothHandsFreeDevice!, scoConnectionClosed status: NSNumber!) {
        delegate?.handsFree(self, scoClosed: true)
        btPrint("[HFP] SCO audio channel closed (device)")
    }

    // MARK: - IOBluetoothRFCOMMChannelDelegate (diagnostic)

    func rfcommChannelOpenComplete(_ rfcommChannel: IOBluetoothRFCOMMChannel!, status error: IOReturn) {
        btPrint("[RFCOMM] Channel open complete! error=\(error) (0=success), channel=\(rfcommChannel?.getID() ?? 0)")
        if error == kIOReturnSuccess {
            btPrint("[RFCOMM] SUCCESS — raw RFCOMM channel is open! HFP RFCOMM works.")
            // Close it — we just wanted to test connectivity
            rfcommChannel?.close()
        } else {
            btPrint("[RFCOMM] FAILED — RFCOMM connection rejected (error \(error))")
        }
    }

    func rfcommChannelData(_ rfcommChannel: IOBluetoothRFCOMMChannel!, data dataPointer: UnsafeMutableRawPointer!, length dataLength: Int) {
        if let ptr = dataPointer {
            let data = Data(bytes: ptr, count: dataLength)
            if let str = String(data: data, encoding: .utf8) {
                btPrint("[RFCOMM] Data received: \(str.trimmingCharacters(in: .whitespacesAndNewlines))")
            } else {
                btPrint("[RFCOMM] Data received: \(dataLength) bytes (binary)")
            }
        }
    }

    func rfcommChannelClosed(_ rfcommChannel: IOBluetoothRFCOMMChannel!) {
        btPrint("[RFCOMM] Channel closed")
    }
}
