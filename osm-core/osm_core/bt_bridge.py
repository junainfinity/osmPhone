"""Async Unix domain socket client for communicating with osm-bt — Component PY-001.2.

Connects to the osm-bt Swift process via Unix domain socket (/tmp/osmphone.sock).
Sends JSON-line commands and receives JSON-line events asynchronously.

Usage:
    bridge = BTBridge()
    bridge.on("incoming_call", handle_incoming_call)  # register event handler
    await bridge.run()  # connect + listen loop with auto-reconnect

Event handlers are async callables: async def handler(event_id: str, payload: dict)
Commands are sent via: await bridge.send_command("dial", {"number": "+1234"})

The bridge auto-reconnects if osm-bt restarts. Set _running = False to stop.

Tests: osm-core/tests/test_bt_bridge.py (4/4 passing)
Note: Tests use /tmp/ for socket paths because macOS AF_UNIX has 104-char limit.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)


class BTBridge:
    """Connects to osm-bt's Unix domain socket and exchanges JSON messages."""

    def __init__(self, socket_path: str = "/tmp/osmphone.sock"):
        self.socket_path = socket_path
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._handlers: dict[str, list[Callable]] = {}
        self._running = False

    async def connect(self, retry_interval: float = 2.0) -> None:
        """Connect to osm-bt socket. Retries until connected."""
        while True:
            try:
                self._reader, self._writer = await asyncio.open_unix_connection(self.socket_path)
                logger.info("Connected to osm-bt at %s", self.socket_path)
                self._running = True
                return
            except (ConnectionRefusedError, FileNotFoundError):
                logger.debug("osm-bt not ready, retrying in %.1fs...", retry_interval)
                await asyncio.sleep(retry_interval)

    async def disconnect(self) -> None:
        """Close the connection."""
        self._running = False
        if self._writer:
            self._writer.close()
            await self._writer.wait_closed()
        self._reader = None
        self._writer = None

    def on(self, event_type: str, handler: Callable[..., Coroutine]) -> None:
        """Register an async handler for an event type."""
        self._handlers.setdefault(event_type, []).append(handler)

    async def send_command(self, command_type: str, payload: dict[str, Any] | None = None) -> str:
        """Send a command to osm-bt. Returns the command ID."""
        if not self._writer:
            raise ConnectionError("Not connected to osm-bt")

        cmd_id = f"cmd-{uuid.uuid4().hex[:8]}"
        message = {
            "id": cmd_id,
            "type": command_type,
            "payload": payload or {},
        }
        line = json.dumps(message) + "\n"
        self._writer.write(line.encode())
        await self._writer.drain()
        logger.debug("Sent: %s", command_type)
        return cmd_id

    async def listen(self) -> None:
        """Read events from osm-bt and dispatch to handlers. Runs until disconnected."""
        while self._running and self._reader:
            try:
                line = await self._reader.readline()
                if not line:
                    logger.warning("osm-bt disconnected")
                    break

                data = json.loads(line.decode().strip())
                event_type = data.get("type", "")
                payload = data.get("payload", {})
                event_id = data.get("id", "")

                handlers = self._handlers.get(event_type, [])
                for handler in handlers:
                    try:
                        await handler(event_id, payload)
                    except Exception:
                        logger.exception("Handler error for %s", event_type)

            except json.JSONDecodeError as e:
                logger.warning("Invalid JSON from osm-bt: %s", e)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Error reading from osm-bt")
                break

        logger.info("Listener stopped")

    async def run(self, retry_interval: float = 2.0) -> None:
        """Connect and listen in a loop, reconnecting on disconnect."""
        while self._running:
            try:
                await self.connect(retry_interval)
                await self.listen()
            except Exception:
                logger.exception("BTBridge error")
            if self._running:
                logger.info("Reconnecting in %.1fs...", retry_interval)
                await asyncio.sleep(retry_interval)
