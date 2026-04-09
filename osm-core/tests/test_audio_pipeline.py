import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from osm_core.audio.pipeline import AudioPipeline, PipelineState

@pytest.fixture
def mocks():
    return {
        "llm": AsyncMock(),
        "stt": AsyncMock(),
        "tts": AsyncMock(),
        "vad": AsyncMock(),
        "bt": AsyncMock(),
        "ws": MagicMock()
    }

@pytest.fixture
def pipeline(mocks):
    return AudioPipeline(
        llm_engine=mocks["llm"],
        stt_engine=mocks["stt"],
        tts_engine=mocks["tts"],
        vad=mocks["vad"],
        bt_bridge=mocks["bt"],
        ws_server=mocks["ws"]
    )

@pytest.mark.asyncio
async def test_pipeline_states(pipeline):
    """UT-PY-001.9-01: Pipeline state machine transitions"""
    assert pipeline.state == PipelineState.IDLE
    
    pipeline.start_call("+12345")
    assert pipeline.state == PipelineState.LISTENING
    pipeline.mocks = None  # Cleanup for clarity
    
    pipeline.end_call()
    assert pipeline.state == PipelineState.IDLE

@pytest.mark.asyncio
async def test_vad_triggers_stt(pipeline, mocks):
    """UT-PY-001.9-02: VAD triggers STT"""
    pipeline.start_call("+12345")
    
    # Mock VAD to detect end of speech
    mocks["vad"].process.return_value = (True, True)
    mocks["stt"].transcribe.return_value = "Hello"
    mocks["llm"].generate.return_value = "Hi there"
    
    # Mock TTS to act as block until we yield an empty chunk
    async def mock_tts_stream(*args):
        yield b"audio_chunk"
    mocks["tts"].stream = mock_tts_stream
    
    await pipeline.feed_audio(b"fake_pcm")
    
    # Give the background task a chance to run
    await asyncio.sleep(0.05)
    
    assert pipeline.state == PipelineState.LISTENING # Finishes up
    mocks["stt"].transcribe.assert_called_once()
    mocks["llm"].generate.assert_called_once()

@pytest.mark.asyncio
async def test_autonomous_mode(pipeline, mocks):
    """UT-PY-001.9-04: LLM triggers TTS immediately in auto mode"""
    pipeline.mode = "autonomous"
    pipeline.start_call("+12345")
    
    mocks["vad"].process.return_value = (True, True)
    mocks["stt"].transcribe.return_value = "Hello"
    mocks["llm"].generate.return_value = "Auto response"
    
    async def mock_tts_stream(*args):
        yield b"chunk1"
        yield b"chunk2"
    mocks["tts"].stream = mock_tts_stream
    
    await pipeline.feed_audio(b"pcm")
    await asyncio.sleep(0.05)
    
    assert mocks["bt"].inject_audio.call_count == 2
    mocks["ws"].broadcast_sync.assert_any_call({"type": "transcript", "payload": {"text": "Auto response", "sender": "assistant"}})
    
@pytest.mark.asyncio
async def test_hitl_mode(pipeline, mocks):
    """UT-PY-001.9-05: LLM waits in HITL mode"""
    pipeline.mode = "hitl"
    pipeline.start_call("+12345")
    
    mocks["vad"].process.return_value = (True, True)
    mocks["stt"].transcribe.return_value = "Hello"
    mocks["llm"].generate.return_value = "HITL draft"
    
    async def mock_tts_stream(*args):
        yield b"chunk"
    mocks["tts"].stream = mock_tts_stream
    
    await pipeline.feed_audio(b"pcm")
    await asyncio.sleep(0.01)
    
    # Pipeline should be paused in PROCESSING
    assert pipeline.state == PipelineState.PROCESSING
    assert mocks["bt"].inject_audio.call_count == 0
    
    # Approve response
    await pipeline.approve_response()
    await asyncio.sleep(0.05)
    
    # Now it should be complete
    assert mocks["bt"].inject_audio.call_count == 1
    assert pipeline.state == PipelineState.LISTENING
