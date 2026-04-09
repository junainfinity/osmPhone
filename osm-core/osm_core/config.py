"""Configuration management for osmPhone — Component PY-001.1.

Loads settings from config.yaml (YAML) into typed Python dataclasses.
Environment variables override YAML values (useful for CI/secrets).

Config search order:
  1. Explicit path passed to load_config()
  2. config.yaml in project root (gitignored, has your real keys)
  3. config.example.yaml in project root (committed, has documented defaults)
  4. All-defaults Config() if no file found

osmAPI support: osmAPI is an OpenAI-compatible endpoint. Set llm.provider="osmapi"
and llm.base_url to your endpoint. The openai SDK is used with base_url override.
No separate provider code needed.

Tests: osm-core/tests/test_config.py (10/10 passing)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class BluetoothConfig:
    device_address: str = ""
    auto_connect: bool = False
    auto_answer: bool = False
    socket_path: str = "/tmp/osmphone.sock"


@dataclass
class LLMConfig:
    provider: str = "openai"  # openai | osmapi | local
    model: str = "gpt-4o-mini"
    api_key: str = ""
    base_url: str = ""
    system_prompt: str = (
        "You are a helpful phone assistant. You handle text messages and phone calls "
        "on behalf of the user. Be concise and natural in your responses."
    )
    max_tokens: int = 256
    temperature: float = 0.7


@dataclass
class STTConfig:
    provider: str = "local"  # local | openai
    model: str = "distil-large-v3"
    language: str = "en"
    api_key: str = ""  # Shared from LLM config or set separately


@dataclass
class TTSConfig:
    provider: str = "openai"  # local | openai | elevenlabs
    voice: str = "nova"
    elevenlabs_api_key: str = ""
    api_key: str = ""  # Shared from LLM config or set separately
    speed: float = 1.0


@dataclass
class VoiceModeConfig:
    default: str = "hitl"  # autonomous | hitl


@dataclass
class AudioConfig:
    sco_sample_rate: int = 8000
    vad_threshold: float = 0.5
    min_speech_duration_ms: int = 250
    silence_duration_ms: int = 700
    comfort_noise: bool = True


@dataclass
class RealtimeConfig:
    enabled: bool = False
    model: str = "gpt-4o-realtime-preview"


@dataclass
class ServerConfig:
    ws_host: str = "localhost"
    ws_port: int = 8765


@dataclass
class Config:
    bluetooth: BluetoothConfig = field(default_factory=BluetoothConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    stt: STTConfig = field(default_factory=STTConfig)
    tts: TTSConfig = field(default_factory=TTSConfig)
    voice_mode: VoiceModeConfig = field(default_factory=VoiceModeConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    realtime: RealtimeConfig = field(default_factory=RealtimeConfig)
    server: ServerConfig = field(default_factory=ServerConfig)


def load_config(path: str | Path | None = None) -> Config:
    """Load configuration from a YAML file.

    Searches in order: explicit path, config.yaml in project root, config.example.yaml.
    Environment variables override YAML values:
      - OPENAI_API_KEY -> llm.api_key
      - ELEVENLABS_API_KEY -> tts.elevenlabs_api_key
      - OSM_API_BASE_URL -> llm.base_url
    """
    if path is None:
        project_root = Path(__file__).parent.parent.parent
        for name in ("config.yaml", "config.example.yaml"):
            candidate = project_root / name
            if candidate.exists():
                path = candidate
                break

    if path is None:
        return _apply_env(Config())

    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path) as f:
        raw = yaml.safe_load(f) or {}

    config = Config(
        bluetooth=_from_dict(BluetoothConfig, raw.get("bluetooth", {})),
        llm=_from_dict(LLMConfig, raw.get("llm", {})),
        stt=_from_dict(STTConfig, raw.get("stt", {})),
        tts=_from_dict(TTSConfig, raw.get("tts", {})),
        voice_mode=_from_dict(VoiceModeConfig, raw.get("voice_mode", {})),
        audio=_from_dict(AudioConfig, raw.get("audio", {})),
        realtime=_from_dict(RealtimeConfig, raw.get("realtime", {})),
        server=_from_dict(ServerConfig, raw.get("server", {})),
    )

    return _apply_env(config)


def _from_dict(cls, data: dict):
    """Create a dataclass instance from a dict, ignoring unknown keys."""
    import dataclasses

    field_names = {f.name for f in dataclasses.fields(cls)}
    filtered = {k: v for k, v in data.items() if k in field_names}
    return cls(**filtered)


def _apply_env(config: Config) -> Config:
    """Override config values from environment variables.

    Also propagates the OpenAI API key to STT/TTS configs so they
    can use the same key without requiring separate config entries.
    """
    openai_key = os.environ.get("OPENAI_API_KEY")
    if openai_key:
        config.llm.api_key = openai_key
    eleven_key = os.environ.get("ELEVENLABS_API_KEY")
    if eleven_key:
        config.tts.elevenlabs_api_key = eleven_key
    osm_url = os.environ.get("OSM_API_BASE_URL")
    if osm_url:
        config.llm.base_url = osm_url

    # Propagate OpenAI key to STT/TTS if not set independently
    shared_key = config.llm.api_key
    if shared_key and not config.stt.api_key:
        config.stt.api_key = shared_key
    if shared_key and not config.tts.api_key:
        config.tts.api_key = shared_key

    return config
