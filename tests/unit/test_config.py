# tests/unit/test_config.py
from atlas.config import load_config


def test_load_default_config():
    config = load_config()
    assert config.daemon.socket_path.endswith("atlas.sock")
    assert config.daemon.max_concurrent_tasks == 1
    assert config.observation.filesystem_debounce_seconds == 5.0
    assert config.skills.forge_enabled is True
    assert config.reactive.enabled is False


def test_load_config_from_file(tmp_path):
    config_file = tmp_path / "custom.yaml"
    config_file.write_text("""
daemon:
  max_concurrent_tasks: 4
reactive:
  enabled: true
""")
    config = load_config(str(config_file))
    assert config.daemon.max_concurrent_tasks == 4
    assert config.reactive.enabled is True


def test_mcp_config_defaults():
    from atlas.config import MCPConfig
    cfg = MCPConfig()
    assert cfg.servers == []
    assert cfg.enabled is True


def test_webhook_event_type():
    from atlas.contracts.types import EventType
    assert EventType.WEBHOOK == "webhook"
