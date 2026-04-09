"""osmPhone Python backend entry point — Component PY-001.13.

Starts all async services and wires them together:
  - BTBridge: connects to osm-bt Swift process via Unix socket
  - WSServer: serves WebSocket for osm-ui frontend
  - LLM/STT/TTS engines: created from config
  - AudioPipeline: real-time voice loop (VAD -> STT -> LLM -> TTS)
  - SMSHandler: incoming SMS -> LLM -> auto-reply or draft
  - ConversationStore: SQLite message history

Event wiring:
  BT events -> forwarded to frontend via WS broadcast
  BT sco_audio -> fed into AudioPipeline
  BT sms_received -> handled by SMSHandler
  WS actions -> translated to BT commands

Run: cd osm-core && python -m osm_core.main
Or:  make dev-core

FIX LOG (Claude Opus 4.6, 2026-04-09):
  - Replaced skeleton with full component wiring
  - All BT events forwarded to frontend
  - All WS actions mapped to BT commands
  - AudioPipeline and SMSHandler instantiated and connected
"""

from __future__ import annotations

import asyncio
import base64
import logging
import signal

from .bt_bridge import BTBridge
from .config import load_config
from .ws_server import WSServer
from .llm.engine import create_engine as create_llm
from .stt.engine import create_engine as create_stt
from .tts.engine import create_engine as create_tts
from .audio.vad import SimpleVAD
from .audio.pipeline import AudioPipeline
from .sms.handler import SMSHandler
from .sms.conversation import ConversationStore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def async_main() -> None:
    config = load_config()
    logger.info("osmPhone core starting...")

    # ---- Initialize infrastructure ----
    bt_bridge = BTBridge(socket_path=config.bluetooth.socket_path)
    ws_server = WSServer(host=config.server.ws_host, port=config.server.ws_port)
    store = ConversationStore()

    # ---- Initialize AI engines from config ----
    llm_engine = create_llm(config.llm.provider, config)
    stt_engine = create_stt(config.stt.provider, config)
    tts_engine = create_tts(config.tts.provider, config)

    # ---- Initialize VAD with config values ----
    vad = SimpleVAD(
        energy_threshold=config.audio.vad_threshold,
        min_duration_ms=float(config.audio.min_speech_duration_ms),
        silence_duration_ms=float(config.audio.silence_duration_ms),
    )

    # ---- Initialize pipeline and handler ----
    if config.realtime.enabled:
        from .audio.realtime import RealtimeAudioPipeline
        pipeline = RealtimeAudioPipeline(
            config=config,
            bt_bridge=bt_bridge,
            ws_server=ws_server,
            mode=config.voice_mode.default,
        )
        logger.info("Using OpenAI Realtime pipeline (<300ms latency)")
    else:
        pipeline = AudioPipeline(
            llm_engine=llm_engine,
            stt_engine=stt_engine,
            tts_engine=tts_engine,
            vad=vad,
            bt_bridge=bt_bridge,
            ws_server=ws_server,
            mode=config.voice_mode.default,
        )
    sms_handler = SMSHandler(
        config=config,
        bridge=bt_bridge,
        ws_server=ws_server,
        store=store,
        llm_engine=llm_engine,
    )

    # ---- Wire BT events -> handlers ----

    # Events that are forwarded directly to the frontend
    FORWARD_EVENTS = [
        "device_found", "scan_complete", "paired", "pair_failed",
        "pair_confirm", "hfp_connected", "hfp_disconnected",
        "signal_update", "battery_update", "error",
    ]

    for event_type in FORWARD_EVENTS:
        async def _make_forwarder(et):
            async def forwarder(event_id: str, payload: dict):
                await ws_server.broadcast(et, payload)
            return forwarder
        bt_bridge.on(event_type, await _make_forwarder(event_type))

    # Incoming call -> forward to frontend
    async def on_incoming_call(event_id: str, payload: dict):
        await ws_server.broadcast("incoming_call", payload)
    bt_bridge.on("incoming_call", on_incoming_call)

    # Call active -> start audio pipeline
    async def on_call_active(event_id: str, payload: dict):
        contact = payload.get("from", "Unknown")
        pipeline.start_call(contact)
        await ws_server.broadcast("call_active", {"from": contact, "duration": 0})
    bt_bridge.on("call_active", on_call_active)

    # Call ended -> stop pipeline
    async def on_call_ended(event_id: str, payload: dict):
        pipeline.end_call()
        await ws_server.broadcast("call_ended", payload)
    bt_bridge.on("call_ended", on_call_ended)

    # SCO audio frames -> feed into pipeline
    async def on_sco_audio(event_id: str, payload: dict):
        data_b64 = payload.get("data", "")
        if data_b64:
            pcm = base64.b64decode(data_b64)
            await pipeline.feed_audio(pcm)
    bt_bridge.on("sco_audio", on_sco_audio)

    # SMS received -> handler
    bt_bridge.on("sms_received", sms_handler.handle_sms_event)

    # SMS sent confirmation -> forward to frontend
    async def on_sms_sent(event_id: str, payload: dict):
        await ws_server.broadcast("sms_sent", payload)
    bt_bridge.on("sms_sent", on_sms_sent)

    # ---- Wire WS actions -> BT commands ----

    # Simple pass-through actions (no payload transformation needed)
    PASSTHROUGH_ACTIONS = {
        "scan_devices": "scan_start",
        "disconnect": "disconnect_hfp",
        "answer_call": "answer_call",
        "reject_call": "reject_call",
        "end_call": "end_call",
    }

    for ws_action, bt_command in PASSTHROUGH_ACTIONS.items():
        async def _make_passthrough(cmd):
            async def handler(data: dict):
                await bt_bridge.send_command(cmd, data)
            return handler
        ws_server.on_action(ws_action, await _make_passthrough(bt_command))

    # Actions with payload mapping
    async def on_pair_device(data: dict):
        address = data.get("address") or data.get("deviceId", "")
        await bt_bridge.send_command("pair", {"address": address})
    ws_server.on_action("pair_device", on_pair_device)

    async def on_confirm_pair(data: dict):
        await bt_bridge.send_command("pair_confirm", data)
    ws_server.on_action("confirm_pair", on_confirm_pair)

    async def on_connect(data: dict):
        address = data.get("address", "")
        await bt_bridge.send_command("connect_hfp", {"address": address})
    ws_server.on_action("connect", on_connect)

    async def on_dial(data: dict):
        await bt_bridge.send_command("dial", {"number": data.get("number", "")})
    ws_server.on_action("dial", on_dial)

    async def on_send_sms(data: dict):
        await bt_bridge.send_command("send_sms", {"to": data.get("to", ""), "body": data.get("body", "")})
        store.add_message(data.get("to", ""), "outgoing", data.get("body", ""))
    ws_server.on_action("send_sms", on_send_sms)

    # HITL approval actions
    async def on_approve_response(data: dict):
        # User approved voice response — pipeline can proceed to TTS
        await pipeline.approve_response()
    ws_server.on_action("approve_response", on_approve_response)

    async def on_approve_sms(data: dict):
        # User approved SMS draft — send it
        to = data.get("to", "")
        body = data.get("body", "")
        await bt_bridge.send_command("send_sms", {"to": to, "body": body})
        store.add_message(to, "outgoing", body)
        await ws_server.broadcast("sms_sent", {"to": to, "body": body})
    ws_server.on_action("approve_sms", on_approve_sms)

    # Voice mode switch
    async def on_set_voice_mode(data: dict):
        mode = data.get("mode", "hitl")
        pipeline.set_mode(mode)
        logger.info("Voice mode set to: %s", mode)
    ws_server.on_action("set_voice_mode", on_set_voice_mode)

    # Settings update (hot-reload providers)
    async def on_update_settings(data: dict):
        # TODO: Hot-swap LLM/STT/TTS providers based on settings change
        logger.info("Settings update received: %s", data)
        await ws_server.broadcast("settings_updated", data)
    ws_server.on_action("update_settings", on_update_settings)

    # ---- Start services ----
    await ws_server.start()
    bt_bridge._running = True

    logger.info("osmPhone core ready")
    logger.info("  WebSocket: ws://%s:%d", config.server.ws_host, config.server.ws_port)
    logger.info("  BT socket: %s", config.bluetooth.socket_path)
    logger.info("  LLM: %s (%s)", config.llm.provider, config.llm.model)
    logger.info("  STT: %s", config.stt.provider)
    logger.info("  TTS: %s", config.tts.provider)
    logger.info("  Voice mode: %s", config.voice_mode.default)
    if config.realtime.enabled:
        logger.info("  Realtime: %s (voice=%s)", config.realtime.model, config.realtime.voice)

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
