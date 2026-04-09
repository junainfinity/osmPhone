// HCIDeviceClass.swift
//
// Attempts to change the Bluetooth device class so iPhone sees us as
// an Audio/Headset device instead of a Computer.
//
// Target class: 0x240404 (Audio/Video, Wearable Headset)
// Current class: 0x7995916 (Computer)
//
// Uses IOBluetoothHostController private API setClassOfDevice:

import Foundation
import IOBluetooth

/// Attempts to set the Bluetooth device class to Audio/Headset.
/// Returns true if the class changed, false if not.
func trySetAudioDeviceClass() -> Bool {
    guard let controller = IOBluetoothHostController.default() else {
        btPrint("[HCI] No Bluetooth controller found")
        return false
    }

    let currentClass = controller.classOfDevice()
    btPrint("[HCI] Current device class: 0x\(String(currentClass, radix: 16)) (\(currentClass))")
    btPrint("[HCI] Controller address: \(controller.addressAsString() ?? "unknown")")
    btPrint("[HCI] Controller name: \(controller.nameAsString() ?? "unknown")")

    // Target: Audio/Video + Wearable Headset
    // Major Service: Audio (bit 21) = 0x200000
    // Major Device: Audio/Video (0x04 << 8) = 0x0400
    // Minor Device: Wearable Headset (0x01 << 2) = 0x04
    // Combined: 0x200404
    let targetClass: BluetoothClassOfDevice = 0x200404

    btPrint("[HCI] Target device class: 0x\(String(targetClass, radix: 16))")

    // Method 1: setClassOfDevice:forTimeInterval: (private API, discovered in method list)
    let selector1 = NSSelectorFromString("setClassOfDevice:forTimeInterval:")
    if controller.responds(to: selector1) {
        btPrint("[HCI] Trying setClassOfDevice:forTimeInterval: with 0x\(String(targetClass, radix: 16)), interval=0 (permanent)")
        controller.perform(selector1, with: NSNumber(value: targetClass), with: NSNumber(value: 0.0))
    }

    // Method 2: Direct call to BluetoothHCIWriteClassOfDevice
    // This is a C-level IOBluetooth function, not an ObjC method
    // The actual function signature is:
    //   IOReturn BluetoothHCIWriteClassOfDevice(BluetoothClassOfDevice classOfDevice)
    // But it's exposed as an instance method on IOBluetoothHostController
    //
    // Use unsafeBitCast to call the method with the correct signature
    typealias WriteClassFunc = @convention(c) (AnyObject, Selector, BluetoothClassOfDevice) -> IOReturn
    let sel = NSSelectorFromString("BluetoothHCIWriteClassOfDevice:")
    if controller.responds(to: sel) {
        let imp = controller.method(for: sel)
        let fn = unsafeBitCast(imp, to: WriteClassFunc.self)
        let result = fn(controller, sel, targetClass)
        btPrint("[HCI] BluetoothHCIWriteClassOfDevice: result=\(result) (0=success)")
    } else {
        btPrint("[HCI] BluetoothHCIWriteClassOfDevice: not available")
    }

    // Also try the read to see if our view is stale
    typealias ReadClassFunc = @convention(c) (AnyObject, Selector, UnsafeMutablePointer<BluetoothClassOfDevice>) -> IOReturn
    let readSel = NSSelectorFromString("BluetoothHCIReadClassOfDevice:")
    if controller.responds(to: readSel) {
        let readImp = controller.method(for: readSel)
        let readFn = unsafeBitCast(readImp, to: ReadClassFunc.self)
        var readClass: BluetoothClassOfDevice = 0
        let readResult = readFn(controller, readSel, &readClass)
        btPrint("[HCI] BluetoothHCIReadClassOfDevice: result=\(readResult), class=0x\(String(readClass, radix: 16))")
    }

    // Wait for HCI command to process
    Thread.sleep(forTimeInterval: 1.0)

    // Check all available methods for anything class-related
    var methodCount: UInt32 = 0
    if let methods = class_copyMethodList(type(of: controller), &methodCount) {
        var classRelated: [String] = []
        for i in 0..<Int(methodCount) {
            let name = NSStringFromSelector(method_getName(methods[i]))
            if name.lowercased().contains("class") || name.lowercased().contains("device") {
                classRelated.append(name)
            }
        }
        free(methods)
        if !classRelated.isEmpty {
            btPrint("[HCI] Class/Device related methods: \(classRelated)")
        }
    }

    // Verify if it changed
    let newClass = controller.classOfDevice()
    btPrint("[HCI] New device class: 0x\(String(newClass, radix: 16)) (\(newClass))")

    if newClass != currentClass {
        btPrint("[HCI] >>> DEVICE CLASS CHANGED! 0x\(String(currentClass, radix: 16)) -> 0x\(String(newClass, radix: 16))")
        return true
    } else {
        btPrint("[HCI] Device class unchanged. Firmware may have ignored the command.")
        return false
    }
}
