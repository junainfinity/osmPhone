"""Unit tests for UT-PY-001.3: WS Server."""

import asyncio
import json

import pytest
import websockets

from osm_core.ws_server import WSServer


@pytest.fixture
async def server():
    ws = WSServer(host="localhost", port=0)  # port 0 = random available
    await ws.start()
    # Get the actual port assigned
    actual_port = ws._server.sockets[0].getsockname()[1]
    ws.port = actual_port
    yield ws
    await ws.stop()


class TestWSServer:
    @pytest.mark.asyncio
    async def test_server_starts(self):
        """UT-PY-001.3-01: Server starts and listens."""
        ws = WSServer(host="localhost", port=0)
        await ws.start()
        assert ws._server is not None
        await ws.stop()

    @pytest.mark.asyncio
    async def test_client_connects(self, server: WSServer):
        """UT-PY-001.3-02: Client connects, server tracks it."""
        async with websockets.connect(f"ws://localhost:{server.port}"):
            await asyncio.sleep(0.1)
            assert len(server._clients) == 1

    @pytest.mark.asyncio
    async def test_broadcast(self, server: WSServer):
        """UT-PY-001.3-03: Broadcast reaches all clients."""
        received = []
        async with websockets.connect(f"ws://localhost:{server.port}") as ws:
            await asyncio.sleep(0.1)
            await server.broadcast("bt_status", {"connected": True})
            msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
            data = json.loads(msg)
            assert data["type"] == "bt_status"
            assert data["data"]["connected"] is True

    @pytest.mark.asyncio
    async def test_action_dispatched(self, server: WSServer):
        """UT-PY-001.3-04: Client action dispatched to handler."""
        actions_received = []

        async def on_dial(data):
            actions_received.append(data)

        server.on_action("dial", on_dial)

        async with websockets.connect(f"ws://localhost:{server.port}") as ws:
            await asyncio.sleep(0.1)
            await ws.send(json.dumps({"action": "dial", "data": {"number": "+1234"}}))
            await asyncio.sleep(0.2)

        assert len(actions_received) == 1
        assert actions_received[0]["number"] == "+1234"

    @pytest.mark.asyncio
    async def test_multiple_clients(self, server: WSServer):
        """UT-PY-001.3-05: Multiple clients receive broadcasts."""
        async with (
            websockets.connect(f"ws://localhost:{server.port}") as ws1,
            websockets.connect(f"ws://localhost:{server.port}") as ws2,
        ):
            await asyncio.sleep(0.1)
            assert len(server._clients) == 2

            await server.broadcast("test", {"msg": "hello"})
            msg1 = await asyncio.wait_for(ws1.recv(), timeout=1.0)
            msg2 = await asyncio.wait_for(ws2.recv(), timeout=1.0)
            assert json.loads(msg1)["data"]["msg"] == "hello"
            assert json.loads(msg2)["data"]["msg"] == "hello"

    @pytest.mark.asyncio
    async def test_client_disconnect(self, server: WSServer):
        """UT-PY-001.3-06: Client disconnect handled cleanly."""
        ws = await websockets.connect(f"ws://localhost:{server.port}")
        await asyncio.sleep(0.1)
        assert len(server._clients) == 1

        await ws.close()
        await asyncio.sleep(0.2)
        assert len(server._clients) == 0
