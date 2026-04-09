// RFCOMMHandsFreeController.swift — Component BT-001.4b
//
// Raw RFCOMM implementation of HFP Hands-Free unit.
// Instead of using IOBluetoothHandsFreeDevice (which fails silently because
// iPhones refuse incoming RFCOMM connections from Macs), this controller:
//
//   1. Publishes an SDP service record advertising as HFP HF (UUID 0x111E)
//   2. Listens for incoming RFCOMM connections from the iPhone (AG)
//   3. Implements the AT command state machine for SLC establishment
//   4. Handles call control, indicators, and Apple extensions
//
// This mimics what Phone Amego does — making the Mac "look like a headset"
// so the iPhone connects TO us rather than us connecting to it.
//
// Same HandsFreeControllerDelegate protocol — drop-in replacement.

import Foundation
import IOBluetooth

class RFCOMMHandsFreeController: NSObject {
    weak var delegate: HandsFreeControllerDelegate?

    // SDP & RFCOMM
    private var sdpServiceRecord: IOBluetoothSDPServiceRecord?
    private var rfcommChannel: IOBluetoothRFCOMMChannel?
    private var channelNotification: IOBluetoothUserNotification?
    private var rfcommChannelID: BluetoothRFCOMMChannelID = 0

    // Connection state
    private var connectedDevice: IOBluetoothDevice?
    private var connectedAddress: String?
    private var connectTime: Date?

    // SLC state machine
    enum SLCState: String {
        case idle
        case rfcommOpen          // RFCOMM channel open, waiting to start
        case waitingBRSFResponse // Sent AT+BRSF, waiting for +BRSF
        case waitingCINDTest     // Sent AT+CIND=?, waiting for +CIND
        case waitingCINDRead     // Sent AT+CIND?, waiting for +CIND values
        case waitingCMER         // Sent AT+CMER, waiting for OK
        case waitingCHLD         // Sent AT+CHLD=?, waiting for +CHLD
        case slcEstablished      // SLC complete
        case appleExtensions     // Sending AT+XAPL
    }
    private var slcState: SLCState = .idle

    // AG features (from +BRSF response)
    private var agFeatures: UInt32 = 0

    // HF features we advertise
    // Bits: 0=EC/NR, 1=3-way, 2=CLI, 3=voice-rec, 4=volume
    private let hfFeatures: UInt32 = 0x1F

    // Indicators from AG
    private var indicatorNames: [String] = []
    private var indicatorValues: [Int] = []

    // AT command buffer
    private var atBuffer = ""

    // Keep-alive
    private var keepAliveTimer: Timer?

    // Auto-reconnect
    private var autoReconnect = true
    private var reconnectAttempts = 0
    private let maxReconnectAttempts = 5

    // MARK: - Public API

    /// Publish SDP record and start listening for incoming RFCOMM connections.
    /// Call this once at startup. The iPhone will find us and connect.
    func startAdvertising() -> Bool {
        btPrint("[RFCOMM-HFP] Publishing HFP Hands-Free SDP service record...")

        // Try multiple SDP dictionary formats to find one that works.
        // Apple's API is poorly documented — format varies by macOS version.

        // Publish BOTH HSP Headset and HFP Hands-Free SDP records.
        // HSP (Headset Profile) is simpler — iPhone may be more willing to
        // activate audio for a basic headset than a full HFP device.
        //
        // HSP UUIDs: 0x1108 (Headset), 0x1131 (Headset-HS)
        // HFP UUID: 0x111E (Handsfree)
        // Generic Audio: 0x1203

        // Record 1: HSP Headset (simpler, more likely to work)
        let hspDict: [String: Any] = [
            "0001 - ServiceClassIDList": [
                IOBluetoothSDPUUID(uuid16: 0x1131)!,  // Headset-HS
                IOBluetoothSDPUUID(uuid16: 0x1203)!   // GenericAudio
            ],
            "0004 - ProtocolDescriptorList": [
                [IOBluetoothSDPUUID(uuid16: 0x0100)!],  // L2CAP
                [IOBluetoothSDPUUID(uuid16: 0x0003)!]   // RFCOMM
            ],
            "0100 - Service Name": "osmPhone Headset"
        ]

        btPrint("[RFCOMM-HFP] Publishing HSP Headset SDP record...")
        sdpServiceRecord = IOBluetoothSDPServiceRecord.publishedServiceRecord(with: hspDict)

        if sdpServiceRecord != nil {
            btPrint("[RFCOMM-HFP] HSP record published successfully")
        } else {
            btPrint("[RFCOMM-HFP] HSP failed, trying HFP...")
            // Fallback: HFP record
            let hfpDict: [String: Any] = [
                "0001 - ServiceClassIDList": [
                    IOBluetoothSDPUUID(uuid16: 0x111E)!,  // Handsfree
                    IOBluetoothSDPUUID(uuid16: 0x1203)!   // GenericAudio
                ],
                "0004 - ProtocolDescriptorList": [
                    [IOBluetoothSDPUUID(uuid16: 0x0100)!],
                    [IOBluetoothSDPUUID(uuid16: 0x0003)!]
                ],
                "0100 - Service Name": "osmPhone Hands-Free"
            ]
            sdpServiceRecord = IOBluetoothSDPServiceRecord.publishedServiceRecord(with: hfpDict)
        }

        btPrint("[RFCOMM-HFP] SDP result: \(sdpServiceRecord == nil ? "FAILED" : "SUCCESS")")
        guard let record = sdpServiceRecord else {
            btPrint("[RFCOMM-HFP] ERROR: Failed to publish SDP service record")
            return false
        }

        // Skip getRFCOMMChannelID — it crashes with NSRangeException on minimal
        // SDP records that don't specify a channel number. Just listen on channel 0
        // (any incoming channel) which is safer.
        var channelID: BluetoothRFCOMMChannelID = 0
        // channelID stays 0 = listen on all channels
        btPrint("[RFCOMM-HFP] SDP published (skipping getRFCOMMChannelID to avoid crash)")
        btPrint("[RFCOMM-HFP] Listening on channel 0 (any incoming channel)")

        // Listen for incoming RFCOMM connections
        // Use channelID 0 to listen on ANY channel if we don't have a specific one
        channelNotification = IOBluetoothRFCOMMChannel.register(
            forChannelOpenNotifications: self,
            selector: #selector(rfcommChannelOpened(_:channel:)),
            withChannelID: rfcommChannelID,
            direction: kIOBluetoothUserNotificationChannelDirectionIncoming
        )

        if channelNotification != nil {
            btPrint("[RFCOMM-HFP] Listening for incoming RFCOMM connections (channel \(rfcommChannelID))")
        } else {
            btPrint("[RFCOMM-HFP] WARNING: Failed to register for RFCOMM notifications")
        }

        btPrint("[RFCOMM-HFP] Ready. iPhone should see 'osmPhone Hands-Free' in Bluetooth devices.")
        return true
    }

    /// Stop advertising and close any active connection.
    func stopAdvertising() {
        channelNotification?.unregister()
        channelNotification = nil
        _ = sdpServiceRecord?.remove()
        sdpServiceRecord = nil
        disconnect()
        btPrint("[RFCOMM-HFP] Stopped advertising")
    }

    /// Connect to the iPhone's HFP Audio Gateway service via direct RFCOMM.
    /// Queries SDP for the Handsfree Gateway service and opens the RFCOMM channel.
    /// This is what Phone Amego does: connect TO the AG, not wait for it.
    func connect(device: IOBluetoothDevice) {
        btPrint("[RFCOMM-HFP] connect() — direct RFCOMM to iPhone's HFP AG")

        connectedDevice = device
        connectTime = Date()
        reconnectAttempts = 0

        // Ensure SDP service is published (so iPhone sees us as HF)
        if sdpServiceRecord == nil {
            _ = startAdvertising()
        }

        // Open ACL if needed
        if !device.isConnected() {
            btPrint("[RFCOMM-HFP] Opening ACL connection...")
            let aclResult = device.openConnection()
            btPrint("[RFCOMM-HFP] ACL result: \(aclResult) (0=success)")
            if aclResult != kIOReturnSuccess {
                delegate?.handsFreeError(self, code: "ACL_FAILED", message: "ACL connection failed: \(aclResult)")
                return
            }
        }

        // Find HFP AG RFCOMM channel via SDP
        var targetChannel: BluetoothRFCOMMChannelID = 0
        if let services = device.services as? [IOBluetoothSDPServiceRecord] {
            for record in services {
                let name = record.getServiceName() ?? ""
                if name.contains("Handsfree") || name.contains("HFP") {
                    var ch: BluetoothRFCOMMChannelID = 0
                    if record.getRFCOMMChannelID(&ch) == kIOReturnSuccess && ch > 0 {
                        targetChannel = ch
                        btPrint("[RFCOMM-HFP] Found '\(name)' on RFCOMM channel \(ch)")
                        break
                    }
                }
            }
        }

        // Log ALL services with their channels
        if let allServices = device.services as? [IOBluetoothSDPServiceRecord] {
            btPrint("[RFCOMM-HFP] ALL SDP services on iPhone:")
            for record in allServices {
                let name = record.getServiceName() ?? "(unnamed)"
                var ch: BluetoothRFCOMMChannelID = 0
                let chResult = record.getRFCOMMChannelID(&ch)
                btPrint("[RFCOMM-HFP]   '\(name)' RFCOMM=\(chResult == kIOReturnSuccess ? "\(ch)" : "n/a")")
            }
        }

        if targetChannel == 0 {
            btPrint("[RFCOMM-HFP] No HFP AG service found via SDP, performing SDP query...")
            // Perform fresh SDP query
            let sdpResult = device.performSDPQuery(nil)
            btPrint("[RFCOMM-HFP] SDP query result: \(sdpResult)")
            // Retry after query
            if let services = device.services as? [IOBluetoothSDPServiceRecord] {
                for record in services {
                    let name = record.getServiceName() ?? ""
                    var ch: BluetoothRFCOMMChannelID = 0
                    if record.getRFCOMMChannelID(&ch) == kIOReturnSuccess && ch > 0 {
                        btPrint("[RFCOMM-HFP] SDP service: '\(name)' channel=\(ch)")
                        if name.contains("Handsfree") || name.contains("HFP") {
                            targetChannel = ch
                        }
                    }
                }
            }
        }

        if targetChannel == 0 {
            // Default to channel 8 (what we discovered earlier)
            targetChannel = 8
            btPrint("[RFCOMM-HFP] Using default HFP channel \(targetChannel)")
        }

        btPrint("[RFCOMM-HFP] Opening RFCOMM channel \(targetChannel) to iPhone AG...")
        var channel: IOBluetoothRFCOMMChannel? = nil
        let rfResult = device.openRFCOMMChannelAsync(&channel, withChannelID: targetChannel, delegate: self)
        btPrint("[RFCOMM-HFP] openRFCOMMChannelAsync: result=\(rfResult), channel=\(channel == nil ? "nil" : "created")")

        if rfResult == kIOReturnSuccess, let ch = channel {
            rfcommChannel = ch
            btPrint("[RFCOMM-HFP] RFCOMM channel opened, waiting for completion callback...")
        } else {
            btPrint("[RFCOMM-HFP] RFCOMM open failed: \(rfResult)")
            delegate?.handsFreeError(self, code: "RFCOMM_FAILED", message: "RFCOMM open failed: \(rfResult)")
        }
    }

    func disconnect() {
        autoReconnect = false
        keepAliveTimer?.invalidate()
        keepAliveTimer = nil
        rfcommChannel?.close()
        rfcommChannel = nil
        connectedDevice = nil
        connectedAddress = nil
        slcState = .idle
    }

    var isConnected: Bool {
        return slcState == .slcEstablished || slcState == .appleExtensions
    }

    // MARK: - Call Control

    func answerCall() { sendAT("ATA") }
    func rejectCall() { sendAT("AT+CHUP") }
    func endCall() { sendAT("AT+CHUP") }
    func dial(number: String) { sendAT("ATD\(number);") }
    func sendDTMF(digit: String) { sendAT("AT+VTS=\(digit)") }

    func transferAudioToComputer() {
        // Request SCO audio transfer — AG should open SCO link
        sendAT("AT+BCC")
    }

    func transferAudioToPhone() {
        btPrint("[RFCOMM-HFP] Transfer audio to phone (close SCO)")
    }

    func sendSMS(to: String, body: String) {
        btPrint("[RFCOMM-HFP] SMS not yet implemented over raw RFCOMM")
    }

    func sendATCommand(_ command: String) {
        sendAT(command)
    }

    // MARK: - Incoming RFCOMM Connection

    @objc private func rfcommChannelOpened(_ notification: IOBluetoothUserNotification, channel: IOBluetoothRFCOMMChannel) {
        btPrint("[RFCOMM-HFP] >>> INCOMING RFCOMM connection on channel \(channel.getID())!")

        rfcommChannel = channel
        channel.setDelegate(self)

        connectedDevice = channel.getDevice()
        connectedAddress = connectedDevice?.addressString
        connectTime = Date()
        reconnectAttempts = 0

        btPrint("[RFCOMM-HFP] Connected from: \(connectedDevice?.name ?? "?") (\(connectedAddress ?? "?"))")

        // Start SLC negotiation — send our supported features
        slcState = .rfcommOpen
        startSLCNegotiation()
    }

    // MARK: - SLC State Machine

    private func startSLCNegotiation() {
        btPrint("[SLC] Starting SLC negotiation (HF features: 0x\(String(hfFeatures, radix: 16)))")
        slcState = .waitingBRSFResponse
        sendAT("AT+BRSF=\(hfFeatures)")
    }

    private func processATResponse(_ line: String) {
        let trimmed = line.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }

        btPrint("[SLC] [\(slcState.rawValue)] AG->HF: \(trimmed)")
        delegate?.handsFreeATLog(self, direction: "AG->HF", command: trimmed)

        // Handle unsolicited results (can come at any time after SLC)
        if trimmed.hasPrefix("+CIEV:") {
            handleCIEV(trimmed)
            return
        }
        if trimmed == "RING" || trimmed.hasPrefix("+CLIP:") {
            handleIncomingCall(trimmed)
            return
        }

        // SLC state machine
        switch slcState {
        case .idle, .rfcommOpen:
            break

        case .waitingBRSFResponse:
            if trimmed.hasPrefix("+BRSF:") {
                // Parse AG features
                let valueStr = trimmed.replacingOccurrences(of: "+BRSF:", with: "").trimmingCharacters(in: .whitespaces)
                agFeatures = UInt32(valueStr) ?? 0
                btPrint("[SLC] AG features: 0x\(String(agFeatures, radix: 16)) (\(agFeatures))")
            } else if trimmed == "OK" {
                // Move to CIND test
                slcState = .waitingCINDTest
                sendAT("AT+CIND=?")
            } else if trimmed.hasPrefix("ERROR") {
                btPrint("[SLC] ERROR on AT+BRSF: \(trimmed)")
            }

        case .waitingCINDTest:
            if trimmed.hasPrefix("+CIND:") {
                // Parse indicator names: +CIND: ("service",(0,1)),("call",(0,1)),...
                parseIndicatorNames(trimmed)
            } else if trimmed == "OK" {
                slcState = .waitingCINDRead
                sendAT("AT+CIND?")
            }

        case .waitingCINDRead:
            if trimmed.hasPrefix("+CIND:") {
                // Parse current indicator values: +CIND: 1,0,0,0,5,0,5
                parseIndicatorValues(trimmed)
            } else if trimmed == "OK" {
                // Enable unsolicited result codes
                slcState = .waitingCMER
                sendAT("AT+CMER=3,0,0,1")
            }

        case .waitingCMER:
            if trimmed == "OK" {
                // Check if 3-way calling is supported
                if hfFeatures & 0x02 != 0 && agFeatures & 0x01 != 0 {
                    slcState = .waitingCHLD
                    sendAT("AT+CHLD=?")
                } else {
                    slcCompleted()
                }
            }

        case .waitingCHLD:
            if trimmed.hasPrefix("+CHLD:") {
                btPrint("[SLC] Call hold modes: \(trimmed)")
            } else if trimmed == "OK" {
                slcCompleted()
            }

        case .slcEstablished, .appleExtensions:
            // Handle post-SLC responses
            if trimmed == "OK" || trimmed.hasPrefix("+XAPL:") {
                if slcState == .appleExtensions {
                    btPrint("[SLC] Apple extension acknowledged: \(trimmed)")
                    slcState = .slcEstablished
                }
            }
        }
    }

    private func slcCompleted() {
        let elapsed = connectTime.map { Date().timeIntervalSince($0) } ?? -1
        btPrint("[SLC] === SLC ESTABLISHED! === (elapsed: \(String(format: "%.1f", elapsed))s)")

        slcState = .slcEstablished

        // Extract signal and battery from indicators
        let signal = indicatorValue(named: "signal") ?? indicatorValue(named: "signal_strength") ?? 0
        let battery = indicatorValue(named: "battchg") ?? indicatorValue(named: "battery") ?? 0

        delegate?.handsFreeDidConnect(self, signal: signal, battery: battery)

        // Send Apple extensions
        slcState = .appleExtensions
        sendAT("AT+XAPL=0001-0001-0100,7")

        // Start keep-alive
        startKeepAlive()
    }

    // MARK: - Indicator Parsing

    private func parseIndicatorNames(_ line: String) {
        // +CIND: ("service",(0,1)),("call",(0,1)),("callsetup",(0,3)),...
        indicatorNames = []
        let pattern = "\"(\\w+)\""
        if let regex = try? NSRegularExpression(pattern: pattern) {
            let matches = regex.matches(in: line, range: NSRange(line.startIndex..., in: line))
            for match in matches {
                if let range = Range(match.range(at: 1), in: line) {
                    indicatorNames.append(String(line[range]))
                }
            }
        }
        btPrint("[SLC] Indicators: \(indicatorNames)")
    }

    private func parseIndicatorValues(_ line: String) {
        // +CIND: 1,0,0,0,5,0,5
        let values = line.replacingOccurrences(of: "+CIND:", with: "")
            .trimmingCharacters(in: .whitespaces)
            .split(separator: ",")
            .compactMap { Int($0.trimmingCharacters(in: .whitespaces)) }
        indicatorValues = values
        btPrint("[SLC] Indicator values: \(values)")
    }

    private func indicatorValue(named name: String) -> Int? {
        guard let idx = indicatorNames.firstIndex(of: name), idx < indicatorValues.count else { return nil }
        return indicatorValues[idx]
    }

    // MARK: - Event Handlers

    private func handleCIEV(_ line: String) {
        // +CIEV: <index>,<value>
        let parts = line.replacingOccurrences(of: "+CIEV:", with: "")
            .trimmingCharacters(in: .whitespaces)
            .split(separator: ",")
        guard parts.count == 2,
              let idx = Int(parts[0].trimmingCharacters(in: .whitespaces)),
              let val = Int(parts[1].trimmingCharacters(in: .whitespaces)) else { return }

        // Update indicator value (1-indexed from AG)
        let arrayIdx = idx - 1
        if arrayIdx >= 0 && arrayIdx < indicatorValues.count {
            indicatorValues[arrayIdx] = val
        }

        let name = (arrayIdx >= 0 && arrayIdx < indicatorNames.count) ? indicatorNames[arrayIdx] : "unknown"
        btPrint("[HFP] Indicator update: \(name) (\(idx)) = \(val)")

        switch name {
        case "signal", "signal_strength":
            delegate?.handsFreeSignalUpdate(self, level: val)
        case "battchg", "battery":
            delegate?.handsFreeBatteryUpdate(self, level: val)
        case "call":
            if val == 1 {
                delegate?.handsFreeCallActive(self, from: connectedAddress ?? "")
            } else if val == 0 {
                delegate?.handsFreeCallEnded(self, reason: "remote_hangup")
            }
        case "callsetup":
            if val == 1 {
                // Incoming call setup
                btPrint("[HFP] Incoming call setup detected via CIEV")
            }
        default:
            break
        }
    }

    private var incomingNumber: String?

    private func handleIncomingCall(_ line: String) {
        if line == "RING" {
            btPrint("[HFP] RING!")
        } else if line.hasPrefix("+CLIP:") {
            // +CLIP: "1234567890",129
            let parts = line.replacingOccurrences(of: "+CLIP:", with: "")
                .trimmingCharacters(in: .whitespaces)
            if let first = parts.split(separator: ",").first {
                let number = first.trimmingCharacters(in: CharacterSet(charactersIn: "\" "))
                incomingNumber = number
                delegate?.handsFreeIncomingCall(self, from: number, name: nil)
                btPrint("[HFP] Incoming call from: \(number)")
            }
        }
    }

    // MARK: - AT Command Sending

    private func sendAT(_ command: String) {
        guard let channel = rfcommChannel else {
            btPrint("[RFCOMM-HFP] Cannot send AT — no RFCOMM channel")
            return
        }

        // HFP spec: HF sends "AT+cmd\r" but many implementations need "\r\nAT+cmd\r\n"
        // Try the fuller format that BTstack and BlueZ use
        let atLine = "\r\(command)\r\n"
        guard let data = atLine.data(using: .utf8) else { return }

        btPrint("[SLC] HF->AG: \(command)")
        delegate?.handsFreeATLog(self, direction: "HF->AG", command: command)

        data.withUnsafeBytes { buf in
            if let ptr = buf.baseAddress {
                let mutablePtr = UnsafeMutableRawPointer(mutating: ptr)
                let writeResult = channel.writeAsync(mutablePtr, length: UInt16(data.count), refcon: nil)
                btPrint("[RFCOMM-HFP] writeAsync result: \(writeResult) (0=success), bytes=\(data.count), raw=\(data.map { String(format: "%02x", $0) }.joined(separator: " "))")
            }
        }
    }

    // MARK: - Keep-Alive

    private func startKeepAlive() {
        keepAliveTimer?.invalidate()
        keepAliveTimer = Timer.scheduledTimer(withTimeInterval: 30.0, repeats: true) { [weak self] _ in
            guard let self = self, self.isConnected else { return }
            self.sendAT("AT+CIND?")
        }
    }
}

// MARK: - IOBluetoothRFCOMMChannelDelegate

extension RFCOMMHandsFreeController: IOBluetoothRFCOMMChannelDelegate {
    func rfcommChannelOpenComplete(_ rfcommChannel: IOBluetoothRFCOMMChannel!, status error: IOReturn) {
        btPrint("[RFCOMM-HFP] Channel open complete! error=\(error) (0=success), channel=\(rfcommChannel?.getID() ?? 0)")

        if error == kIOReturnSuccess {
            btPrint("[RFCOMM-HFP] >>> RFCOMM CONNECTED! Starting SLC negotiation...")
            self.rfcommChannel = rfcommChannel
            connectedDevice = rfcommChannel.getDevice()
            connectedAddress = connectedDevice?.addressString
            slcState = .rfcommOpen
            startSLCNegotiation()
        } else {
            btPrint("[RFCOMM-HFP] RFCOMM connection REJECTED: error=\(error)")
            delegate?.handsFreeError(self, code: "RFCOMM_REJECTED", message: "RFCOMM connection rejected: \(error)")
        }
    }

    func rfcommChannelData(_ rfcommChannel: IOBluetoothRFCOMMChannel!, data dataPointer: UnsafeMutableRawPointer!, length dataLength: Int) {
        guard let ptr = dataPointer else { return }
        let data = Data(bytes: ptr, count: dataLength)
        guard let str = String(data: data, encoding: .utf8) else {
            btPrint("[RFCOMM-HFP] Received \(dataLength) bytes (non-UTF8)")
            return
        }

        // Buffer AT responses (may come in fragments)
        atBuffer += str

        // Process complete lines
        while let newlineIdx = atBuffer.firstIndex(where: { $0 == "\r" || $0 == "\n" }) {
            let line = String(atBuffer[atBuffer.startIndex..<newlineIdx])
            atBuffer = String(atBuffer[atBuffer.index(after: newlineIdx)...])
            // Skip empty lines
            let trimmed = line.trimmingCharacters(in: .whitespacesAndNewlines)
            if !trimmed.isEmpty {
                processATResponse(trimmed)
            }
        }
    }

    func rfcommChannelClosed(_ rfcommChannel: IOBluetoothRFCOMMChannel!) {
        let elapsed = connectTime.map { Date().timeIntervalSince($0) } ?? -1
        btPrint("[RFCOMM-HFP] Channel closed (elapsed: \(String(format: "%.1f", elapsed))s)")

        keepAliveTimer?.invalidate()
        keepAliveTimer = nil
        self.rfcommChannel = nil
        slcState = .idle

        delegate?.handsFreeDidDisconnect(self, reason: "rfcomm_closed(elapsed=\(String(format: "%.1f", elapsed))s)")
    }
}
