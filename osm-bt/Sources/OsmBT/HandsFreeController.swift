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
//   - Methods take IOBluetoothHandsFree! (base class), NOT IOBluetoothHandsFreeDevice!
//     If you use the wrong type, the method silently never gets called.
//   - Battery indicator constant is IOBluetoothHandsFreeIndicatorBattChg (not Battery)
//   - Signal indicator is IOBluetoothHandsFreeIndicatorSignal
//   - Both return Int32, not Int — cast explicitly
//   - send(atCommand:) was renamed from sendATCommand in a recent SDK
//
// NOT YET TESTED with real hardware — compiles against SDK headers.

import Foundation
import IOBluetooth

/// Delegate for HFP call and connection events.
protocol HandsFreeControllerDelegate: AnyObject {
    func handsFreeDidConnect(_ controller: HandsFreeController, signal: Int, battery: Int)
    func handsFreeDidDisconnect(_ controller: HandsFreeController, reason: String)
    func handsFreeIncomingCall(_ controller: HandsFreeController, from: String, name: String?)
    func handsFreeCallActive(_ controller: HandsFreeController, from: String)
    func handsFreeCallEnded(_ controller: HandsFreeController, reason: String)
    func handsFreeIncomingSMS(_ controller: HandsFreeController, from: String, body: String, timestamp: String)
    func handsFreeSignalUpdate(_ controller: HandsFreeController, level: Int)
    func handsFreeBatteryUpdate(_ controller: HandsFreeController, level: Int)
    func handsFreeError(_ controller: HandsFreeController, code: String, message: String)
    func handsFree(_ controller: HandsFreeController, scoOpened codec: String, sampleRate: Int)
    func handsFree(_ controller: HandsFreeController, scoClosed: Bool)
}

/// Wraps IOBluetoothHandsFreeDevice for HFP connection and call control.
/// The Mac acts as the Hands-Free (HF) unit; the phone is the Audio Gateway (AG).
class HandsFreeController: NSObject {
    weak var delegate: HandsFreeControllerDelegate?

    private var hfDevice: IOBluetoothHandsFreeDevice?
    private var connectedAddress: String?

    // MARK: - Connection

    func connect(device: IOBluetoothDevice) {
        hfDevice = IOBluetoothHandsFreeDevice(device: device, delegate: self)
        hfDevice?.connect()
        connectedAddress = device.addressString
        print("[HFP] Connecting to \(device.addressString ?? "unknown")")
    }

    func disconnect() {
        hfDevice?.disconnect()
        hfDevice = nil
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
        hfDevice?.send(atCommand: command)
    }
}

// MARK: - IOBluetoothHandsFreeDeviceDelegate

extension HandsFreeController: IOBluetoothHandsFreeDeviceDelegate {
    func handsFree(_ device: IOBluetoothHandsFree!, connected status: NSNumber!) {
        let isConnected = status?.boolValue ?? false
        if isConnected {
            let signal = Int(device.indicator(IOBluetoothHandsFreeIndicatorSignal))
            let battery = Int(device.indicator(IOBluetoothHandsFreeIndicatorBattChg))
            delegate?.handsFreeDidConnect(self, signal: signal, battery: battery)
            print("[HFP] Connected (signal: \(signal), battery: \(battery))")
        } else {
            delegate?.handsFreeDidDisconnect(self, reason: "disconnected")
            print("[HFP] Disconnected")
        }
    }

    func handsFree(_ device: IOBluetoothHandsFree!, incomingCallFrom number: NSNumber!) {
        let from = number?.stringValue ?? "Unknown"
        delegate?.handsFreeIncomingCall(self, from: from, name: nil)
        print("[HFP] Incoming call from \(from)")
    }

    func handsFree(_ device: IOBluetoothHandsFree!, isCallActive status: NSNumber!) {
        if status?.boolValue == true {
            delegate?.handsFreeCallActive(self, from: connectedAddress ?? "")
        }
    }

    func handsFree(_ device: IOBluetoothHandsFree!, callSetupMode mode: NSNumber!) {
        // 0 = no call setup, 1 = incoming, 2 = outgoing dialing, 3 = outgoing ringing
        if mode?.intValue == 0 {
            delegate?.handsFreeCallEnded(self, reason: "remote_hangup")
        }
    }

    func handsFree(_ device: IOBluetoothHandsFree!, incomingSMS sms: [AnyHashable: Any]!) {
        guard let sms = sms else { return }
        let from = sms["PhoneNumber"] as? String ?? "Unknown"
        let body = sms["Content"] as? String ?? ""
        let timestamp = ISO8601DateFormatter().string(from: Date())
        delegate?.handsFreeIncomingSMS(self, from: from, body: body, timestamp: timestamp)
        print("[HFP] SMS from \(from): \(body.prefix(50))")
    }

    func handsFree(_ device: IOBluetoothHandsFree!, signalStrength level: NSNumber!) {
        let signal = level?.intValue ?? 0
        delegate?.handsFreeSignalUpdate(self, level: signal)
    }

    func handsFree(_ device: IOBluetoothHandsFree!, batteryCharge level: NSNumber!) {
        let battery = level?.intValue ?? 0
        delegate?.handsFreeBatteryUpdate(self, level: battery)
    }

    func handsFree(_ device: IOBluetoothHandsFree!, scoConnectionOpened status: NSNumber!) {
        // SCO channel opened - voice audio is now flowing
        delegate?.handsFree(self, scoOpened: "CVSD", sampleRate: 8000)
        print("[HFP] SCO audio channel opened")
    }

    func handsFree(_ device: IOBluetoothHandsFree!, scoConnectionClosed status: NSNumber!) {
        delegate?.handsFree(self, scoClosed: true)
        print("[HFP] SCO audio channel closed")
    }
}
