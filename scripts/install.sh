#!/usr/bin/env bash
set -euo pipefail

echo "=== osmPhone Dependency Installer ==="
echo ""

# Check macOS
if [[ "$(uname)" != "Darwin" ]]; then
    echo "ERROR: osmPhone requires macOS"
    exit 1
fi

# Check Homebrew
if ! command -v brew &>/dev/null; then
    echo "Installing Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi

# Check Xcode CLI tools
if ! xcode-select -p &>/dev/null; then
    echo "Installing Xcode Command Line Tools..."
    xcode-select --install
    echo "Please complete the Xcode CLI installation and re-run this script."
    exit 1
fi

# Check Python 3.11+
if ! command -v python3 &>/dev/null; then
    echo "Installing Python 3.11..."
    brew install python@3.11
fi

PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)
if [[ "$PYTHON_MAJOR" -lt 3 ]] || [[ "$PYTHON_MAJOR" -eq 3 && "$PYTHON_MINOR" -lt 11 ]]; then
    echo "Python 3.11+ required (found $PYTHON_VERSION). Installing..."
    brew install python@3.11
fi

# Check Node.js 20+
if ! command -v node &>/dev/null; then
    echo "Installing Node.js 20..."
    brew install node@20
fi

NODE_MAJOR=$(node -v | sed 's/v//' | cut -d. -f1)
if [[ "$NODE_MAJOR" -lt 20 ]]; then
    echo "Node.js 20+ required (found v$(node -v)). Installing..."
    brew install node@20
fi

# Install BlackHole virtual audio driver
if ! system_profiler SPAudioDataType 2>/dev/null | grep -q "BlackHole"; then
    echo "Installing BlackHole virtual audio driver..."
    brew install blackhole-2ch
    echo "NOTE: BlackHole 2ch installed. You may need to configure an aggregate audio device."
fi

echo ""
echo "=== System dependencies OK ==="
echo ""

# Install Python backend
echo "Installing osm-core Python dependencies..."
cd "$(dirname "$0")/../osm-core"
pip install -e ".[all]" 2>/dev/null || pip install -e ".[dev]"

# Install Node frontend
echo ""
echo "Installing osm-ui Node dependencies..."
cd "$(dirname "$0")/../osm-ui"
npm install

# Build Swift helper
echo ""
echo "Building osm-bt Swift helper..."
cd "$(dirname "$0")/../osm-bt"
swift build

echo ""
echo "=== osmPhone installation complete ==="
echo ""
echo "Next steps:"
echo "  1. Copy config.example.yaml to config.yaml and add your API keys"
echo "  2. Run: make setup-bt    (enables HFP sink mode, requires reboot)"
echo "  3. Run: make dev         (starts all components)"
