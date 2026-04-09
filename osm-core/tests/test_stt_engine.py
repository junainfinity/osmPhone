"""
test_stt_engine.py - Tests for STT Engine (PY-001.5)
"""
import pytest
import numpy as np
from osm_core.config import Config, STTConfig
from osm_core.stt.engine import create_engine, WhisperLocalEngine, OpenAISTTEngine

@pytest.fixture
def config():
    c = Config()
    c.stt = STTConfig(provider="local")
    return c

@pytest.mark.asyncio
async def test_transcribe_local(config):
    # UT-PY-001.5-01: Local Whisper transcribe
    engine = create_engine("local", config)
    audio = np.zeros(16000)
    result = await engine.transcribe(audio)
    assert isinstance(result, str)
    assert result == "mock local transcription"

@pytest.mark.asyncio
async def test_transcribe_openai():
    # UT-PY-001.5-02: OpenAI STT transcribe
    c = Config()
    c.stt = STTConfig(provider="openai")
    engine = create_engine("openai", c)
    audio = b"\x00" * 32000
    result = await engine.transcribe(audio)
    assert isinstance(result, str)
    assert result == "mock openai transcription"

def test_provider_factory(config):
    # UT-PY-001.5-03: Provider factory
    e1 = create_engine("local", config)
    assert isinstance(e1, WhisperLocalEngine)
    e2 = create_engine("openai", config)
    assert isinstance(e2, OpenAISTTEngine)

@pytest.mark.asyncio
async def test_empty_audio(config):
    # UT-PY-001.5-04: Empty audio returns empty
    engine = create_engine("local", config)
    audio = np.array([])
    result = await engine.transcribe(audio)
    assert result == ""
