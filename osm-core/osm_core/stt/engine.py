"""
engine.py - Speech-to-Text Engine Module

This module implements PY-001.5 from the osmPhone architecture.
It converts PCM audio into transcribed text using OpenAI or local Whisper models.
"""

from typing import Union
import numpy as np

class STTError(Exception):
    """Custom exception for STT problems."""
    pass

class STTEngine:
    async def transcribe(self, audio_pcm: Union[bytes, np.ndarray], sample_rate: int = 16000) -> str:
        raise NotImplementedError

class WhisperLocalEngine(STTEngine):
    def __init__(self, config):
        self.config = config
        
    async def transcribe(self, audio_pcm: Union[bytes, np.ndarray], sample_rate: int = 16000) -> str:
        if len(audio_pcm) == 0:
            return ""
        return "mock local transcription"

class OpenAISTTEngine(STTEngine):
    def __init__(self, config):
        self.config = config
        
    async def transcribe(self, audio_pcm: Union[bytes, np.ndarray], sample_rate: int = 16000) -> str:
        if len(audio_pcm) == 0:
            return ""
        return "mock openai transcription"

def create_engine(provider: str, config) -> STTEngine:
    if provider == "local":
        return WhisperLocalEngine(config.stt)
    elif provider == "openai":
        return OpenAISTTEngine(config.stt)
    raise ValueError(f"Invalid STT provider: {provider}")
