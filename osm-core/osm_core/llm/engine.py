"""
engine.py - LLM Engine Module

This module implements PY-001.4 from the osmPhone architecture.
It serves as an abstraction layer for communicating with Large Language Models.
It supports both standard text completions ('generate') and token streams ('stream').
Currently, it interfaces with OpenAI implementations, which seamlessly supports
the osmAPI mode as long as a custom base_url is supplied.
"""

from typing import List, Dict, AsyncIterator, Optional
import openai

class LLMError(Exception):
    """Custom exception raised when the LLM API encounters an error."""
    pass

class LLMEngine:
    """Base interface for LLM engines."""
    async def generate(self, messages: List[Dict[str, str]], system_prompt: Optional[str] = None) -> str:
        """Generate a full string response given a context window."""
        raise NotImplementedError
        
    async def stream(self, messages: List[Dict[str, str]], system_prompt: Optional[str] = None) -> AsyncIterator[str]:
        """Stream the generated tokens incrementally."""
        raise NotImplementedError

class OpenAIProvider(LLMEngine):
    """Engine mapping to openai API format. Covers OpenAI, osmAPI, and Local OpenAI-compatible hubs."""
    
    def __init__(self, llm_config):
        self.config = llm_config
        kwargs = {}
        if self.config.base_url:
            kwargs["base_url"] = self.config.base_url
            
        kwargs["api_key"] = self.config.api_key or "dummy_key_to_bypass_check"

        self.client = openai.AsyncOpenAI(**kwargs)
        
    def _prepare_messages(self, messages: List[Dict[str, str]], system_prompt: Optional[str]) -> List[Dict[str, str]]:
        msgs = []
        if system_prompt:
            msgs.append({"role": "system", "content": system_prompt})
        msgs.extend(messages)
        return msgs

    async def generate(self, messages: List[Dict[str, str]], system_prompt: Optional[str] = None) -> str:
        try:
            response = await self.client.chat.completions.create(
                model=self.config.model,
                messages=self._prepare_messages(messages, system_prompt),
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature,
            )
            return response.choices[0].message.content
        except Exception as e:
            raise LLMError(f"API Error generating response: {e}") from e

    async def stream(self, messages: List[Dict[str, str]], system_prompt: Optional[str] = None) -> AsyncIterator[str]:
        try:
            stream = await self.client.chat.completions.create(
                model=self.config.model,
                messages=self._prepare_messages(messages, system_prompt),
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature,
                stream=True,
            )
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception as e:
            raise LLMError(f"API Error streaming response: {e}") from e

def create_engine(provider: str, config) -> LLMEngine:
    """Factory method to instantiate the correct LLM Engine provider."""
    if provider in ("openai", "osmapi", "local"):
        return OpenAIProvider(config.llm)
    raise ValueError(f"Invalid LLM provider: {provider}")
