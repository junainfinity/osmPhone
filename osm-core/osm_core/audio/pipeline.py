"""Real-time audio pipeline — Component PY-001.9.

Orchestrates the voice call loop: SCO audio -> VAD -> STT -> LLM -> TTS -> SCO inject.

State machine:
  IDLE -> LISTENING (call starts) -> PROCESSING (speech ended, running STT/LLM) ->
  SPEAKING (TTS output playing) -> LISTENING (ready for next utterance)

Two voice modes:
  - autonomous: STT -> LLM -> TTS runs without human intervention.
  - hitl (human-in-the-loop): After LLM generates a response, pipeline pauses
    and sends the text to the frontend. User can edit and approve. Only then
    does TTS run and audio get injected.

Integration points:
  - Receives PCM frames from bt_bridge (called by main.py event handler)
  - Sends inject_audio commands back to bt_bridge for SCO output
  - Broadcasts transcript/llm_response events to frontend via ws_server

FIX LOG (Claude Opus 4.6, 2026-04-09):
  - Changed broadcast_sync() calls to use proper (event_type, data) signature
    instead of single dict — matching WSServer.broadcast_sync(str, dict)
  - Pipeline now correctly calls vad.process() which returns (is_speech, end_of_speech)
  - bt_bridge.inject_audio changed to bt_bridge.send_command("inject_audio", ...)
"""

from enum import Enum, auto
import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class PipelineState(Enum):
    IDLE = auto()
    LISTENING = auto()
    PROCESSING = auto()
    SPEAKING = auto()


class AudioPipeline:
    """Real-time voice pipeline: VAD -> STT -> LLM -> TTS -> audio injection."""

    def __init__(self,
                 llm_engine,
                 stt_engine,
                 tts_engine,
                 vad,
                 bt_bridge,
                 ws_server,
                 mode: str = "autonomous"):
        self.llm_engine = llm_engine
        self.stt_engine = stt_engine
        self.tts_engine = tts_engine
        self.vad = vad
        self.bt_bridge = bt_bridge
        self.ws_server = ws_server
        self.mode = mode

        self.state = PipelineState.IDLE
        self._current_audio_buffer = bytearray()
        self._pending_llm_response: str = ""
        self._approval_event: Optional[asyncio.Event] = None
        self._process_task: Optional[asyncio.Task] = None
        self._contact = "Unknown"
        self._history = []

    def start_call(self, contact: str):
        """Transition to LISTENING when a call begins."""
        self.state = PipelineState.LISTENING
        self._contact = contact
        self._current_audio_buffer.clear()
        self._history.clear()
        self._approval_event = asyncio.Event()
        # Reset VAD streaming state for the new call
        if hasattr(self.vad, 'reset'):
            self.vad.reset()
        # Notify frontend — uses (event_type, data) signature
        self.ws_server.broadcast_sync("call_active", {"active": True, "contact": contact})
        logger.info("Pipeline started LISTENING for %s", contact)

    def end_call(self):
        """Transition to IDLE when call ends."""
        self.state = PipelineState.IDLE
        if self._process_task and not self._process_task.done():
            self._process_task.cancel()
        self.ws_server.broadcast_sync("call_active", {"active": False})
        logger.info("Pipeline returned to IDLE")

    def set_mode(self, mode: str):
        """Switch between 'autonomous' and 'hitl' voice modes."""
        self.mode = mode

    async def feed_audio(self, pcm_data: bytes):
        """Feed a PCM audio frame from the SCO channel.

        Called by main.py whenever a sco_audio event arrives from bt_bridge.
        The VAD determines when the caller has finished speaking, then
        triggers the STT -> LLM -> TTS pipeline.
        """
        if self.state != PipelineState.LISTENING:
            return

        self._current_audio_buffer.extend(pcm_data)

        # VAD.process() returns (is_speech, end_of_speech) per frame
        is_speech, end_of_speech = await self.vad.process(pcm_data)

        if end_of_speech:
            self.state = PipelineState.PROCESSING
            logger.info("End of speech detected, moving to PROCESSING")
            audio_to_process = bytes(self._current_audio_buffer)
            self._current_audio_buffer.clear()
            self._process_task = asyncio.create_task(self._run_pipeline(audio_to_process))

    async def approve_response(self):
        """Called when user approves an LLM response in HITL mode."""
        if self.state == PipelineState.PROCESSING and self.mode == "hitl":
            logger.info("Response approved by user")
            self._approval_event.set()

    async def _run_pipeline(self, audio_data: bytes):
        """Internal: Run the full STT -> LLM -> TTS pipeline on one utterance."""
        try:
            # 1. STT — convert caller's speech to text
            user_text = await self.stt_engine.transcribe(audio_data)
            self.ws_server.broadcast_sync("transcript", {"text": user_text, "sender": "user"})
            self._history.append({"role": "user", "content": user_text})

            # 2. LLM — generate response
            self._pending_llm_response = await self.llm_engine.generate(self._history)
            self._history.append({"role": "assistant", "content": self._pending_llm_response})

            # 3. Mode check — in HITL, wait for user approval before speaking
            if self.mode == "hitl":
                self.ws_server.broadcast_sync(
                    "llm_response",
                    {"text": self._pending_llm_response, "approved": False}
                )
                self._approval_event.clear()
                await self._approval_event.wait()

            self.ws_server.broadcast_sync(
                "transcript",
                {"text": self._pending_llm_response, "sender": "assistant"}
            )

            # 4. TTS — synthesize voice and inject into SCO
            self.state = PipelineState.SPEAKING
            logger.info("Moving to SPEAKING state")

            async for chunk in self.tts_engine.stream(self._pending_llm_response):
                # Send audio back through BT bridge to SCO channel
                import base64
                await self.bt_bridge.send_command("inject_audio", {
                    "sample_rate": 8000,
                    "data": base64.b64encode(chunk).decode(),
                })

            # Done speaking — ready for next utterance
            self.state = PipelineState.LISTENING
            logger.info("Finished speaking, returning to LISTENING")

        except asyncio.CancelledError:
            logger.info("Pipeline task cancelled (call ended)")
        except Exception as e:
            logger.error("Pipeline error: %s", e, exc_info=True)
            self.state = PipelineState.LISTENING
