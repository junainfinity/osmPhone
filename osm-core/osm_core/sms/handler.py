"""
handler.py - SMS Handlers Module

This module implements PY-001.11 from the osmPhone architecture.
It manages incoming SMS events from the Bluetooth bridge, checks 
prior conversation history, and invokes the LLM for replies.
"""

from typing import Dict, Any

class SMSHandler:
    def __init__(self, config, bridge, ws_server, store, llm_engine):
        self.config = config
        self.bridge = bridge
        self.ws_server = ws_server
        self.store = store
        self.llm_engine = llm_engine
        
    async def handle_sms_event(self, event: Dict[str, Any]):
        """Callback for bridge sms_received event."""
        if event.get("type") != "sms_received":
            return
            
        payload = event.get("payload", {})
        contact = payload.get("from")
        body = payload.get("body")
        
        if not contact or not body:
            return
            
        # 1. Store incoming message
        self.store.add_message(contact, "incoming", body)
        
        # 2. Get history to build context
        history = self.store.get_history(contact, limit=10)
        messages = []
        for msg in history:
            role = "assistant" if msg["direction"] == "outgoing" else "user"
            messages.append({"role": role, "content": msg["body"]})
            
        # 3. Generate LLM response
        sys_prompt = self.config.llm.system_prompt if self.config.llm else None
        llm_response = await self.self_llm_generate(messages, sys_prompt)
        
        # 4. Handle based on mode
        mode = self.config.voice_mode.default if self.config.voice_mode else "hitl"
        
        if mode == "autonomous":
            self.store.add_message(contact, "outgoing", llm_response)
            if self.bridge:
                self.bridge.send_command("send_sms", {
                    "to": contact,
                    "body": llm_response
                })
        else:
            # hitl mode
            if self.ws_server:
                self.ws_server.broadcast({
                    "type": "llm_sms_draft",
                    "contact": contact,
                    "draft": llm_response
                })
                
    async def self_llm_generate(self, messages, sys_prompt):
        return await self.llm_engine.generate(messages, sys_prompt)
