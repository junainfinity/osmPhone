"""WebSocket server for frontend communication — Component PY-001.3.

Serves ws://localhost:8765 for the osm-ui Next.js frontend.
Two-way communication:
  - Server -> Client: broadcast events (bt_status, incoming_call, transcript, etc.)
  - Client -> Server: receive actions (dial, answer_call, send_sms, etc.)

Multiple frontend clients can connect simultaneously (all receive broadcasts).
Action handlers are registered via ws.on_action("dial", handler).

Protocol: JSON messages. See ARCHITECTURE.md WebSocket Protocol section.

Note: Uses websockets 14.x legacy API (WebSocketServerProtocol).
The deprecation warnings are harmless — migrate to new API when convenient.

Tests: osm-core/tests/test_ws_server.py (6/6 passing)
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable, Coroutine

import websockets
from websockets.server import WebSocketServerProtocol

logger = logging.getLogger(__name__)


class WSServer:
    """WebSocket server that broadcasts events and receives actions from the frontend."""

    def __init__(self, host: str = "localhost", port: int = 8765):
        self.host = host
        self.port = port
        self._clients: set[WebSocketServerProtocol] = set()
        self._action_handlers: dict[str, list[Callable]] = {}
        self._server = None

    def on_action(self, action: str, handler: Callable[..., Coroutine]) -> None:
        """Register an async handler for a frontend action."""
        self._action_handlers.setdefault(action, []).append(handler)

    async def broadcast(self, event_type: str, data: dict[str, Any] | None = None) -> None:
        """Send an event to all connected frontend clients (async version)."""
        message = json.dumps({"type": event_type, "data": data or {}})
        if self._clients:
            await asyncio.gather(
                *[self._send_safe(client, message) for client in self._clients],
                return_exceptions=True,
            )

    def broadcast_sync(self, event_type: str, data: dict[str, Any] | None = None) -> None:
        """Fire-and-forget broadcast from sync code (e.g., AudioPipeline state changes).

        Schedules the async broadcast on the running event loop. Safe to call from
        synchronous methods that run inside an async context (like pipeline.start_call).

        FIX LOG (Claude Opus 4.6, 2026-04-09):
          Added this method — AudioPipeline calls broadcast_sync() from sync methods
          like start_call() and end_call(). Without this, AttributeError at runtime.
        """
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.broadcast(event_type, data))
        except RuntimeError:
            # No running loop — log and skip (happens in tests or shutdown)
            logger.warning("broadcast_sync: no running event loop, skipping broadcast")

    async def _send_safe(self, client: WebSocketServerProtocol, message: str) -> None:
        try:
            await client.send(message)
        except websockets.exceptions.ConnectionClosed:
            pass

    async def start(self) -> None:
        """Start the WebSocket server."""
        self._server = await websockets.serve(
            self._handle_client,
            self.host,
            self.port,
        )
        logger.info("WebSocket server listening on ws://%s:%d", self.host, self.port)

    async def stop(self) -> None:
        """Stop the WebSocket server."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def _handle_client(self, websocket: WebSocketServerProtocol) -> None:
        """Handle a connected frontend client."""
        self._clients.add(websocket)
        logger.info("Frontend connected (%d total)", len(self._clients))

        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                    action = data.get("action", "")
                    action_data = data.get("data", {})

                    handlers = self._action_handlers.get(action, [])
                    for handler in handlers:
                        try:
                            await handler(action_data)
                        except Exception:
                            logger.exception("Action handler error for %s", action)

                except json.JSONDecodeError:
                    logger.warning("Invalid JSON from frontend")
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            self._clients.discard(websocket)
            logger.info("Frontend disconnected (%d remaining)", len(self._clients))
