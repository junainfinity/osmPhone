"""OpenAI Realtime API audio pipeline — Component PY-001.10.

Replaces the sequential VAD -> STT -> LLM -> TTS pipeline with a single
persistent WebSocket connection to OpenAI's Realtime API, achieving <300ms
latency for voice conversations.

The Realtime API handles speech detection, transcription, LLM response, and
voice synthesis in one round-trip. Audio flows:

  SCO 8kHz PCM -> resample 24kHz -> base64 -> WebSocket -> OpenAI
  OpenAI -> base64 PCM 24kHz -> resample 8kHz -> inject_audio -> SCO

Public interface matches AudioPipeline (start_call, end_call, feed_audio,
approve_response, set_mode) so main.py can swap between them based on
config.realtime.enabled.

Two voice modes:
  - autonomous: AI response audio is injected into SCO immediately.
  - hitl (human-in-the-loop): Audio is buffered, transcript sent to frontend,
    user approves, then buffered audio is flushed to SCO.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import Optional

import numpy as np
import websockets
import websockets.exceptions

from .pipeline import PipelineState
from .resampler import AudioResampler

logger = logging.getLogger(__name__)

# OpenAI Realtime API constants
REALTIME_INPUT_SAMPLE_RATE = 24000
REALTIME_OUTPUT_SAMPLE_RATE = 24000


class RealtimeAudioPipeline:
    """Real-time voice pipeline using OpenAI Realtime API.

    Same public interface as AudioPipeline so main.py can swap between them.
    """

    def __init__(self, config, bt_bridge, ws_server, mode: str = "autonomous"):
        self.config = config
        self.bt_bridge = bt_bridge
        self.ws_server = ws_server
        self.mode = mode

        self.state = PipelineState.IDLE
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._listen_task: Optional[asyncio.Task] = None
        self._connect_task: Optional[asyncio.Task] = None
        self._contact = "Unknown"

        # HITL support
        self._approval_event = asyncio.Event()
        self._pending_audio_chunks: list[bytes] = []
        self._pending_transcript = ""

        # Reconnection
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = 5

    # ------------------------------------------------------------------ #
    # Public interface (matches AudioPipeline)
    # ------------------------------------------------------------------ #

    def start_call(self, contact: str):
        """Transition to LISTENING. Opens WebSocket to OpenAI Realtime API."""
        self.state = PipelineState.LISTENING
        self._contact = contact
        self._pending_audio_chunks.clear()
        self._pending_transcript = ""
        self._reconnect_attempts = 0
        self._approval_event = asyncio.Event()

        # Kick off async WebSocket connection
        self._connect_task = asyncio.create_task(self._connect())

        self.ws_server.broadcast_sync("call_active", {"active": True, "contact": contact})
        logger.info("Realtime pipeline started LISTENING for %s", contact)

    def end_call(self):
        """Transition to IDLE. Closes WebSocket."""
        self.state = PipelineState.IDLE
        if self._listen_task and not self._listen_task.done():
            self._listen_task.cancel()
        if self._connect_task and not self._connect_task.done():
            self._connect_task.cancel()
        asyncio.create_task(self._disconnect())
        self.ws_server.broadcast_sync("call_active", {"active": False})
        logger.info("Realtime pipeline returned to IDLE")

    async def feed_audio(self, pcm_data: bytes):
        """Feed a PCM audio frame from the SCO channel.

        Resamples from SCO rate (8kHz) to 24kHz and sends to OpenAI.
        """
        if self.state not in (PipelineState.LISTENING, PipelineState.PROCESSING):
            return
        if self._ws is None:
            return

        try:
            # Convert bytes to int16 numpy array
            audio_int16 = np.frombuffer(pcm_data, dtype=np.int16)

            # Resample from SCO rate to 24kHz
            sco_rate = self.config.audio.sco_sample_rate
            if sco_rate != REALTIME_INPUT_SAMPLE_RATE:
                audio_24k = AudioResampler.resample(
                    audio_int16.astype(np.float64),
                    sco_rate,
                    REALTIME_INPUT_SAMPLE_RATE,
                )
                audio_24k_int16 = audio_24k.astype(np.int16)
            else:
                audio_24k_int16 = audio_int16

            # Base64 encode and send
            audio_b64 = base64.b64encode(audio_24k_int16.tobytes()).decode()
            await self._send_event({
                "type": "input_audio_buffer.append",
                "audio": audio_b64,
            })
        except Exception as e:
            logger.error("Error feeding audio to Realtime API: %s", e)

    async def approve_response(self):
        """HITL: User approved the pending response. Flush buffered audio to SCO."""
        if self.mode == "hitl" and self._pending_audio_chunks:
            logger.info("Response approved, flushing %d audio chunks", len(self._pending_audio_chunks))
            self._approval_event.set()

    def set_mode(self, mode: str):
        """Switch between 'autonomous' and 'hitl' voice modes."""
        self.mode = mode

    # ------------------------------------------------------------------ #
    # WebSocket lifecycle
    # ------------------------------------------------------------------ #

    async def _connect(self):
        """Open WebSocket to OpenAI Realtime API."""
        model = self.config.realtime.model
        api_key = self.config.llm.api_key
        url = f"wss://api.openai.com/v1/realtime?model={model}"

        headers = {
            "Authorization": f"Bearer {api_key}",
            "OpenAI-Beta": "realtime=v1",
        }

        try:
            self._ws = await websockets.connect(
                url,
                additional_headers=headers,
                ping_interval=20,
                ping_timeout=10,
            )
            logger.info("Connected to OpenAI Realtime API (model=%s)", model)
            self._reconnect_attempts = 0

            # Configure the session
            await self._send_session_update()

            # Start listening for events
            self._listen_task = asyncio.create_task(self._receive_loop())

        except Exception as e:
            logger.error("Failed to connect to Realtime API: %s", e)
            await self._handle_disconnect()

    async def _disconnect(self):
        """Close WebSocket cleanly."""
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        logger.info("Disconnected from Realtime API")

    async def _send_session_update(self):
        """Send session.update to configure voice, modalities, and turn detection."""
        turn_detection_config = None
        if self.config.realtime.turn_detection == "server_vad":
            turn_detection_config = {
                "type": "server_vad",
                "threshold": 0.5,
                "prefix_padding_ms": 300,
                "silence_duration_ms": self.config.audio.silence_duration_ms,
            }

        await self._send_event({
            "type": "session.update",
            "session": {
                "modalities": ["text", "audio"],
                "voice": self.config.realtime.voice,
                "instructions": self.config.llm.system_prompt,
                "input_audio_format": "pcm16",
                "output_audio_format": "pcm16",
                "turn_detection": turn_detection_config,
                "input_audio_transcription": {
                    "model": "whisper-1",
                },
            },
        })
        logger.info("Sent session.update (voice=%s, turn_detection=%s)",
                     self.config.realtime.voice, self.config.realtime.turn_detection)

    async def _send_event(self, event: dict):
        """Send a JSON event to the WebSocket."""
        if self._ws is None:
            return
        try:
            await self._ws.send(json.dumps(event))
        except websockets.exceptions.ConnectionClosed:
            logger.warning("WebSocket closed while sending event")
            await self._handle_disconnect()

    # ------------------------------------------------------------------ #
    # Receive loop and event dispatch
    # ------------------------------------------------------------------ #

    async def _receive_loop(self):
        """Listen for events from OpenAI and dispatch to handlers."""
        try:
            async for message in self._ws:
                if self.state == PipelineState.IDLE:
                    break
                try:
                    event = json.loads(message)
                    await self._handle_event(event)
                except json.JSONDecodeError:
                    logger.warning("Invalid JSON from Realtime API")
        except websockets.exceptions.ConnectionClosed as e:
            logger.warning("Realtime WebSocket closed: %s", e)
            await self._handle_disconnect()
        except asyncio.CancelledError:
            logger.info("Receive loop cancelled")
        except Exception as e:
            logger.error("Receive loop error: %s", e, exc_info=True)
            await self._handle_disconnect()

    async def _handle_event(self, event: dict):
        """Route incoming events to specific handlers."""
        event_type = event.get("type", "")

        handlers = {
            "session.created": self._on_session_created,
            "session.updated": self._on_session_updated,
            "input_audio_buffer.speech_started": self._on_speech_started,
            "input_audio_buffer.speech_stopped": self._on_speech_stopped,
            "response.audio.delta": self._on_audio_delta,
            "response.audio_transcript.delta": self._on_audio_transcript_delta,
            "conversation.item.input_audio_transcription.completed": self._on_input_transcription_completed,
            "response.done": self._on_response_done,
            "error": self._on_error,
        }

        handler = handlers.get(event_type)
        if handler:
            await handler(event)

    # ------------------------------------------------------------------ #
    # Event handlers
    # ------------------------------------------------------------------ #

    async def _on_session_created(self, event: dict):
        """Session created confirmation."""
        session_id = event.get("session", {}).get("id", "?")
        logger.info("Realtime session created: %s", session_id)

    async def _on_session_updated(self, event: dict):
        """Session configuration updated."""
        logger.info("Realtime session updated")

    async def _on_speech_started(self, event: dict):
        """Server VAD detected user speech start."""
        self.state = PipelineState.LISTENING
        self.ws_server.broadcast_sync("transcript", {"text": "", "sender": "user", "interim": True})
        logger.debug("Speech started")

    async def _on_speech_stopped(self, event: dict):
        """Server VAD detected user speech end."""
        self.state = PipelineState.PROCESSING
        logger.debug("Speech stopped, processing...")

    async def _on_audio_delta(self, event: dict):
        """Response audio chunk from OpenAI. Resample and inject into SCO."""
        if self.state == PipelineState.IDLE:
            return
        delta_b64 = event.get("delta", "")
        if not delta_b64:
            return

        try:
            # Decode base64 PCM16 at 24kHz
            audio_bytes = base64.b64decode(delta_b64)
            audio_24k = np.frombuffer(audio_bytes, dtype=np.int16)

            # Resample 24kHz -> SCO rate (e.g. 8kHz)
            sco_rate = self.config.audio.sco_sample_rate
            if sco_rate != REALTIME_OUTPUT_SAMPLE_RATE:
                audio_sco = AudioResampler.resample(
                    audio_24k.astype(np.float64),
                    REALTIME_OUTPUT_SAMPLE_RATE,
                    sco_rate,
                )
                pcm_out = audio_sco.astype(np.int16).tobytes()
            else:
                pcm_out = audio_bytes

            if self.mode == "autonomous":
                # Inject immediately
                self.state = PipelineState.SPEAKING
                await self.bt_bridge.send_command("inject_audio", {
                    "sample_rate": sco_rate,
                    "data": base64.b64encode(pcm_out).decode(),
                })
            else:
                # HITL: buffer for later
                self._pending_audio_chunks.append(pcm_out)

        except Exception as e:
            logger.error("Error processing audio delta: %s", e)

    async def _on_audio_transcript_delta(self, event: dict):
        """AI response text chunk. Broadcast to frontend."""
        text = event.get("delta", "")
        if text:
            self._pending_transcript += text
            self.ws_server.broadcast_sync(
                "transcript",
                {"text": text, "sender": "assistant", "delta": True},
            )

    async def _on_input_transcription_completed(self, event: dict):
        """User speech transcript from Whisper. Broadcast to frontend."""
        transcript = event.get("transcript", "")
        if transcript:
            self.ws_server.broadcast_sync(
                "transcript",
                {"text": transcript, "sender": "user"},
            )
            logger.info("User said: %s", transcript[:80])

    async def _on_response_done(self, event: dict):
        """Response complete. Handle HITL approval or transition back to LISTENING."""
        if self.mode == "hitl" and self._pending_audio_chunks:
            # Send full transcript to frontend for approval
            self.ws_server.broadcast_sync(
                "llm_response",
                {"text": self._pending_transcript, "approved": False},
            )
            logger.info("HITL: waiting for approval of response")
            self._approval_event.clear()
            await self._approval_event.wait()

            # Flush buffered audio to SCO
            self.state = PipelineState.SPEAKING
            sco_rate = self.config.audio.sco_sample_rate
            for chunk in self._pending_audio_chunks:
                if self.state != PipelineState.SPEAKING:
                    break
                await self.bt_bridge.send_command("inject_audio", {
                    "sample_rate": sco_rate,
                    "data": base64.b64encode(chunk).decode(),
                })
            self._pending_audio_chunks.clear()

        # Broadcast the final assistant transcript
        if self._pending_transcript:
            self.ws_server.broadcast_sync(
                "transcript",
                {"text": self._pending_transcript, "sender": "assistant"},
            )

        self._pending_transcript = ""
        self.state = PipelineState.LISTENING
        logger.info("Response done, returning to LISTENING")

    async def _on_error(self, event: dict):
        """Handle API errors."""
        error = event.get("error", {})
        logger.error("Realtime API error: type=%s, message=%s",
                     error.get("type", "?"), error.get("message", "?"))

    # ------------------------------------------------------------------ #
    # Reconnection
    # ------------------------------------------------------------------ #

    async def _handle_disconnect(self):
        """Handle WebSocket disconnection with exponential backoff retry."""
        self._ws = None
        if self.state == PipelineState.IDLE:
            return  # Don't reconnect if we're not in a call

        self._reconnect_attempts += 1
        if self._reconnect_attempts > self._max_reconnect_attempts:
            logger.error("Max reconnect attempts reached, giving up")
            self.state = PipelineState.IDLE
            self.ws_server.broadcast_sync("error", {
                "code": "REALTIME_DISCONNECTED",
                "message": "Lost connection to OpenAI Realtime API",
            })
            return

        delay = min(2 ** self._reconnect_attempts, 30)
        logger.info("Reconnecting in %ds (attempt %d/%d)",
                     delay, self._reconnect_attempts, self._max_reconnect_attempts)
        await asyncio.sleep(delay)
        await self._connect()
