#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# PIDs for cleanup
BT_PID=""
CORE_PID=""
UI_PID=""

cleanup() {
    echo ""
    echo "Shutting down osmPhone..."
    [[ -n "$UI_PID" ]] && kill "$UI_PID" 2>/dev/null || true
    [[ -n "$CORE_PID" ]] && kill "$CORE_PID" 2>/dev/null || true
    [[ -n "$BT_PID" ]] && kill "$BT_PID" 2>/dev/null || true
    rm -f /tmp/osmphone.sock
    echo "All processes stopped."
    exit 0
}

trap cleanup SIGINT SIGTERM EXIT

echo "=== Starting osmPhone ==="

# Start Swift Bluetooth helper
echo "Starting osm-bt..."
cd "$PROJECT_DIR/osm-bt"
swift run OsmBT &
BT_PID=$!
sleep 2

# Start Python backend
echo "Starting osm-core..."
cd "$PROJECT_DIR/osm-core"
python -m osm_core.main &
CORE_PID=$!
sleep 1

# Start Next.js frontend
echo "Starting osm-ui..."
cd "$PROJECT_DIR/osm-ui"
npm run dev &
UI_PID=$!

echo ""
echo "=== osmPhone Running ==="
echo "  osm-bt   PID: $BT_PID"
echo "  osm-core PID: $CORE_PID"
echo "  osm-ui   PID: $UI_PID"
echo ""
echo "  UI: http://localhost:3000"
echo "  WS: ws://localhost:8765"
echo "  BT: /tmp/osmphone.sock"
echo ""
echo "Press Ctrl+C to stop all processes."

# Wait for any child to exit
wait
