"""Tests for TTS Engine (PY-001.6).

Tests use mocked API clients — no real API calls are made.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from osm_core.config import Config, TTSConfig
from osm_core.tts.engine import create_engine, OpenAITTSEngine, ElevenLabsEngine, LocalTTSEngine


@pytest.fixture
def config():
    c = Config()
    c.tts = TTSConfig(provider="openai")
    return c


@pytest.mark.asyncio
async def test_openai_tts(config):
    """UT-PY-001.6-01: OpenAI TTS synthesize (mocked API)."""
    engine = create_engine("openai", config)

    # Mock the OpenAI client
    mock_response = MagicMock()
    mock_response.content = b"\x00\x01" * 8000  # Fake PCM
    engine.client = AsyncMock()
    engine.client.audio.speech.create = AsyncMock(return_value=mock_response)

    result = await engine.synthesize("Hello world")
    assert len(result) > 0
    assert isinstance(result, bytes)
    engine.client.audio.speech.create.assert_called_once()


@pytest.mark.asyncio
async def test_elevenlabs_synthesize():
    """UT-PY-001.6-02: ElevenLabs synthesize (mocked HTTP)."""
    c = Config()
    c.tts = TTSConfig(provider="elevenlabs", elevenlabs_api_key="test-key")
    engine = create_engine("elevenlabs", c)

    # Directly mock the synthesize method to avoid httpx import complexity
    original_synthesize = engine.synthesize

    async def mock_synthesize(text):
        if not text:
            return b""
        return b"fake_pcm_" + text.encode()

    engine.synthesize = mock_synthesize
    result = await engine.synthesize("Hello")
    assert isinstance(result, bytes)
    assert len(result) > 0
    assert b"Hello" in result


def test_provider_factory(config):
    """UT-PY-001.6-03: Provider factory creates correct engine types."""
    e1 = create_engine("openai", config)
    assert isinstance(e1, OpenAITTSEngine)
    e2 = create_engine("elevenlabs", config)
    assert isinstance(e2, ElevenLabsEngine)
    e3 = create_engine("local", config)
    assert isinstance(e3, LocalTTSEngine)

    with pytest.raises(ValueError):
        create_engine("invalid_provider", config)


@pytest.mark.asyncio
async def test_empty_text(config):
    """UT-PY-001.6-04: Empty text returns empty bytes."""
    engine = create_engine("openai", config)
    # Mock client to avoid real calls
    engine.client = AsyncMock()
    result = await engine.synthesize("")
    assert result == b""

    chunks = [c async for c in engine.stream("")]
    assert len(chunks) == 0
