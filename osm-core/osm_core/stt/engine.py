"""Speech-to-Text Engine — Component PY-001.5.

Converts PCM audio into transcribed text. Two providers:

  - OpenAISTTEngine: Uses OpenAI Whisper API (cloud). Sends audio as WAV to
    the /v1/audio/transcriptions endpoint. Requires OPENAI_API_KEY.

  - WhisperLocalEngine: Placeholder for lightning-whisper-mlx (Apple Silicon).
    Returns a stub transcription. Real implementation requires:
      pip install lightning-whisper-mlx
    and loading the model at init time.

Factory: create_engine("local" | "openai", config) -> STTEngine

FIX LOG (Claude Opus 4.6, 2026-04-09):
  - Replaced mock implementations with real OpenAI Whisper API calls
  - WhisperLocalEngine still stubbed (requires Apple Silicon + model download)
  - Added WAV header construction for raw PCM -> file-like upload
"""

import io
import struct
import logging
from typing import Union

import numpy as np

logger = logging.getLogger(__name__)


class STTError(Exception):
    """Raised when speech-to-text transcription fails."""
    pass


class STTEngine:
    """Abstract base for STT providers."""
    async def transcribe(self, audio_pcm: Union[bytes, np.ndarray], sample_rate: int = 16000) -> str:
        raise NotImplementedError


def _pcm_to_wav(pcm_data: bytes, sample_rate: int = 16000, channels: int = 1, sample_width: int = 2) -> bytes:
    """Wrap raw PCM bytes in a WAV header for API upload."""
    data_size = len(pcm_data)
    wav = io.BytesIO()
    # RIFF header
    wav.write(b"RIFF")
    wav.write(struct.pack('<I', 36 + data_size))
    wav.write(b"WAVE")
    # fmt chunk
    wav.write(b"fmt ")
    wav.write(struct.pack('<I', 16))  # chunk size
    wav.write(struct.pack('<H', 1))   # PCM format
    wav.write(struct.pack('<H', channels))
    wav.write(struct.pack('<I', sample_rate))
    wav.write(struct.pack('<I', sample_rate * channels * sample_width))  # byte rate
    wav.write(struct.pack('<H', channels * sample_width))  # block align
    wav.write(struct.pack('<H', sample_width * 8))  # bits per sample
    # data chunk
    wav.write(b"data")
    wav.write(struct.pack('<I', data_size))
    wav.write(pcm_data)
    return wav.getvalue()


class OpenAISTTEngine(STTEngine):
    """Transcribe audio using OpenAI Whisper API.

    Sends PCM audio as a WAV file to /v1/audio/transcriptions.
    Requires: openai SDK + valid API key in config.
    """

    def __init__(self, config):
        self.config = config
        import openai
        api_key = getattr(config, 'api_key', None) or "sk-placeholder"
        self.client = openai.AsyncOpenAI(api_key=api_key)
        self.model = getattr(config, 'model', 'whisper-1')
        self.language = getattr(config, 'language', 'en')

    async def transcribe(self, audio_pcm: Union[bytes, np.ndarray], sample_rate: int = 16000) -> str:
        if isinstance(audio_pcm, np.ndarray):
            audio_pcm = (audio_pcm * 32768).astype(np.int16).tobytes()
        if len(audio_pcm) == 0:
            return ""

        try:
            wav_data = _pcm_to_wav(audio_pcm, sample_rate)
            wav_file = io.BytesIO(wav_data)
            wav_file.name = "audio.wav"

            response = await self.client.audio.transcriptions.create(
                model=self.model,
                file=wav_file,
                language=self.language,
            )
            return response.text.strip()
        except Exception as e:
            raise STTError(f"OpenAI STT error: {e}") from e


class WhisperLocalEngine(STTEngine):
    """Local STT using lightning-whisper-mlx on Apple Silicon.

    STUB: Returns placeholder text. To implement fully:
      1. pip install lightning-whisper-mlx
      2. Load model in __init__: from lightning_whisper_mlx import LightningWhisperMLX
      3. Call model.transcribe() with audio numpy array
    The local engine avoids API calls — runs entirely on-device using MLX.
    """

    def __init__(self, config):
        self.config = config
        self.model_name = getattr(config, 'model', 'distil-large-v3')
        logger.info("WhisperLocalEngine initialized (stub) with model=%s", self.model_name)

    async def transcribe(self, audio_pcm: Union[bytes, np.ndarray], sample_rate: int = 16000) -> str:
        if isinstance(audio_pcm, np.ndarray) and len(audio_pcm) == 0:
            return ""
        if isinstance(audio_pcm, bytes) and len(audio_pcm) == 0:
            return ""
        # TODO: Replace with real lightning-whisper-mlx inference
        # from lightning_whisper_mlx import LightningWhisperMLX
        # whisper = LightningWhisperMLX(model=self.model_name, batch_size=12, quant=None)
        # result = whisper.transcribe(audio_path_or_array)
        # return result["text"]
        logger.warning("WhisperLocalEngine.transcribe() is a stub — returning placeholder")
        return "[local STT placeholder — install lightning-whisper-mlx for real transcription]"


def create_engine(provider: str, config) -> STTEngine:
    """Factory: create the correct STT engine based on config provider string."""
    if provider == "local":
        return WhisperLocalEngine(config.stt)
    elif provider == "openai":
        return OpenAISTTEngine(config.stt)
    raise ValueError(f"Invalid STT provider: {provider}. Expected 'local' or 'openai'.")
