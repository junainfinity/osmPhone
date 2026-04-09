// BluetoothManager.swift — Component BT-001.3
//
// Handles Bluetooth device discovery and pairing using IOBluetooth framework.
//
// Discovery: Uses IOBluetoothDeviceInquiry to scan for nearby classic BT devices.
//   The inquiry runs for 10 seconds by default. Each discovered device triggers
//   a delegate callback which gets forwarded as a "device_found" event.
//
// Pairing: Uses IOBluetoothDevicePair. The pairing flow:
//   1. Call pairDevice(address:) -> creates IOBluetoothDevicePair, starts pairing
//   2. If numeric comparison needed -> delegate fires pairConfirmRequired
//   3. User confirms via UI -> call confirmPairing(address:, confirmed:)
//   4. On success -> delegate fires didPairDevice
//
// IMPORTANT: These are classic Bluetooth operations, NOT BLE. IOBluetooth is
// separate from CoreBluetooth (which is BLE-only). Don't confuse the two.
//
// NOT YET TESTED with real hardware — compiles and delegate structure is correct.

import Foundation
import IOBluetooth

/// Delegate for Bluetooth discovery and pairing events.
protocol BluetoothManagerDelegate: AnyObject {
    func bluetoothManager(_ manager: BluetoothManager, didFindDevice address: String, name: String, rssi: Int)
    func bluetoothManagerScanComplete(_ manager: BluetoothManager)
    func bluetoothManager(_ manager: BluetoothManager, didPairDevice address: String, name: String)
    func bluetoothManager(_ manager: BluetoothManager, pairFailedForDevice address: String, error: String)
    func bluetoothManager(_ manager: BluetoothManager, pairConfirmRequired address: String, name: String, numericValue: UInt32)
}

/// Handles Bluetooth device discovery and pairing via IOBluetooth.
class BluetoothManager: NSObject {
    weak var delegate: BluetoothManagerDelegate?

    private var inquiry: IOBluetoothDeviceInquiry?
    private var currentPairing: IOBluetoothDevicePair?

    // MARK: - Discovery

    func startScan() {
        inquiry?.stop()
        inquiry = IOBluetoothDeviceInquiry(delegate: self)
        inquiry?.updateNewDeviceNames = true
        inquiry?.inquiryLength = 10 // seconds
        inquiry?.start()
        print("[BluetoothManager] Scan started")
    }

    func stopScan() {
        inquiry?.stop()
        inquiry = nil
        print("[BluetoothManager] Scan stopped")
    }

    // MARK: - Pairing

    func pairDevice(address: String) {
        guard let device = IOBluetoothDevice(addressString: address) else {
            delegate?.bluetoothManager(self, pairFailedForDevice: address, error: "Device not found")
            return
        }

        currentPairing = IOBluetoothDevicePair(device: device)
        currentPairing?.delegate = self
        currentPairing?.start()
        print("[BluetoothManager] Pairing with \(address)")
    }

    func confirmPairing(address: String, confirmed: Bool) {
        if confirmed {
            currentPairing?.replyUserConfirmation(true)
        } else {
            currentPairing?.replyUserConfirmation(false)
        }
    }

    /// Returns a paired device by address, or nil if not found/not paired.
    func pairedDevice(address: String) -> IOBluetoothDevice? {
        guard let device = IOBluetoothDevice(addressString: address) else { return nil }
        return device.isPaired() ? device : nil
    }
}

// MARK: - IOBluetoothDeviceInquiryDelegate

extension BluetoothManager: IOBluetoothDeviceInquiryDelegate {
    func deviceInquiryDeviceFound(_ sender: IOBluetoothDeviceInquiry!, device: IOBluetoothDevice!) {
        guard let device = device else { return }
        let address = device.addressString ?? "unknown"
        let name = device.name ?? "Unknown Device"
        let rssi = Int(device.rawRSSI())
        delegate?.bluetoothManager(self, didFindDevice: address, name: name, rssi: rssi)
    }

    func deviceInquiryComplete(_ sender: IOBluetoothDeviceInquiry!, error: IOReturn, aborted: Bool) {
        delegate?.bluetoothManagerScanComplete(self)
    }
}

// MARK: - IOBluetoothDevicePairDelegate

extension BluetoothManager: IOBluetoothDevicePairDelegate {
    func devicePairingFinished(_ sender: Any!, error: IOReturn) {
        guard let pair = sender as? IOBluetoothDevicePair,
              let device = pair.device() else { return }
        let address = device.addressString ?? "unknown"
        let name = device.name ?? "Unknown Device"

        if error == kIOReturnSuccess {
            delegate?.bluetoothManager(self, didPairDevice: address, name: name)
        } else {
            delegate?.bluetoothManager(self, pairFailedForDevice: address, error: "Pairing error: \(error)")
        }
        currentPairing = nil
    }

    func devicePairingUserConfirmationRequest(_ sender: Any!, numericValue: BluetoothNumericValue) {
        guard let pair = sender as? IOBluetoothDevicePair,
              let device = pair.device() else { return }
        let address = device.addressString ?? "unknown"
        let name = device.name ?? "Unknown Device"

        // Show the numeric code and confirm from Mac side after a brief delay.
        // The user MUST also tap Pair on the iPhone within ~30 seconds.
        // Previously we auto-confirmed immediately which raced with iPhone.
        btPrint("[BT] Pairing code: \(numericValue) — confirm on BOTH devices!")
        delegate?.bluetoothManager(self, pairConfirmRequired: address, name: name, numericValue: numericValue)

        // Confirm from Mac side after 3s delay (gives iPhone time to show its prompt)
        DispatchQueue.main.asyncAfter(deadline: .now() + 3.0) {
            btPrint("[BT] Mac confirming pairing code \(numericValue)")
            pair.replyUserConfirmation(true)
        }
    }
}
