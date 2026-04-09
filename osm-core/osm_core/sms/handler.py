"""SMS Handler — Component PY-001.11.

Receives incoming SMS events from the Bluetooth bridge, looks up conversation
history, generates an LLM response, and either auto-sends (autonomous mode)
or drafts for user approval (HITL mode).

Integration:
  - Registered as handler for "sms_received" events on bt_bridge
  - Uses ConversationStore for message history
  - Uses LLM engine for response generation
  - Sends "send_sms" commands back through bt_bridge
  - Broadcasts "llm_sms_draft" to frontend via ws_server (HITL mode)

FIX LOG (Claude Opus 4.6, 2026-04-09):
  - Fixed ws_server.broadcast() call: was passing single dict, now uses
    (event_type, data) two-arg signature matching WSServer.broadcast()
  - Fixed bridge.send_command(): was missing await (it's async)
  - Fixed typo: self.self_llm_generate -> self.llm_engine.generate
  - Added error handling: LLM/bridge failures no longer crash the handler
"""

import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


class SMSHandler:
    """Handles incoming SMS events and orchestrates LLM-powered replies."""

    def __init__(self, config, bridge, ws_server, store, llm_engine):
        self.config = config
        self.bridge = bridge
        self.ws_server = ws_server
        self.store = store
        self.llm_engine = llm_engine

    async def handle_sms_event(self, event_id: str, payload: Dict[str, Any]):
        """Callback for bt_bridge 'sms_received' events.

        Registered via: bridge.on("sms_received", handler.handle_sms_event)
        Args match bt_bridge handler signature: (event_id: str, payload: dict)
        """
        contact = payload.get("from")
        body = payload.get("body")

        if not contact or not body:
            logger.warning("SMS event missing 'from' or 'body': %s", payload)
            return

        try:
            # 1. Store incoming message
            self.store.add_message(contact, "incoming", body)

            # 2. Build conversation context from history
            history = self.store.get_history(contact, limit=10)
            messages = []
            for msg in history:
                role = "assistant" if msg["direction"] == "outgoing" else "user"
                messages.append({"role": role, "content": msg["body"]})

            # 3. Generate LLM response
            sys_prompt = getattr(self.config.llm, 'system_prompt', None)
            llm_response = await self.llm_engine.generate(messages, sys_prompt)

            # 4. Handle based on voice mode
            mode = getattr(self.config.voice_mode, 'default', 'hitl')

            if mode == "autonomous":
                # Auto-send reply
                self.store.add_message(contact, "outgoing", llm_response)
                await self.bridge.send_command("send_sms", {
                    "to": contact,
                    "body": llm_response,
                })
                # Also notify frontend
                await self.ws_server.broadcast("sms_sent", {
                    "to": contact,
                    "body": llm_response,
                })
                logger.info("Auto-replied to %s", contact)
            else:
                # HITL: send draft to frontend for approval
                # Uses (event_type, data) two-arg signature
                await self.ws_server.broadcast("llm_sms_draft", {
                    "from": contact,
                    "to": contact,
                    "body": llm_response,
                    "approved": False,
                })
                logger.info("SMS draft sent to frontend for %s", contact)

        except Exception as e:
            logger.error("SMS handler error for %s: %s", contact, e, exc_info=True)
            # Don't crash — next SMS can still be processed
