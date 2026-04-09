// SMSController.swift — Component BT-001.6
//
// Thin wrapper around HandsFreeController's sendSMS method.
// SMS receiving is handled by the HandsFreeController delegate (incomingSMS:).
// This class exists to encapsulate send-side validation (e.g., 160-char limit).
//
// HFP SMS limitations:
//   - Max 160 characters per message (some phones silently truncate)
//   - Unicode support varies by phone AG implementation
//   - Not all phones expose SMS over HFP — test with your specific device
//   - For richer SMS access, MAP (Message Access Profile) over OBEX is needed
//     (not yet implemented — would be a separate component)

import Foundation

/// Handles SMS operations through the HFP connection.
/// Uses IOBluetoothHandsFreeDevice's sendSMS and incomingSMS delegate.
/// This is a thin coordinator that delegates to HandsFreeController.
class SMSController {
    private weak var hfController: HandsFreeController?

    init(controller: HandsFreeController) {
        self.hfController = controller
    }

    /// Send an SMS through the connected phone.
    func send(to: String, body: String) {
        guard let hf = hfController, hf.isConnected else {
            print("[SMS] Cannot send: not connected")
            return
        }

        // HFP SMS has a 160 character limit for single messages
        if body.count > 160 {
            print("[SMS] Warning: message exceeds 160 chars, may be truncated by some phones")
        }

        hf.sendSMS(to: to, body: body)
        print("[SMS] Sent to \(to): \(body.prefix(50))...")
    }
}
