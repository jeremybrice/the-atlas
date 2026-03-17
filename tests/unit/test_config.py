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


def test_webhook_config_defaults():
    from atlas.config import WebhookConfig
    cfg = WebhookConfig()
    assert cfg.enabled is False
    assert cfg.host == "127.0.0.1"
    assert cfg.port == 8484
    assert cfg.webhook_path_prefix == "/webhooks"
    assert cfg.dashboard_enabled is False


def test_vector_search_config_defaults():
    from atlas.config import VectorSearchConfig
    cfg = VectorSearchConfig()
    assert cfg.enabled is False
    assert cfg.model == "voyage-3-lite"
    assert cfg.semantic_weight == 0.6
    assert cfg.keyword_weight == 0.4
    assert cfg.search_limit == 50


def test_vector_search_nested_in_memory_config():
    from atlas.config import MemoryConfig, VectorSearchConfig
    cfg = MemoryConfig()
    assert isinstance(cfg.vector_search, VectorSearchConfig)
    assert cfg.vector_search.enabled is False


def test_load_config_with_vector_search_override(tmp_path):
    config_file = tmp_path / "custom.yaml"
    config_file.write_text("""
memory:
  vector_search:
    enabled: true
    model: "voyage-3-lite"
    semantic_weight: 0.7
""")
    config = load_config(str(config_file))
    assert config.memory.vector_search.enabled is True
    assert config.memory.vector_search.semantic_weight == 0.7
    assert config.memory.vector_search.keyword_weight == 0.4  # default preserved
