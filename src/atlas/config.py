"""Structured configuration loading with YAML defaults and user overrides."""
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class DaemonConfig:
    socket_path: str = "~/.atlas/atlas.sock"
    pid_file: str = "~/.atlas/daemon.pid"
    max_concurrent_tasks: int = 1


@dataclass
class ControlConfig:
    autonomy_level: str = "act_within_bounds"
    allowed_read_paths: list[str] = field(default_factory=lambda: ["."])
    allowed_write_paths: list[str] = field(default_factory=lambda: ["."])
    blocked_paths: list[str] = field(default_factory=lambda: ["~/.ssh", "~/.gnupg"])


@dataclass
class TrustConfig:
    escalation_threshold: int = 10  # consecutive successes to suggest escalation
    demotion_failure_count: int = 3  # failures in window to auto-demote
    demotion_window_size: int = 10  # rolling window for failure rate
    enabled: bool = True


@dataclass
class MemoryConfig:
    working_memory_max_keys: int = 100
    episode_retention_days: int = 90
    context_default_token_budget: int = 4000
    pattern_extraction_interval_minutes: int = 30


@dataclass
class SkillsConfig:
    seed_skills: list[str] = field(default_factory=lambda: ["file.read", "file.write", "file.search", "shell.execute"])
    forge_enabled: bool = True
    forge_max_retries: int = 1
    custom_skills_dir: str = "~/.atlas/skills"


@dataclass
class MCPConfig:
    enabled: bool = True
    servers: list[dict] = field(default_factory=list)


@dataclass
class EnvironmentConfig:
    command_timeout_seconds: int = 30


@dataclass
class ObservationConfig:
    filesystem_debounce_seconds: float = 5.0
    watches: list[str] = field(default_factory=list)


@dataclass
class ReactiveConfig:
    enabled: bool = False
    rules: list[dict] = field(default_factory=list)
    cooldown_default_seconds: int = 60


@dataclass
class WebhookConfig:
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 8484
    webhook_path_prefix: str = "/webhooks"
    dashboard_enabled: bool = False
    secrets: dict[str, str] = field(default_factory=dict)


@dataclass
class GitHubConfig:
    token: str = ""
    owner: str = ""
    repo: str = ""


@dataclass
class AtlasConfig:
    data_dir: str = "~/.atlas"
    log_level: str = "INFO"
    daemon: DaemonConfig = field(default_factory=DaemonConfig)
    control: ControlConfig = field(default_factory=ControlConfig)
    trust: TrustConfig = field(default_factory=TrustConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    skills: SkillsConfig = field(default_factory=SkillsConfig)
    environment: EnvironmentConfig = field(default_factory=EnvironmentConfig)
    observation: ObservationConfig = field(default_factory=ObservationConfig)
    reactive: ReactiveConfig = field(default_factory=ReactiveConfig)
    mcp: MCPConfig = field(default_factory=MCPConfig)
    webhook: WebhookConfig = field(default_factory=WebhookConfig)
    github: GitHubConfig = field(default_factory=GitHubConfig)


_SECTION_MAP = {
    "daemon": DaemonConfig,
    "control": ControlConfig,
    "trust": TrustConfig,
    "memory": MemoryConfig,
    "skills": SkillsConfig,
    "environment": EnvironmentConfig,
    "observation": ObservationConfig,
    "reactive": ReactiveConfig,
    "mcp": MCPConfig,
    "webhook": WebhookConfig,
    "github": GitHubConfig,
}


def _merge_into_dataclass(dc_class, data: dict):
    """Create a dataclass instance from a dict, ignoring unknown keys."""
    valid_fields = {f.name for f in dc_class.__dataclass_fields__.values()}
    filtered = {k: v for k, v in data.items() if k in valid_fields}
    return dc_class(**filtered)


def _find_default_config() -> Path:
    """Find the default config file shipped with the package."""
    # Look relative to this file's location
    pkg_dir = Path(__file__).parent
    candidates = [
        pkg_dir.parent.parent / "config" / "default.yaml",  # src layout
        pkg_dir.parent / "config" / "default.yaml",
    ]
    for p in candidates:
        if p.exists():
            return p
    return candidates[0]  # return first candidate path even if missing


def load_config(override_path: str | None = None) -> AtlasConfig:
    """Load config from default.yaml, optionally merged with an override file."""
    # Load defaults
    default_path = _find_default_config()
    raw: dict = {}
    if default_path.exists():
        raw = yaml.safe_load(default_path.read_text()) or {}

    # Load overrides
    if override_path:
        override_data = yaml.safe_load(Path(override_path).read_text()) or {}
        _deep_merge(raw, override_data)

    # Build config
    atlas_section = raw.get("atlas", {})
    config = AtlasConfig(
        data_dir=atlas_section.get("data_dir", "~/.atlas"),
        log_level=atlas_section.get("log_level", "INFO"),
    )

    for section_name, dc_class in _SECTION_MAP.items():
        section_data = raw.get(section_name, {})
        if section_data:
            setattr(config, section_name, _merge_into_dataclass(dc_class, section_data))

    return config


def _deep_merge(base: dict, override: dict) -> None:
    """Recursively merge override into base."""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
