#!/usr/bin/env bash
set -euo pipefail

echo "=== Enabling Bluetooth HFP Sink Mode ==="
echo ""
echo "macOS 12+ disables HFP sink mode by default."
echo "This script re-enables it so your Mac can act as a Bluetooth headset."
echo ""

# Enable HFP sink mode
defaults write com.apple.BluetoothAudioAgent "EnableBluetoothSinkMode" -bool true

# Optimize Bluetooth audio quality
defaults write com.apple.BluetoothAudioAgent "Apple Bitpool Max (editable)" 53
defaults write com.apple.BluetoothAudioAgent "Apple Bitpool Min (editable)" 35
defaults write com.apple.BluetoothAudioAgent "Apple Initial Bitpool (editable)" 35
defaults write com.apple.BluetoothAudioAgent "Apple Initial Bitpool Min (editable)" 53
defaults write com.apple.BluetoothAudioAgent "Negotiated Bitpool" 53
defaults write com.apple.BluetoothAudioAgent "Negotiated Bitpool Max" 53
defaults write com.apple.BluetoothAudioAgent "Negotiated Bitpool Min" 35

echo "Bluetooth settings updated."
echo ""
echo "You MUST reboot your Mac for these changes to take effect."
echo ""
echo "To verify after reboot, run:"
echo "  defaults read com.apple.BluetoothAudioAgent"
echo ""
read -p "Reboot now? (y/N) " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]]; then
    sudo shutdown -r now
fi
