"""Tests for Audio Pipeline (PY-001.9).

Tests use fully mocked dependencies (LLM, STT, TTS, VAD, bridge, WS server).
"""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from osm_core.audio.pipeline import AudioPipeline, PipelineState


@pytest.fixture
def mocks():
    ws = MagicMock()
    ws.broadcast_sync = MagicMock()  # Sync method on real WSServer
    return {
        "llm": AsyncMock(),
        "stt": AsyncMock(),
        "tts": AsyncMock(),
        "vad": AsyncMock(),
        "bt": AsyncMock(),
        "ws": ws,
    }


@pytest.fixture
def pipeline(mocks):
    return AudioPipeline(
        llm_engine=mocks["llm"],
        stt_engine=mocks["stt"],
        tts_engine=mocks["tts"],
        vad=mocks["vad"],
        bt_bridge=mocks["bt"],
        ws_server=mocks["ws"],
    )


@pytest.mark.asyncio
async def test_pipeline_states(pipeline):
    """UT-PY-001.9-01: Pipeline state machine transitions."""
    assert pipeline.state == PipelineState.IDLE

    pipeline.start_call("+12345")
    assert pipeline.state == PipelineState.LISTENING

    pipeline.end_call()
    assert pipeline.state == PipelineState.IDLE


@pytest.mark.asyncio
async def test_vad_triggers_stt(pipeline, mocks):
    """UT-PY-001.9-02: VAD end-of-speech triggers STT."""
    pipeline.start_call("+12345")

    mocks["vad"].process.return_value = (True, True)  # speech ended
    mocks["stt"].transcribe.return_value = "Hello"
    mocks["llm"].generate.return_value = "Hi there"

    async def mock_tts_stream(*args):
        yield b"audio_chunk"
    mocks["tts"].stream = mock_tts_stream

    await pipeline.feed_audio(b"fake_pcm")
    await asyncio.sleep(0.1)

    assert pipeline.state == PipelineState.LISTENING
    mocks["stt"].transcribe.assert_called_once()
    mocks["llm"].generate.assert_called_once()


@pytest.mark.asyncio
async def test_autonomous_mode(pipeline, mocks):
    """UT-PY-001.9-04: In autonomous mode, TTS runs immediately."""
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
    await asyncio.sleep(0.1)

    # bt_bridge.send_command called for each TTS chunk (inject_audio)
    assert mocks["bt"].send_command.call_count == 2
    # broadcast_sync uses (event_type, data) signature
    mocks["ws"].broadcast_sync.assert_any_call(
        "transcript", {"text": "Auto response", "sender": "assistant"}
    )


@pytest.mark.asyncio
async def test_hitl_mode(pipeline, mocks):
    """UT-PY-001.9-05: In HITL mode, pipeline waits for approval."""
    pipeline.mode = "hitl"
    pipeline.start_call("+12345")

    mocks["vad"].process.return_value = (True, True)
    mocks["stt"].transcribe.return_value = "Hello"
    mocks["llm"].generate.return_value = "HITL draft"

    async def mock_tts_stream(*args):
        yield b"chunk"
    mocks["tts"].stream = mock_tts_stream

    await pipeline.feed_audio(b"pcm")
    await asyncio.sleep(0.05)

    # Pipeline should be paused waiting for approval
    assert pipeline.state == PipelineState.PROCESSING
    assert mocks["bt"].send_command.call_count == 0

    # Approve response
    await pipeline.approve_response()
    await asyncio.sleep(0.1)

    # Now TTS should have run
    assert mocks["bt"].send_command.call_count == 1
    assert pipeline.state == PipelineState.LISTENING
