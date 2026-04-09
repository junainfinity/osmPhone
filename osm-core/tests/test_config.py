"""Unit tests for UT-PY-001.1: Config."""

import os
import tempfile
from pathlib import Path

import pytest
import yaml

from osm_core.config import (
    Config,
    BluetoothConfig,
    LLMConfig,
    STTConfig,
    TTSConfig,
    VoiceModeConfig,
    AudioConfig,
    RealtimeConfig,
    ServerConfig,
    load_config,
)


def _write_yaml(data: dict, path: Path) -> Path:
    with open(path, "w") as f:
        yaml.dump(data, f)
    return path


class TestLoadConfig:
    """UT-PY-001.1-01 through UT-PY-001.1-05."""

    def test_load_valid_config(self, tmp_path: Path):
        """UT-PY-001.1-01: Load valid config returns Config dataclass."""
        data = {
            "bluetooth": {"device_address": "AA:BB:CC:DD:EE:FF", "auto_connect": True},
            "llm": {"provider": "openai", "model": "gpt-4o", "api_key": "sk-test"},
            "stt": {"provider": "local"},
            "tts": {"provider": "elevenlabs", "voice": "rachel"},
            "voice_mode": {"default": "autonomous"},
            "audio": {"sco_sample_rate": 16000},
            "realtime": {"enabled": True},
            "server": {"ws_port": 9000},
        }
        cfg_path = _write_yaml(data, tmp_path / "config.yaml")
        config = load_config(cfg_path)

        assert isinstance(config, Config)
        assert config.bluetooth.device_address == "AA:BB:CC:DD:EE:FF"
        assert config.bluetooth.auto_connect is True
        assert config.llm.provider == "openai"
        assert config.llm.model == "gpt-4o"
        assert config.llm.api_key == "sk-test"
        assert config.stt.provider == "local"
        assert config.tts.provider == "elevenlabs"
        assert config.tts.voice == "rachel"
        assert config.voice_mode.default == "autonomous"
        assert config.audio.sco_sample_rate == 16000
        assert config.realtime.enabled is True
        assert config.server.ws_port == 9000

    def test_missing_file_raises(self):
        """UT-PY-001.1-02: Missing file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            load_config("/nonexistent/path/config.yaml")

    def test_defaults_applied(self, tmp_path: Path):
        """UT-PY-001.1-04: Minimal YAML gets defaults filled."""
        data = {"llm": {"provider": "openai"}}
        cfg_path = _write_yaml(data, tmp_path / "config.yaml")
        config = load_config(cfg_path)

        assert config.voice_mode.default == "hitl"
        assert config.server.ws_port == 8765
        assert config.audio.sco_sample_rate == 8000
        assert config.bluetooth.socket_path == "/tmp/osmphone.sock"
        assert config.llm.temperature == 0.7
        assert config.realtime.enabled is False

    def test_osmapi_base_url(self, tmp_path: Path):
        """UT-PY-001.1-05: osmAPI config uses base_url."""
        data = {
            "llm": {
                "provider": "osmapi",
                "base_url": "https://my-osm-api.com/v1",
                "api_key": "osm-key",
            }
        }
        cfg_path = _write_yaml(data, tmp_path / "config.yaml")
        config = load_config(cfg_path)

        assert config.llm.provider == "osmapi"
        assert config.llm.base_url == "https://my-osm-api.com/v1"
        assert config.llm.api_key == "osm-key"

    def test_env_override(self, tmp_path: Path, monkeypatch):
        """Environment variables override YAML values."""
        data = {"llm": {"api_key": "yaml-key"}}
        cfg_path = _write_yaml(data, tmp_path / "config.yaml")

        monkeypatch.setenv("OPENAI_API_KEY", "env-key")
        monkeypatch.setenv("ELEVENLABS_API_KEY", "env-eleven")
        monkeypatch.setenv("OSM_API_BASE_URL", "https://env-osm.com/v1")

        config = load_config(cfg_path)

        assert config.llm.api_key == "env-key"
        assert config.tts.elevenlabs_api_key == "env-eleven"
        assert config.llm.base_url == "https://env-osm.com/v1"

    def test_unknown_keys_ignored(self, tmp_path: Path):
        """Unknown keys in YAML don't cause errors."""
        data = {
            "llm": {"provider": "openai", "unknown_key": "value"},
            "unknown_section": {"foo": "bar"},
        }
        cfg_path = _write_yaml(data, tmp_path / "config.yaml")
        config = load_config(cfg_path)
        assert config.llm.provider == "openai"

    def test_empty_yaml(self, tmp_path: Path):
        """Empty YAML file returns all defaults."""
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text("")
        config = load_config(cfg_path)
        assert isinstance(config, Config)
        assert config.llm.provider == "openai"


class TestConfigSchema:
    """UT-IF-001.4: Verify config.example.yaml is valid."""

    def test_example_yaml_is_valid(self):
        """UT-IF-001.4-01: config.example.yaml is valid YAML."""
        example_path = Path(__file__).parent.parent.parent / "config.example.yaml"
        if not example_path.exists():
            pytest.skip("config.example.yaml not found")
        with open(example_path) as f:
            data = yaml.safe_load(f)
        assert isinstance(data, dict)

    def test_example_has_required_sections(self):
        """UT-IF-001.4-02: All required sections present."""
        example_path = Path(__file__).parent.parent.parent / "config.example.yaml"
        if not example_path.exists():
            pytest.skip("config.example.yaml not found")
        with open(example_path) as f:
            data = yaml.safe_load(f)
        for section in ("bluetooth", "llm", "stt", "tts", "voice_mode", "audio", "server"):
            assert section in data, f"Missing section: {section}"

    def test_example_loads_as_config(self):
        """UT-IF-001.4-03: config.example.yaml loads into Config dataclass."""
        example_path = Path(__file__).parent.parent.parent / "config.example.yaml"
        if not example_path.exists():
            pytest.skip("config.example.yaml not found")
        config = load_config(example_path)
        assert isinstance(config, Config)
        assert config.voice_mode.default == "hitl"
