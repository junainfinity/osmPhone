from enum import Enum, auto
import asyncio
import logging
from typing import Optional, Callable, Awaitable

logger = logging.getLogger(__name__)

class PipelineState(Enum):
    IDLE = auto()
    LISTENING = auto()
    PROCESSING = auto()
    SPEAKING = auto()

class AudioPipeline:
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
        self.state = PipelineState.LISTENING
        self._contact = contact
        self._current_audio_buffer.clear()
        self._history.clear()
        self._approval_event = asyncio.Event()
        self.ws_server.broadcast_sync({"type": "call_active", "payload": {"active": True, "contact": contact}})
        logger.info("Pipeline started LISTENING")

    def end_call(self):
        self.state = PipelineState.IDLE
        if self._process_task and not self._process_task.done():
            self._process_task.cancel()
        self.ws_server.broadcast_sync({"type": "call_active", "payload": {"active": False}})
        logger.info("Pipeline returned to IDLE")

    def set_mode(self, mode: str):
        self.mode = mode

    async def feed_audio(self, pcm_data: bytes):
        if self.state != PipelineState.LISTENING:
            return
            
        self._current_audio_buffer.extend(pcm_data)
        
        # In a real scenario, VAD processes chunks. For this mockup, we just pass to VAD.
        is_speech, end_of_speech = await self.vad.process(pcm_data)
        if end_of_speech:
            self.state = PipelineState.PROCESSING
            logger.info("End of speech detected. Moving to PROCESSING")
            audio_to_process = bytes(self._current_audio_buffer)
            self._current_audio_buffer.clear()
            
            # Fire and forget the processing pipeline
            self._process_task = asyncio.create_task(self._run_pipeline(audio_to_process))

    async def approve_response(self):
        if self.state == PipelineState.PROCESSING and self.mode == "hitl":
            logger.info("Response approved")
            self._approval_event.set()

    async def _run_pipeline(self, audio_data: bytes):
        try:
            # 1. STT
            user_text = await self.stt_engine.transcribe(audio_data)
            self.ws_server.broadcast_sync({"type": "transcript", "payload": {"text": user_text, "sender": "user"}})
            self._history.append({"role": "user", "content": user_text})
            
            # 2. LLM
            self._pending_llm_response = await self.llm_engine.generate(self._history)
            self._history.append({"role": "assistant", "content": self._pending_llm_response})
            
            # 3. Mode Check (HITL / Autonomous)
            if self.mode == "hitl":
                self.ws_server.broadcast_sync({
                    "type": "llm_response", 
                    "payload": {"text": self._pending_llm_response, "approved": False}
                })
                self._approval_event.clear()
                await self._approval_event.wait()
            
            self.ws_server.broadcast_sync({"type": "transcript", "payload": {"text": self._pending_llm_response, "sender": "assistant"}})
            
            # 4. TTS
            self.state = PipelineState.SPEAKING
            logger.info("Moving to SPEAKING state")
            
            async for chunk in self.tts_engine.stream(self._pending_llm_response):
                await self.bt_bridge.inject_audio(chunk)
                
            # Done
            self.state = PipelineState.LISTENING
            logger.info("Finished speaking, returning to LISTENING")
            
        except asyncio.CancelledError:
            logger.info("Pipeline task cancelled")
        except Exception as e:
            logger.error(f"Pipeline error: {e}")
            self.state = PipelineState.LISTENING
