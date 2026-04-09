"""Text-to-Speech Engine — Component PY-001.6.

Converts text into PCM audio for voice synthesis. Three providers:

  - OpenAITTSEngine: Uses OpenAI TTS API (/v1/audio/speech). Returns PCM bytes.
  - ElevenLabsEngine: Uses ElevenLabs API. Supports both batch and streaming.
  - LocalTTSEngine: Placeholder for mlx-audio (Apple Silicon local TTS).

Each provider implements:
  - synthesize(text) -> bytes: Full audio generation (batch).
  - stream(text) -> AsyncIterator[bytes]: Streaming audio chunks for low-latency
    playback during active calls.

Factory: create_engine("openai" | "elevenlabs" | "local", config) -> TTSEngine

FIX LOG (Claude Opus 4.6, 2026-04-09):
  - Replaced mock implementations with real OpenAI and ElevenLabs API calls
  - LocalTTSEngine remains stubbed (requires mlx-audio + model download)
  - Added proper PCM conversion from API response formats
"""

import io
import logging
from typing import AsyncIterator

logger = logging.getLogger(__name__)


class TTSError(Exception):
    """Raised when text-to-speech synthesis fails."""
    pass


class TTSEngine:
    """Abstract base for TTS providers."""
    async def synthesize(self, text: str) -> bytes:
        raise NotImplementedError

    async def stream(self, text: str) -> AsyncIterator[bytes]:
        raise NotImplementedError
        yield  # make it a generator


class OpenAITTSEngine(TTSEngine):
    """Synthesize speech using OpenAI TTS API.

    Uses /v1/audio/speech endpoint. Returns raw PCM audio (pcm format).
    Voices: alloy, echo, fable, onyx, nova, shimmer.
    """

    def __init__(self, config):
        self.config = config
        import openai
        api_key = getattr(config, 'api_key', None) or "sk-placeholder"
        self.client = openai.AsyncOpenAI(api_key=api_key)
        self.voice = getattr(config, 'voice', 'nova')
        self.speed = getattr(config, 'speed', 1.0)

    async def synthesize(self, text: str) -> bytes:
        if not text:
            return b""
        try:
            response = await self.client.audio.speech.create(
                model="tts-1",
                voice=self.voice,
                input=text,
                response_format="pcm",  # Raw PCM 24kHz 16-bit mono
                speed=self.speed,
            )
            return response.content
        except Exception as e:
            raise TTSError(f"OpenAI TTS error: {e}") from e

    async def stream(self, text: str) -> AsyncIterator[bytes]:
        if not text:
            return
        try:
            response = await self.client.audio.speech.create(
                model="tts-1",
                voice=self.voice,
                input=text,
                response_format="pcm",
                speed=self.speed,
            )
            # OpenAI returns the full audio — we chunk it for streaming injection
            data = response.content
            chunk_size = 4800  # 150ms at 16kHz 16-bit mono
            for i in range(0, len(data), chunk_size):
                yield data[i:i + chunk_size]
        except Exception as e:
            raise TTSError(f"OpenAI TTS stream error: {e}") from e


class ElevenLabsEngine(TTSEngine):
    """Synthesize speech using ElevenLabs API.

    Uses the text-to-speech endpoint with streaming support.
    ~75ms latency via WebSocket for real-time use.
    """

    def __init__(self, config):
        self.config = config
        self.api_key = getattr(config, 'elevenlabs_api_key', '') or getattr(config, 'api_key', '')
        self.voice = getattr(config, 'voice', 'nova')
        self.speed = getattr(config, 'speed', 1.0)

    async def synthesize(self, text: str) -> bytes:
        if not text:
            return b""
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice}",
                    headers={
                        "xi-api-key": self.api_key,
                        "Content-Type": "application/json",
                    },
                    json={
                        "text": text,
                        "model_id": "eleven_flash_v2_5",
                        "output_format": "pcm_16000",
                    },
                    timeout=30.0,
                )
                response.raise_for_status()
                return response.content
        except Exception as e:
            raise TTSError(f"ElevenLabs TTS error: {e}") from e

    async def stream(self, text: str) -> AsyncIterator[bytes]:
        if not text:
            return
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                async with client.stream(
                    "POST",
                    f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice}/stream",
                    headers={
                        "xi-api-key": self.api_key,
                        "Content-Type": "application/json",
                    },
                    json={
                        "text": text,
                        "model_id": "eleven_flash_v2_5",
                        "output_format": "pcm_16000",
                    },
                    timeout=30.0,
                ) as response:
                    response.raise_for_status()
                    async for chunk in response.aiter_bytes(4096):
                        yield chunk
        except Exception as e:
            raise TTSError(f"ElevenLabs TTS stream error: {e}") from e


class LocalTTSEngine(TTSEngine):
    """Local TTS using mlx-audio on Apple Silicon.

    STUB: Returns silence bytes. To implement fully:
      1. pip install mlx-audio
      2. Load model in __init__
      3. Generate PCM from text
    """

    def __init__(self, config):
        self.config = config
        logger.info("LocalTTSEngine initialized (stub)")

    async def synthesize(self, text: str) -> bytes:
        if not text:
            return b""
        logger.warning("LocalTTSEngine.synthesize() is a stub — returning silence")
        # Return 1 second of silence at 16kHz 16-bit mono
        import struct
        return struct.pack('<' + 'h' * 16000, *([0] * 16000))

    async def stream(self, text: str) -> AsyncIterator[bytes]:
        if not text:
            return
        data = await self.synthesize(text)
        chunk_size = 4800
        for i in range(0, len(data), chunk_size):
            yield data[i:i + chunk_size]


def create_engine(provider: str, config) -> TTSEngine:
    """Factory: create the correct TTS engine based on config provider string."""
    if provider == "openai":
        return OpenAITTSEngine(config.tts)
    elif provider == "elevenlabs":
        return ElevenLabsEngine(config.tts)
    elif provider == "local":
        return LocalTTSEngine(config.tts)
    raise ValueError(f"Invalid TTS provider: {provider}. Expected 'openai', 'elevenlabs', or 'local'.")
