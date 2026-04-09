"""Tests for SMS Handler (PY-001.11).

Tests use mocked dependencies (bridge, ws_server, store, llm_engine).
"""
import pytest
from unittest.mock import MagicMock, AsyncMock
from osm_core.config import Config, VoiceModeConfig, LLMConfig
from osm_core.sms.handler import SMSHandler


class MockStore:
    """In-memory store mock matching ConversationStore interface."""
    def __init__(self):
        self.history = []

    def add_message(self, contact, direction, body):
        self.history.append({"contact": contact, "direction": direction, "body": body})

    def get_history(self, contact, limit):
        return [m for m in self.history if m["contact"] == contact][-limit:]


@pytest.fixture
def deps():
    config = Config(
        voice_mode=VoiceModeConfig(default="hitl"),
        llm=LLMConfig(system_prompt="test system")
    )
    bridge = AsyncMock()
    ws_server = AsyncMock()
    store = MockStore()
    llm_engine = AsyncMock()
    llm_engine.generate.return_value = "AI reply"
    return config, bridge, ws_server, store, llm_engine


@pytest.mark.asyncio
async def test_incoming_sms_triggers_llm(deps):
    """UT-PY-001.11-01: Incoming SMS triggers LLM."""
    config, bridge, ws_server, store, llm = deps
    handler = SMSHandler(config, bridge, ws_server, store, llm)

    # Handler signature: (event_id, payload)
    await handler.handle_sms_event("evt-1", {"from": "+1", "body": "Hello!"})

    llm.generate.assert_called_once()
    args, kwargs = llm.generate.call_args
    assert len(args[0]) == 1
    assert args[0][0]["content"] == "Hello!"


@pytest.mark.asyncio
async def test_auto_reply_autonomous(deps):
    """UT-PY-001.11-02: Auto-reply in autonomous mode."""
    config, bridge, ws_server, store, llm = deps
    config.voice_mode.default = "autonomous"
    handler = SMSHandler(config, bridge, ws_server, store, llm)

    await handler.handle_sms_event("evt-2", {"from": "+2", "body": "Ping"})

    bridge.send_command.assert_called_once_with("send_sms", {"to": "+2", "body": "AI reply"})
    assert store.history[-1] == {"contact": "+2", "direction": "outgoing", "body": "AI reply"}


@pytest.mark.asyncio
async def test_draft_only_hitl(deps):
    """UT-PY-001.11-03: HITL mode sends draft to frontend, does NOT send SMS."""
    config, bridge, ws_server, store, llm = deps
    config.voice_mode.default = "hitl"
    handler = SMSHandler(config, bridge, ws_server, store, llm)

    await handler.handle_sms_event("evt-3", {"from": "+3", "body": "Test HITL"})

    bridge.send_command.assert_not_called()
    # broadcast(event_type, data) — two-arg signature
    ws_server.broadcast.assert_called_once_with("llm_sms_draft", {
        "from": "+3",
        "to": "+3",
        "body": "AI reply",
        "approved": False,
    })


@pytest.mark.asyncio
async def test_conversation_history(deps):
    """UT-PY-001.11-04: Conversation history includes prior messages."""
    config, bridge, ws_server, store, llm = deps

    store.add_message("+4", "incoming", "Msg 1")
    store.add_message("+4", "outgoing", "Reply 1")
    store.add_message("+4", "incoming", "Msg 2")

    handler = SMSHandler(config, bridge, ws_server, store, llm)
    await handler.handle_sms_event("evt-4", {"from": "+4", "body": "Msg 3"})

    args, kwargs = llm.generate.call_args
    messages = args[0]
    assert len(messages) == 4
    assert messages[0]["content"] == "Msg 1"
    assert messages[1]["content"] == "Reply 1"
    assert messages[2]["content"] == "Msg 2"
    assert messages[3]["content"] == "Msg 3"
