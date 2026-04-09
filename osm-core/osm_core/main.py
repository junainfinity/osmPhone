"""osmPhone Python backend entry point — Component PY-001.13 (SKELETON).

Starts all async services: BT bridge, WS server, and (future) audio pipeline.
Currently a skeleton — the event wiring between BT bridge and WS server
has placeholder `pass` statements that need to be filled in.

TODO for the next developer:
  1. Wire BT events to WS broadcasts (forward_bt_event needs per-type routing)
  2. Wire WS actions to BT commands (forward_ws_action needs per-action routing)
  3. Instantiate LLM/STT/TTS engines from config
  4. Create SMS handler and audio pipeline
  5. Wire everything together

Run: cd osm-core && python -m osm_core.main
Or:  make dev-core
"""

from __future__ import annotations

import asyncio
import logging
import signal

from .bt_bridge import BTBridge
from .config import load_config
from .ws_server import WSServer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def async_main() -> None:
    config = load_config()
    logger.info("osmPhone core starting...")

    # Initialize components
    bt_bridge = BTBridge(socket_path=config.bluetooth.socket_path)
    ws_server = WSServer(host=config.server.ws_host, port=config.server.ws_port)

    # Wire BT events -> WS broadcasts
    async def forward_bt_event(event_id: str, payload: dict) -> None:
        """Forward BT events to all connected frontends."""
        # The event type is determined by the handler registration
        pass  # TODO: implement per-event forwarding

    # Wire WS actions -> BT commands
    async def forward_ws_action(data: dict) -> None:
        """Forward frontend actions to BT bridge."""
        pass  # TODO: implement per-action forwarding

    # Start services
    await ws_server.start()
    bt_bridge._running = True

    logger.info("osmPhone core ready")
    logger.info("  WebSocket: ws://%s:%d", config.server.ws_host, config.server.ws_port)
    logger.info("  BT socket: %s", config.bluetooth.socket_path)

    # Run BT bridge listener (blocks until disconnect/shutdown)
    try:
        await bt_bridge.run()
    except asyncio.CancelledError:
        pass
    finally:
        await ws_server.stop()
        await bt_bridge.disconnect()
        logger.info("osmPhone core stopped")


def main() -> None:
    loop = asyncio.new_event_loop()

    def shutdown(sig: signal.Signals) -> None:
        logger.info("Received %s, shutting down...", sig.name)
        for task in asyncio.all_tasks(loop):
            task.cancel()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, shutdown, sig)

    try:
        loop.run_until_complete(async_main())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
