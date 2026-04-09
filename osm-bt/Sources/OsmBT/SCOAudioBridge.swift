// SCOAudioBridge.swift — Component BT-001.5 (IN PROGRESS)
//
// Captures incoming call audio from the Bluetooth SCO channel and sends it to
// osm-core for STT processing. Also receives TTS-generated audio from osm-core
// and injects it back into the SCO output so the caller hears the AI voice.
//
// STATUS: STUB. Device discovery (findSCODevice) works. The actual AudioUnit
// capture and injection pipelines are TODO.
//
// How SCO audio works on macOS:
//   When an HFP call is active and audio is transferred to the computer,
//   macOS creates a virtual audio device for the Bluetooth SCO channel.
//   This device appears in Audio MIDI Setup and can be selected as input/output.
//
// Implementation plan:
//   1. Find the SCO audio device via AudioObjectGetPropertyData (partially done)
//   2. Create an AudioUnit (kAudioUnitSubType_HALOutput) configured for input
//   3. Set up an input render callback to receive PCM frames
//   4. Forward captured PCM to osm-core via the onAudioCaptured callback
//   5. For injection: set up an output render callback that feeds TTS audio
//
// Alternative approach if direct SCO device access is restricted:
//   Use BlackHole (virtual audio driver) as an aggregate device:
//   - SCO input -> app -> BlackHole output -> aggregate device -> SCO output
//   This adds a routing hop but avoids needing direct SCO device write access.
//
// Relevant Apple docs:
//   - AudioHardware.h (kAudioHardwarePropertyDevices)
//   - AudioUnit hosting for HAL I/O

import Foundation
import CoreAudio
import AudioToolbox

/// Bridges SCO audio to/from the IPC layer.
/// Captures incoming call audio from the SCO channel (via CoreAudio)
/// and injects TTS-generated audio back into the SCO output.
class SCOAudioBridge {
    /// Called when audio data is captured from the SCO channel.
    var onAudioCaptured: ((Data, Int) -> Void)?  // (pcmData, sampleRate)

    private var isCapturing = false
    private var captureUnit: AudioComponentInstance?
    private var scoSampleRate: Int = 8000

    // MARK: - Start/Stop Capture

    /// Begin capturing audio from the SCO input device.
    func startCapture(sampleRate: Int = 8000) {
        scoSampleRate = sampleRate
        isCapturing = true
        // TODO: Implement CoreAudio capture from SCO device
        // 1. Find the SCO audio device via AudioObjectGetPropertyData
        // 2. Set up AudioUnit with kAudioUnitSubType_HALOutput
        // 3. Configure input callback to receive PCM frames
        // 4. Forward frames via onAudioCaptured callback
        print("[SCOAudio] Capture started (sample rate: \(sampleRate))")
    }

    func stopCapture() {
        isCapturing = false
        // TODO: Tear down AudioUnit
        print("[SCOAudio] Capture stopped")
    }

    // MARK: - Inject Audio

    /// Inject PCM audio data into the SCO output (caller hears this).
    func injectAudio(pcmData: Data, sampleRate: Int) {
        guard isCapturing else { return }
        // TODO: Write PCM to the SCO output device
        // 1. Find the SCO output device
        // 2. Write pcmData to its output buffer via AudioUnit render callback
        print("[SCOAudio] Injecting \(pcmData.count) bytes at \(sampleRate)Hz")
    }

    // MARK: - Audio Device Discovery

    /// Find the Bluetooth SCO audio device ID.
    static func findSCODevice() -> AudioDeviceID? {
        var propertyAddress = AudioObjectPropertyAddress(
            mSelector: kAudioHardwarePropertyDevices,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain
        )
        var dataSize: UInt32 = 0
        AudioObjectGetPropertyDataSize(
            AudioObjectID(kAudioObjectSystemObject),
            &propertyAddress,
            0, nil,
            &dataSize
        )
        let deviceCount = Int(dataSize) / MemoryLayout<AudioDeviceID>.size
        var devices = [AudioDeviceID](repeating: 0, count: deviceCount)
        AudioObjectGetPropertyData(
            AudioObjectID(kAudioObjectSystemObject),
            &propertyAddress,
            0, nil,
            &dataSize,
            &devices
        )

        for device in devices {
            if let name = getDeviceName(device),
               name.lowercased().contains("bluetooth") || name.lowercased().contains("sco") {
                return device
            }
        }
        return nil
    }

    private static func getDeviceName(_ deviceID: AudioDeviceID) -> String? {
        var propertyAddress = AudioObjectPropertyAddress(
            mSelector: kAudioDevicePropertyDeviceNameCFString,
            mScope: kAudioObjectPropertyScopeGlobal,
            mElement: kAudioObjectPropertyElementMain
        )
        var name: CFString = "" as CFString
        var dataSize = UInt32(MemoryLayout<CFString>.size)
        let status = AudioObjectGetPropertyData(deviceID, &propertyAddress, 0, nil, &dataSize, &name)
        return status == noErr ? name as String : nil
    }
}
