"""Tests for STT Engine (PY-001.5).

Tests use mocked API clients — no real API calls are made.
"""
import pytest
import numpy as np
from unittest.mock import AsyncMock, MagicMock, patch
from osm_core.config import Config, STTConfig
from osm_core.stt.engine import create_engine, WhisperLocalEngine, OpenAISTTEngine


@pytest.fixture
def config():
    c = Config()
    c.stt = STTConfig(provider="local")
    return c


@pytest.mark.asyncio
async def test_transcribe_local(config):
    """UT-PY-001.5-01: Local Whisper transcribe returns string."""
    engine = create_engine("local", config)
    audio = np.zeros(16000)
    result = await engine.transcribe(audio)
    assert isinstance(result, str)
    assert len(result) > 0  # Stub returns placeholder text


@pytest.mark.asyncio
async def test_transcribe_openai():
    """UT-PY-001.5-02: OpenAI STT transcribe (mocked API)."""
    c = Config()
    c.stt = STTConfig(provider="openai")
    engine = create_engine("openai", c)

    # Mock the OpenAI client's transcription endpoint
    mock_response = MagicMock()
    mock_response.text = "Hello from Whisper"
    engine.client = AsyncMock()
    engine.client.audio.transcriptions.create = AsyncMock(return_value=mock_response)

    audio = b"\x00" * 32000
    result = await engine.transcribe(audio)
    assert isinstance(result, str)
    assert result == "Hello from Whisper"
    engine.client.audio.transcriptions.create.assert_called_once()


def test_provider_factory(config):
    """UT-PY-001.5-03: Provider factory creates correct engine types."""
    e1 = create_engine("local", config)
    assert isinstance(e1, WhisperLocalEngine)
    e2 = create_engine("openai", config)
    assert isinstance(e2, OpenAISTTEngine)

    with pytest.raises(ValueError):
        create_engine("invalid_provider", config)


@pytest.mark.asyncio
async def test_empty_audio(config):
    """UT-PY-001.5-04: Empty audio returns empty string."""
    engine = create_engine("local", config)
    # numpy empty
    result = await engine.transcribe(np.array([]))
    assert result == ""
    # bytes empty
    result2 = await engine.transcribe(b"")
    assert result2 == ""
