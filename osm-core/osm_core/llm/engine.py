"""LLM Engine — Component PY-001.4.

Abstraction layer for Large Language Model providers. Supports:

  - "openai": Standard OpenAI API (gpt-4o, gpt-4o-mini, etc.)
  - "osmapi": Any OpenAI-compatible endpoint. Same as openai but with custom base_url.
              Just set llm.base_url in config.yaml to your endpoint.
  - "local": Placeholder for mlx-lm local inference on Apple Silicon.
              Currently falls back to OpenAI client (works if you run a local
              OpenAI-compatible server like ollama, vllm, or lmstudio).

Each provider implements:
  - generate(messages, system_prompt) -> str: Full response.
  - stream(messages, system_prompt) -> AsyncIterator[str]: Token-by-token streaming.

Factory: create_engine("openai" | "osmapi" | "local", config) -> LLMEngine

FIX LOG (Claude Opus 4.6, 2026-04-09):
  - Added LocalLLMEngine stub with clear upgrade path to mlx-lm
  - osmAPI now explicitly documented as OpenAI-compatible with base_url override
  - Added retry-friendly error messages in LLMError
"""

from typing import List, Dict, AsyncIterator, Optional
import logging

import openai

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """Raised when the LLM API encounters an error."""
    pass


class LLMEngine:
    """Abstract base for LLM providers."""

    async def generate(self, messages: List[Dict[str, str]], system_prompt: Optional[str] = None) -> str:
        raise NotImplementedError

    async def stream(self, messages: List[Dict[str, str]], system_prompt: Optional[str] = None) -> AsyncIterator[str]:
        raise NotImplementedError
        yield  # make it a generator


class OpenAIProvider(LLMEngine):
    """LLM provider using OpenAI chat completions API.

    Also works for osmAPI and any OpenAI-compatible endpoint — just set base_url.
    The openai SDK handles the rest transparently.
    """

    def __init__(self, llm_config):
        self.config = llm_config
        kwargs = {}
        if self.config.base_url:
            kwargs["base_url"] = self.config.base_url
        # Use "dummy" key if none set — some local servers don't need a key
        kwargs["api_key"] = self.config.api_key or "sk-placeholder"
        self.client = openai.AsyncOpenAI(**kwargs)

    def _prepare_messages(self, messages: List[Dict[str, str]], system_prompt: Optional[str]) -> List[Dict[str, str]]:
        """Prepend system prompt to message list if provided."""
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
            raise LLMError(f"LLM API error (model={self.config.model}): {e}") from e

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
            raise LLMError(f"LLM streaming error (model={self.config.model}): {e}") from e


class LocalLLMEngine(LLMEngine):
    """Local LLM using mlx-lm on Apple Silicon.

    STUB: Currently delegates to OpenAI client (works if you have a local
    OpenAI-compatible server running). To implement native mlx-lm:
      1. pip install mlx-lm
      2. Load model: from mlx_lm import load, generate
      3. Call generate() directly — no HTTP, runs on Metal GPU
    """

    def __init__(self, llm_config):
        self.config = llm_config
        # For now, use OpenAI client pointed at localhost
        # (works with ollama, vllm, lmstudio, etc.)
        base_url = self.config.base_url or "http://localhost:11434/v1"
        api_key = self.config.api_key or "sk-placeholder"
        self.client = openai.AsyncOpenAI(base_url=base_url, api_key=api_key)
        logger.info("LocalLLMEngine using OpenAI-compatible endpoint at %s", base_url)

    def _prepare_messages(self, messages, system_prompt):
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
            raise LLMError(f"Local LLM error: {e}") from e

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
            raise LLMError(f"Local LLM streaming error: {e}") from e


def create_engine(provider: str, config) -> LLMEngine:
    """Factory: create the correct LLM engine based on config provider string.

    - "openai": Standard OpenAI API
    - "osmapi": OpenAI-compatible endpoint with custom base_url
    - "local": Local inference (currently via OpenAI-compatible local server)
    """
    if provider in ("openai", "osmapi"):
        return OpenAIProvider(config.llm)
    elif provider == "local":
        return LocalLLMEngine(config.llm)
    raise ValueError(f"Invalid LLM provider: {provider}. Expected 'openai', 'osmapi', or 'local'.")
