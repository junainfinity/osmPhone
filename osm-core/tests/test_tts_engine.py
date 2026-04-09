"""
test_tts_engine.py - Tests for TTS Engine (PY-001.6)
"""
import pytest
from osm_core.config import Config, TTSConfig
from osm_core.tts.engine import create_engine, OpenAITTSEngine, ElevenLabsEngine

@pytest.fixture
def config():
    c = Config()
    c.tts = TTSConfig(provider="openai")
    return c

@pytest.mark.asyncio
async def test_openai_tts(config):
    # UT-PY-001.6-01: OpenAI TTS synthesize
    engine = create_engine("openai", config)
    res = await engine.synthesize("Hello world")
    assert len(res) > 0
    assert b"mock-pcm-openai-Hello world" in res

@pytest.mark.asyncio
async def test_elevenlabs_stream():
    # UT-PY-001.6-02: ElevenLabs stream
    c = Config()
    c.tts = TTSConfig(provider="elevenlabs")
    engine = create_engine("elevenlabs", c)
    chunks = [chunk async for chunk in engine.stream("Hello world")]
    assert len(chunks) == 3
    assert b"".join(chunks) == b"chunks_of_elevenlabs"

def test_provider_factory(config):
    # UT-PY-001.6-03: Provider factory
    e1 = create_engine("openai", config)
    assert isinstance(e1, OpenAITTSEngine)
    e2 = create_engine("elevenlabs", config)
    assert isinstance(e2, ElevenLabsEngine)

@pytest.mark.asyncio
async def test_empty_text(config):
    # UT-PY-001.6-04: Empty text returns empty
    engine = create_engine("openai", config)
    res = await engine.synthesize("")
    assert res == b""
    chunks = [c async for c in engine.stream("")]
    assert len(chunks) == 0
