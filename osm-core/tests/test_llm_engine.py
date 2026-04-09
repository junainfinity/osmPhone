"""
test_llm_engine.py - Tests for LLM Engine (PY-001.4)
"""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from osm_core.config import Config, LLMConfig
from osm_core.llm.engine import create_engine, OpenAIProvider, LLMError

@pytest.fixture
def config():
    c = Config()
    c.llm = LLMConfig(provider="openai", api_key="test-key")
    return c

@pytest.mark.asyncio
async def test_generate(config):
    # UT-PY-001.4-01: OpenAI provider generate
    engine = create_engine("openai", config)
    
    mock_response = MagicMock()
    mock_response.choices = [MagicMock(message=MagicMock(content="Hello mocked response"))]
    
    with patch.object(engine.client.chat.completions, 'create', new_callable=AsyncMock) as mock_create:
        mock_create.return_value = mock_response
        result = await engine.generate([{"role": "user", "content": "Hi"}], system_prompt="Sys")
        assert result == "Hello mocked response"
        mock_create.assert_called_once()
        _, kwargs = mock_create.call_args
        assert kwargs['messages'][0]['content'] == "Sys"

@pytest.mark.asyncio
async def test_stream(config):
    # UT-PY-001.4-02: OpenAI provider stream
    engine = create_engine("openai", config)
    
    async def mock_stream():
        for token in ["Hello", " mocked", " stream"]:
            chunk = MagicMock()
            chunk.choices = [MagicMock(delta=MagicMock(content=token))]
            yield chunk

    async def mock_create(*args, **kwargs):
        # We need an awaitable (via async def) that returns the async generator
        return mock_stream()
            
    with patch.object(engine.client.chat.completions, 'create', side_effect=mock_create):
        tokens = [t async for t in engine.stream([{"role": "user", "content": "Hi"}])]
        assert "".join(tokens) == "Hello mocked stream"

def test_osmapi_base_url():
    # UT-PY-001.4-03: osmAPI uses custom base_url
    c = Config()
    c.llm = LLMConfig(provider="osmapi", base_url="http://custom.local/v1")
    engine = create_engine("osmapi", c)
    assert str(engine.client.base_url) == "http://custom.local/v1/"

def test_provider_factory(config):
    # UT-PY-001.4-04: Provider factory
    engine = create_engine("openai", config)
    assert isinstance(engine, OpenAIProvider)

def test_invalid_provider(config):
    # UT-PY-001.4-05: Invalid provider -> ValueError
    with pytest.raises(ValueError):
        create_engine("invalid", config)

@pytest.mark.asyncio
async def test_api_error_handling(config):
    # UT-PY-001.4-06: API error handling
    engine = create_engine("openai", config)
    
    with patch.object(engine.client.chat.completions, 'create', new_callable=AsyncMock) as mock_create:
        mock_create.side_effect = Exception("500 Server Error")
        with pytest.raises(LLMError) as exc:
            await engine.generate([{"role": "user", "content": "crash"}])
        assert "500 Server Error" in str(exc.value)
