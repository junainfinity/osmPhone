"""Unit tests for UT-PY-001.2: BT Bridge."""

import asyncio
import json
import os
import tempfile

import pytest

from osm_core.bt_bridge import BTBridge


@pytest.fixture
def socket_path():
    """Use /tmp for socket path (macOS AF_UNIX has 104 char limit)."""
    import uuid
    path = f"/tmp/osm_test_{uuid.uuid4().hex[:8]}.sock"
    yield path
    # Cleanup
    import os
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


async def start_mock_server(socket_path: str):
    """Start a mock Unix domain socket server that echoes events."""
    received = []

    async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        while True:
            line = await reader.readline()
            if not line:
                break
            received.append(json.loads(line.decode().strip()))

    server = await asyncio.start_unix_server(handle_client, path=socket_path)
    return server, received


class TestBTBridge:
    @pytest.mark.asyncio
    async def test_connect_to_mock_server(self, socket_path):
        """UT-PY-001.2-01: Connect to mock Unix socket server."""
        server, _ = await start_mock_server(socket_path)
        bridge = BTBridge(socket_path)

        await bridge.connect(retry_interval=0.1)
        assert bridge._writer is not None

        await bridge.disconnect()
        server.close()

    @pytest.mark.asyncio
    async def test_send_command(self, socket_path):
        """UT-PY-001.2-02: Send command, mock server receives JSON line."""
        received = []

        async def handle(reader, writer):
            line = await reader.readline()
            if line:
                received.append(json.loads(line.decode().strip()))

        server = await asyncio.start_unix_server(handle, path=socket_path)
        bridge = BTBridge(socket_path)
        await bridge.connect(retry_interval=0.1)

        cmd_id = await bridge.send_command("scan_start", {})
        await asyncio.sleep(0.1)

        assert len(received) == 1
        assert received[0]["type"] == "scan_start"
        assert received[0]["id"] == cmd_id

        await bridge.disconnect()
        server.close()

    @pytest.mark.asyncio
    async def test_receive_event(self, socket_path):
        """UT-PY-001.2-03: Mock server sends event, bridge handler called."""
        events_received = []

        async def handle_client(reader, writer):
            event = {
                "id": "evt-1",
                "type": "device_found",
                "payload": {"address": "AA:BB", "name": "Test", "rssi": -50},
            }
            writer.write((json.dumps(event) + "\n").encode())
            await writer.drain()
            # Keep connection open briefly
            await asyncio.sleep(0.5)
            writer.close()

        server = await asyncio.start_unix_server(handle_client, path=socket_path)
        bridge = BTBridge(socket_path)

        async def on_device_found(event_id, payload):
            events_received.append((event_id, payload))

        bridge.on("device_found", on_device_found)
        await bridge.connect(retry_interval=0.1)

        # Listen briefly
        listen_task = asyncio.create_task(bridge.listen())
        await asyncio.sleep(0.3)
        bridge._running = False
        await asyncio.sleep(0.1)

        assert len(events_received) == 1
        assert events_received[0][0] == "evt-1"
        assert events_received[0][1]["name"] == "Test"

        await bridge.disconnect()
        server.close()

    @pytest.mark.asyncio
    async def test_multiple_events(self, socket_path):
        """UT-PY-001.2-05: Multiple events dispatched in order."""
        events_received = []

        async def handle_client(reader, writer):
            for i in range(3):
                event = {"id": f"evt-{i}", "type": "device_found", "payload": {"index": i}}
                writer.write((json.dumps(event) + "\n").encode())
                await writer.drain()
            await asyncio.sleep(0.5)
            writer.close()

        server = await asyncio.start_unix_server(handle_client, path=socket_path)
        bridge = BTBridge(socket_path)

        async def on_event(event_id, payload):
            events_received.append(payload["index"])

        bridge.on("device_found", on_event)
        await bridge.connect(retry_interval=0.1)

        listen_task = asyncio.create_task(bridge.listen())
        await asyncio.sleep(0.3)
        bridge._running = False
        await asyncio.sleep(0.1)

        assert events_received == [0, 1, 2]

        await bridge.disconnect()
        server.close()
