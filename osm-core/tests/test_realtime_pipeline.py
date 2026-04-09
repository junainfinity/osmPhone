"""Tests for OpenAI Realtime Audio Pipeline (PY-001.10).

Tests use a fully mocked WebSocket and dependencies.
No real OpenAI API key needed.
"""
import pytest
import asyncio
import json
import base64
import struct
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np

from osm_core.audio.realtime import RealtimeAudioPipeline, REALTIME_INPUT_SAMPLE_RATE
from osm_core.audio.pipeline import PipelineState
from osm_core.config import Config, RealtimeConfig, LLMConfig, AudioConfig, VoiceModeConfig


def make_config(**overrides):
    """Create a test Config with realtime enabled."""
    cfg = Config()
    cfg.realtime = RealtimeConfig(enabled=True, voice="alloy", turn_detection="server_vad")
    cfg.llm = LLMConfig(api_key="test-key-123", system_prompt="You are a test assistant.")
    cfg.audio = AudioConfig(sco_sample_rate=8000, silence_duration_ms=700)
    cfg.voice_mode = VoiceModeConfig(default="autonomous")
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


class MockWebSocket:
    """Mock WebSocket that records sent messages and can inject received events."""

    def __init__(self):
        self.sent_messages = []
        self._recv_queue = asyncio.Queue()
        self.closed = False
        self.close = AsyncMock()

    async def send(self, data):
        self.sent_messages.append(data)

    async def recv(self):
        return await self._recv_queue.get()

    def inject_event(self, event: dict):
        """Inject a server event to be received by the pipeline."""
        self._recv_queue.put_nowait(json.dumps(event))

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            msg = await asyncio.wait_for(self._recv_queue.get(), timeout=0.5)
            return msg
        except asyncio.TimeoutError:
            raise StopAsyncIteration


@pytest.fixture
def mock_ws():
    return MockWebSocket()


@pytest.fixture
def pipeline(mock_ws):
    config = make_config()
    bt = AsyncMock()
    ws_server = MagicMock()
    ws_server.broadcast_sync = MagicMock()
    ws_server.broadcast = AsyncMock()

    with patch("osm_core.audio.realtime.websockets.connect", new_callable=AsyncMock, return_value=mock_ws):
        p = RealtimeAudioPipeline(
            config=config,
            bt_bridge=bt,
            ws_server=ws_server,
            mode="autonomous",
        )
    return p, mock_ws, bt, ws_server


@pytest.mark.asyncio
async def test_state_transitions(pipeline):
    """UT-PY-001.10-01: Pipeline state machine transitions."""
    p, mock_ws, bt, ws = pipeline
    assert p.state == PipelineState.IDLE

    with patch("osm_core.audio.realtime.websockets.connect", new_callable=AsyncMock, return_value=mock_ws):
        p.start_call("+12345")
    assert p.state == PipelineState.LISTENING

    p.end_call()
    assert p.state == PipelineState.IDLE


@pytest.mark.asyncio
async def test_websocket_connection(pipeline):
    """UT-PY-001.10-02: WebSocket connects with correct URL and headers."""
    p, mock_ws, bt, ws = pipeline

    with patch("osm_core.audio.realtime.websockets.connect", new_callable=AsyncMock, return_value=mock_ws) as mock_connect:
        p.start_call("+12345")
        await asyncio.sleep(0.1)

        mock_connect.assert_called_once()
        call_args = mock_connect.call_args
        url = call_args[0][0]
        headers = call_args[1].get("additional_headers", {})

        assert "wss://api.openai.com/v1/realtime" in url
        assert "gpt-4o-realtime-preview" in url
        assert headers.get("Authorization") == "Bearer test-key-123"
        assert headers.get("OpenAI-Beta") == "realtime=v1"

    p.end_call()


@pytest.mark.asyncio
async def test_session_update_sent(pipeline):
    """UT-PY-001.10-03: session.update sent after WebSocket connection."""
    p, mock_ws, bt, ws = pipeline

    with patch("osm_core.audio.realtime.websockets.connect", new_callable=AsyncMock, return_value=mock_ws):
        p.start_call("+12345")
        await asyncio.sleep(0.1)

    # First sent message should be session.update
    assert len(mock_ws.sent_messages) >= 1
    session_update = json.loads(mock_ws.sent_messages[0])
    assert session_update["type"] == "session.update"
    session = session_update["session"]
    assert session["voice"] == "alloy"
    assert session["modalities"] == ["text", "audio"]
    assert session["input_audio_format"] == "pcm16"
    assert session["output_audio_format"] == "pcm16"
    assert "You are a test assistant" in session["instructions"]
    assert session["turn_detection"]["type"] == "server_vad"

    p.end_call()


@pytest.mark.asyncio
async def test_feed_audio_resamples_and_sends(pipeline):
    """UT-PY-001.10-04: feed_audio resamples 8kHz->24kHz and sends input_audio_buffer.append."""
    p, mock_ws, bt, ws = pipeline

    with patch("osm_core.audio.realtime.websockets.connect", new_callable=AsyncMock, return_value=mock_ws):
        p.start_call("+12345")
        await asyncio.sleep(0.1)

    # Manually set _ws since _connect runs as a task and may not fully wire
    p._ws = mock_ws

    # Create 20ms of 8kHz audio (160 samples * 2 bytes = 320 bytes)
    num_samples_8k = 160
    audio_8k = np.zeros(num_samples_8k, dtype=np.int16)
    audio_8k[0] = 1000  # non-zero sample for verification

    initial_count = len(mock_ws.sent_messages)
    await p.feed_audio(audio_8k.tobytes())

    # Should have sent an input_audio_buffer.append event
    assert len(mock_ws.sent_messages) > initial_count
    append_event = json.loads(mock_ws.sent_messages[-1])
    assert append_event["type"] == "input_audio_buffer.append"

    # Verify the audio is base64-encoded and resampled to 24kHz
    decoded = base64.b64decode(append_event["audio"])
    resampled = np.frombuffer(decoded, dtype=np.int16)
    # 160 samples at 8kHz = 20ms -> 480 samples at 24kHz
    expected_samples = int(num_samples_8k * REALTIME_INPUT_SAMPLE_RATE / 8000)
    assert len(resampled) == expected_samples

    p.end_call()


@pytest.mark.asyncio
async def test_audio_delta_resampled_and_injected(pipeline):
    """UT-PY-001.10-05: response.audio.delta resampled 24kHz->8kHz and injected."""
    p, mock_ws, bt, ws = pipeline

    with patch("osm_core.audio.realtime.websockets.connect", new_callable=AsyncMock, return_value=mock_ws):
        p.start_call("+12345")
        await asyncio.sleep(0.1)

    # Simulate an audio delta event from OpenAI (24kHz PCM16)
    num_samples_24k = 480  # 20ms at 24kHz
    audio_24k = np.ones(num_samples_24k, dtype=np.int16) * 500
    delta_b64 = base64.b64encode(audio_24k.tobytes()).decode()

    await p._on_audio_delta({"delta": delta_b64})

    # In autonomous mode, should inject immediately
    bt.send_command.assert_called_once()
    call_args = bt.send_command.call_args
    assert call_args[0][0] == "inject_audio"
    payload = call_args[0][1]
    assert payload["sample_rate"] == 8000

    # Verify the injected audio is resampled to 8kHz
    injected_bytes = base64.b64decode(payload["data"])
    injected = np.frombuffer(injected_bytes, dtype=np.int16)
    expected_samples_8k = int(num_samples_24k * 8000 / 24000)
    assert len(injected) == expected_samples_8k

    p.end_call()


@pytest.mark.asyncio
async def test_transcript_events_broadcast(pipeline):
    """UT-PY-001.10-06: Transcript events broadcast to frontend."""
    p, mock_ws, bt, ws = pipeline

    with patch("osm_core.audio.realtime.websockets.connect", new_callable=AsyncMock, return_value=mock_ws):
        p.start_call("+12345")
        await asyncio.sleep(0.1)

    # User transcript
    await p._on_input_transcription_completed({"transcript": "Hello there"})
    ws.broadcast_sync.assert_any_call("transcript", {"text": "Hello there", "sender": "user"})

    # AI response transcript delta
    await p._on_audio_transcript_delta({"delta": "Hi!"})
    ws.broadcast_sync.assert_any_call("transcript", {"text": "Hi!", "sender": "assistant", "delta": True})

    p.end_call()


@pytest.mark.asyncio
async def test_hitl_buffers_until_approval(pipeline):
    """UT-PY-001.10-07: HITL mode buffers audio until approve_response."""
    p, mock_ws, bt, ws = pipeline
    p.mode = "hitl"

    with patch("osm_core.audio.realtime.websockets.connect", new_callable=AsyncMock, return_value=mock_ws):
        p.start_call("+12345")
        await asyncio.sleep(0.1)

    # Send audio deltas — should NOT inject in HITL mode
    audio_24k = np.ones(480, dtype=np.int16) * 500
    delta_b64 = base64.b64encode(audio_24k.tobytes()).decode()

    await p._on_audio_delta({"delta": delta_b64})
    await p._on_audio_delta({"delta": delta_b64})

    # bt_bridge should NOT have been called yet
    bt.send_command.assert_not_called()
    assert len(p._pending_audio_chunks) == 2

    # Simulate response.done which triggers approval wait
    p._pending_transcript = "Test response"
    # Run response_done in background (it waits for approval)
    done_task = asyncio.create_task(p._on_response_done({}))
    await asyncio.sleep(0.05)

    # Should have broadcast llm_response for approval
    ws.broadcast_sync.assert_any_call("llm_response", {"text": "Test response", "approved": False})

    # Approve
    await p.approve_response()
    await asyncio.sleep(0.1)

    # Now audio should have been flushed
    assert bt.send_command.call_count == 2
    assert p.state == PipelineState.LISTENING

    if not done_task.done():
        done_task.cancel()

    p.end_call()


@pytest.mark.asyncio
async def test_end_call_during_response(pipeline):
    """UT-PY-001.10-08: end_call during active response stops injection."""
    p, mock_ws, bt, ws = pipeline

    with patch("osm_core.audio.realtime.websockets.connect", new_callable=AsyncMock, return_value=mock_ws):
        p.start_call("+12345")
        await asyncio.sleep(0.1)

    # Inject some audio
    audio_24k = np.ones(480, dtype=np.int16) * 500
    delta_b64 = base64.b64encode(audio_24k.tobytes()).decode()
    await p._on_audio_delta({"delta": delta_b64})

    assert bt.send_command.call_count == 1

    # End call
    p.end_call()
    assert p.state == PipelineState.IDLE

    # Further audio should not be injected
    bt.send_command.reset_mock()
    await p._on_audio_delta({"delta": delta_b64})
    bt.send_command.assert_not_called()


@pytest.mark.asyncio
async def test_error_event_handling(pipeline):
    """UT-PY-001.10-09: Error events are handled without crashing."""
    p, mock_ws, bt, ws = pipeline

    with patch("osm_core.audio.realtime.websockets.connect", new_callable=AsyncMock, return_value=mock_ws):
        p.start_call("+12345")
        await asyncio.sleep(0.1)

    # Should not raise
    await p._on_error({
        "error": {"type": "invalid_request_error", "message": "Bad audio format"}
    })

    # Pipeline should still be functional
    assert p.state == PipelineState.LISTENING

    p.end_call()


@pytest.mark.asyncio
async def test_feed_audio_ignored_when_idle(pipeline):
    """UT-PY-001.10-10: feed_audio is a no-op when pipeline is IDLE."""
    p, mock_ws, bt, ws = pipeline

    # Pipeline starts IDLE
    assert p.state == PipelineState.IDLE

    audio_8k = np.zeros(160, dtype=np.int16)
    await p.feed_audio(audio_8k.tobytes())

    # No messages sent (no WebSocket connection either)
    assert len(mock_ws.sent_messages) == 0
