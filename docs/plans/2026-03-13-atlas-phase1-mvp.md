# ATLAS Phase 1 MVP Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a working CLI tool where `atlas goal "do X"` decomposes a goal into tasks via Claude Code, executes them sequentially using seed skills, and records the episode — proving the planning-execution-reflection loop end-to-end.

**Architecture:** Bottom-up build. Shared contracts first, then each domain in dependency order (Control -> Memory -> Environment -> Skills -> Core -> CLI). Each domain implements only its Phase 1 slice from the Foundation Spec. asyncio throughout, single SQLite database, Claude Code one-shot only.

**Tech Stack:** Python 3.12+, Click (CLI), aiosqlite (async SQLite), PyYAML (config), pytest + pytest-asyncio (testing), ruff (linting)

---

## Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `src/atlas/__init__.py`
- Create: `src/atlas/__main__.py`
- Create: `config/default.yaml`
- Create: all `__init__.py` files for subpackages
- Create: `tests/conftest.py`

**Step 1: Create pyproject.toml**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "atlas"
version = "0.1.0"
description = "Autonomous Tool-Learning Agent System"
requires-python = ">=3.12"
dependencies = [
    "click>=8.1",
    "aiosqlite>=0.20",
    "pyyaml>=6.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
    "ruff>=0.8",
]

[project.scripts]
atlas = "atlas.cli:main"

[tool.hatch.build.targets.wheel]
packages = ["src/atlas"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"

[tool.ruff]
target-version = "py312"
src = ["src"]
```

**Step 2: Create .gitignore**

```gitignore
# Python
__pycache__/
*.py[cod]
*$py.class
*.egg-info/
dist/
build/
*.egg
.eggs/

# Virtual environments
.venv/
venv/
env/

# IDE
.idea/
.vscode/
*.swp
*.swo

# OS
.DS_Store
Thumbs.db

# ATLAS runtime data
.atlas/

# Testing
.pytest_cache/
.coverage
htmlcov/

# Distribution
*.tar.gz
*.whl
```

**Step 3: Create directory structure with __init__.py files**

```bash
mkdir -p src/atlas/{contracts,core,memory,skills,env,integrations,control}
mkdir -p src/atlas/integrations/connectors
mkdir -p tests/{unit,integration}
mkdir -p tests/unit/{contracts,core,memory,skills,env,control}
mkdir -p config
```

Every `__init__.py` is empty. Create them for:
- `src/atlas/__init__.py`
- `src/atlas/contracts/__init__.py`
- `src/atlas/core/__init__.py`
- `src/atlas/memory/__init__.py`
- `src/atlas/skills/__init__.py`
- `src/atlas/env/__init__.py`
- `src/atlas/integrations/__init__.py`
- `src/atlas/integrations/connectors/__init__.py`
- `src/atlas/control/__init__.py`

**Step 4: Create `src/atlas/__main__.py`**

```python
from atlas.cli import main

main()
```

**Step 5: Create `config/default.yaml`**

```yaml
atlas:
  data_dir: "~/.atlas"
  log_level: "INFO"

control:
  autonomy_level: "act_within_bounds"
  allowed_read_paths:
    - "."
  allowed_write_paths:
    - "."
  blocked_paths:
    - "~/.ssh"
    - "~/.gnupg"

memory:
  working_memory_max_keys: 100
  episode_retention_days: 90
  context_default_token_budget: 4000

skills:
  seed_skills:
    - "file.read"
    - "file.write"
    - "file.search"
    - "shell.execute"

environment:
  command_timeout_seconds: 30
  claude_code_timeout_seconds: 120
```

**Step 6: Create `tests/conftest.py`**

```python
import asyncio
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio


@pytest.fixture
def tmp_data_dir(tmp_path: Path) -> Path:
    """Provides a temporary ATLAS data directory."""
    data_dir = tmp_path / ".atlas"
    data_dir.mkdir()
    (data_dir / "config").mkdir()
    (data_dir / "data").mkdir()
    (data_dir / "logs").mkdir()
    (data_dir / "skills").mkdir()
    return data_dir


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    """Provides a temporary workspace directory with sample files."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "src").mkdir()
    (workspace / "src" / "main.py").write_text("print('hello')\n")
    return workspace
```

**Step 7: Install in dev mode and verify**

Run: `pip install -e ".[dev]"`
Expected: Success, `atlas` command available on PATH

Run: `atlas --help`
Expected: Will fail (cli.py doesn't exist yet) — that's fine, confirms entry point is wired

**Step 8: Commit**

```bash
git add pyproject.toml .gitignore src/ tests/ config/
git commit -m "feat: scaffold project structure with pyproject.toml and directory layout"
```

---

## Task 2: Contracts — Shared Types

**Files:**
- Create: `src/atlas/contracts/types.py`
- Test: `tests/unit/contracts/test_types.py`

**Step 1: Write the failing test**

```python
# tests/unit/contracts/test_types.py
from atlas.contracts.types import (
    ExecutionContext,
    PolicyDecision,
    AutonomyLevel,
    TaskStatus,
    MissionStatus,
    SkillType,
    RiskLevel,
)


def test_execution_context_creates_with_correlation_id():
    ctx = ExecutionContext(correlation_id="abc-123")
    assert ctx.correlation_id == "abc-123"
    assert ctx.mission_id is None
    assert ctx.task_id is None


def test_execution_context_creates_with_all_fields():
    ctx = ExecutionContext(
        correlation_id="abc-123",
        mission_id="mission-1",
        task_id="task-1",
    )
    assert ctx.mission_id == "mission-1"


def test_policy_decision_enum_values():
    assert PolicyDecision.ALLOW.value == "allow"
    assert PolicyDecision.DENY.value == "deny"
    assert PolicyDecision.REQUIRE_APPROVAL.value == "require_approval"


def test_autonomy_level_ordering():
    assert AutonomyLevel.OBSERVE.value < AutonomyLevel.SUGGEST.value
    assert AutonomyLevel.SUGGEST.value < AutonomyLevel.ACT_WITHIN_BOUNDS.value


def test_task_status_terminal_states():
    terminal = {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}
    non_terminal = {TaskStatus.PENDING, TaskStatus.READY, TaskStatus.EXECUTING}
    for s in terminal:
        assert s.is_terminal()
    for s in non_terminal:
        assert not s.is_terminal()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/contracts/test_types.py -v`
Expected: FAIL — module not found

**Step 3: Write implementation**

```python
# src/atlas/contracts/types.py
"""Shared data models, enums, and value types used across all ATLAS domains."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


# --- Identifiers ---

def new_id() -> str:
    """Generate a new UUID string."""
    return str(uuid.uuid4())


# --- Execution Context (observability) ---

@dataclass(frozen=True)
class ExecutionContext:
    """Propagated through all cross-domain calls for tracing."""
    correlation_id: str
    mission_id: str | None = None
    task_id: str | None = None

    @classmethod
    def new(cls, mission_id: str | None = None, task_id: str | None = None) -> ExecutionContext:
        return cls(correlation_id=new_id(), mission_id=mission_id, task_id=task_id)


# --- Enums ---

class PolicyDecision(Enum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"
    ALLOW_WITH_LOGGING = "allow_with_logging"


class AutonomyLevel(Enum):
    OBSERVE = 0
    SUGGEST = 1
    ACT_WITHIN_BOUNDS = 2


class TaskStatus(Enum):
    PENDING = "pending"
    READY = "ready"
    EXECUTING = "executing"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    def is_terminal(self) -> bool:
        return self in {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}


class MissionStatus(Enum):
    PLANNING = "planning"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SkillType(Enum):
    PYTHON_FUNCTION = "python_function"
    CLI_COMMAND = "cli_command"
    CLAUDE_CODE_PROMPT = "claude_code_prompt"


class RiskLevel(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class SkillMaturity(Enum):
    DRAFT = "draft"
    TESTING = "testing"
    STABLE = "stable"
    DEPRECATED = "deprecated"


class EpisodeType(Enum):
    TASK_EXECUTION = "task_execution"
    OBSERVATION = "observation"
    REFLECTION = "reflection"
    USER_INTERACTION = "user_interaction"


# --- Shared Data Models ---

@dataclass
class ProposedAction:
    """Submitted to Control Plane for permission check."""
    action_type: str  # e.g., "filesystem_write", "shell_execute"
    domain: str       # e.g., "skills", "core"
    description: str
    params: dict[str, Any] = field(default_factory=dict)
    risk_level: RiskLevel = RiskLevel.LOW
    skill_id: str | None = None


@dataclass
class AuditEntry:
    """Written to the audit log for every significant action."""
    entry_id: str = field(default_factory=new_id)
    timestamp: datetime = field(default_factory=datetime.now)
    correlation_id: str | None = None
    actor: str = ""           # domain/component
    action_type: str = ""
    action_details: dict[str, Any] = field(default_factory=dict)
    policy_decision: PolicyDecision | None = None
    outcome: str = ""         # "success", "failure", "denied", "timeout"
    mission_id: str | None = None
    task_id: str | None = None


@dataclass
class Episode:
    """A record of something the agent did or observed."""
    episode_id: str = field(default_factory=new_id)
    timestamp: datetime = field(default_factory=datetime.now)
    episode_type: EpisodeType = EpisodeType.TASK_EXECUTION
    trigger: str = ""
    plan: str = ""
    actions: list[dict[str, Any]] = field(default_factory=list)
    outcome: str = ""
    lessons: list[str] = field(default_factory=list)
    mission_id: str | None = None
    task_id: str | None = None
    tags: list[str] = field(default_factory=list)
    correlation_id: str | None = None


@dataclass
class ContextQuery:
    """Request for assembled context from the Memory System."""
    purpose: str              # "planning", "execution", "reflection"
    task_description: str
    mission_context: str | None = None
    token_budget: int = 4000
    recency_weight: float = 0.7


@dataclass
class ContextBundle:
    """Assembled context ready for injection into a Claude Code prompt."""
    contents: list[dict[str, Any]] = field(default_factory=list)
    total_tokens: int = 0
    budget_tokens: int = 4000


@dataclass
class SkillDescriptor:
    """Lightweight skill view for search results."""
    skill_id: str
    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    risk_level: RiskLevel = RiskLevel.LOW
    tags: list[str] = field(default_factory=list)


@dataclass
class SkillResult:
    """Result of a skill invocation."""
    invocation_id: str = field(default_factory=new_id)
    skill_id: str = ""
    status: str = "success"   # "success", "failure", "timeout", "cancelled"
    output: Any = None
    error: str | None = None
    execution_time_ms: int = 0


@dataclass
class EnvironmentAction:
    """An action to be executed in the environment."""
    action_id: str = field(default_factory=new_id)
    action_type: str = ""     # "filesystem_read", "filesystem_write", "process_execute", etc.
    provider: str = ""        # "filesystem", "process", "claude_code"
    params: dict[str, Any] = field(default_factory=dict)
    timeout: int = 30


@dataclass
class ActionResult:
    """Result of an environment action."""
    action_id: str = ""
    status: str = "success"   # "success", "failure", "timeout", "denied"
    output: Any = None
    error: str | None = None
    execution_time_ms: int = 0


@dataclass
class ClaudeResponse:
    """Response from a Claude Code CLI call."""
    content: str = ""
    parsed_output: Any = None
    tokens_used: int = 0
    execution_time_ms: int = 0


@dataclass
class ApprovalRequest:
    """Submitted to the Approval Workflow when permission check returns REQUIRE_APPROVAL."""
    request_id: str = field(default_factory=new_id)
    action: ProposedAction | None = None
    reasoning: str = ""
    expected_outcome: str = ""
    risk_assessment: str = ""


class ApprovalResult(Enum):
    APPROVED = "approved"
    DENIED = "denied"
    TIMEOUT = "timeout"
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/contracts/test_types.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/atlas/contracts/types.py tests/unit/contracts/test_types.py
git commit -m "feat: add shared types, enums, and data models in contracts"
```

---

## Task 3: Contracts — Error Hierarchy

**Files:**
- Create: `src/atlas/contracts/errors.py`
- Test: `tests/unit/contracts/test_errors.py`

**Step 1: Write the failing test**

```python
# tests/unit/contracts/test_errors.py
from atlas.contracts.errors import (
    AtlasError,
    RetriableError,
    FatalError,
    PermissionDeniedError,
    ClaudeCodeError,
    SkillNotFoundError,
    SkillInvocationError,
)


def test_atlas_error_carries_correlation_id():
    err = AtlasError("something broke", correlation_id="abc-123")
    assert err.correlation_id == "abc-123"
    assert str(err) == "something broke"


def test_retriable_error_has_max_retries():
    err = RetriableError("transient failure", max_retries=5)
    assert err.max_retries == 5
    assert isinstance(err, AtlasError)


def test_fatal_error_is_not_retriable():
    err = FatalError("permanent failure")
    assert isinstance(err, AtlasError)
    assert not isinstance(err, RetriableError)


def test_permission_denied_is_fatal():
    err = PermissionDeniedError("not allowed")
    assert isinstance(err, FatalError)


def test_claude_code_error_is_retriable():
    err = ClaudeCodeError("rate limited", max_retries=2)
    assert isinstance(err, RetriableError)
    assert err.max_retries == 2


def test_cause_chaining():
    root = ClaudeCodeError("CLI timeout")
    wrapped = SkillInvocationError("skill failed", cause=root)
    assert wrapped.cause is root
    assert wrapped.correlation_id is None


def test_skill_not_found_is_fatal():
    err = SkillNotFoundError("no such skill: foo.bar")
    assert isinstance(err, FatalError)


def test_error_hierarchy_isinstance_checks():
    """Verify callers can branch on RetriableError vs FatalError."""
    retriable = SkillInvocationError("oops")
    fatal = SkillNotFoundError("gone")

    assert isinstance(retriable, RetriableError)
    assert not isinstance(retriable, FatalError)
    assert isinstance(fatal, FatalError)
    assert not isinstance(fatal, RetriableError)
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/contracts/test_errors.py -v`
Expected: FAIL — module not found

**Step 3: Write implementation**

```python
# src/atlas/contracts/errors.py
"""Unified error hierarchy for ATLAS. All domain errors extend RetriableError or FatalError."""

from __future__ import annotations


class AtlasError(Exception):
    """Base for all ATLAS errors."""

    def __init__(
        self,
        message: str,
        correlation_id: str | None = None,
        cause: Exception | None = None,
    ):
        super().__init__(message)
        self.correlation_id = correlation_id
        self.cause = cause


class RetriableError(AtlasError):
    """Caller should retry with backoff."""

    def __init__(self, message: str, max_retries: int = 3, **kwargs):
        super().__init__(message, **kwargs)
        self.max_retries = max_retries


class FatalError(AtlasError):
    """Do not retry. Escalate or abort."""


# --- Control Plane ---

class PermissionDeniedError(FatalError):
    """Action was denied by the Policy Engine."""


class ApprovalTimeoutError(RetriableError):
    """Approval request timed out waiting for user response."""


# --- Environment ---

class EnvironmentActionError(RetriableError):
    """An environment action failed but may succeed on retry."""


class ClaudeCodeError(RetriableError):
    """Claude Code CLI call failed (rate limit, timeout, parse error)."""


class ClaudeCodeUnavailableError(FatalError):
    """Claude Code CLI is not reachable at all."""


# --- Skills ---

class SkillNotFoundError(FatalError):
    """Requested skill does not exist in the registry."""


class SkillInvocationError(RetriableError):
    """Skill execution failed but may succeed on retry."""


class SkillValidationError(FatalError):
    """Skill input or output failed schema validation."""


# --- Memory ---

class MemoryStoreError(RetriableError):
    """SQLite or storage operation failed transiently."""


class ContextBudgetExceededError(FatalError):
    """Cannot fit required context within token budget."""


# --- Integration ---

class ConnectorError(RetriableError):
    """External service connector failed."""


class CredentialError(FatalError):
    """Authentication failed and cannot be refreshed."""
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/contracts/test_errors.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/atlas/contracts/errors.py tests/unit/contracts/test_errors.py
git commit -m "feat: add unified error hierarchy with retriable/fatal branching"
```

---

## Task 4: Contracts — Interfaces (ABCs)

**Files:**
- Create: `src/atlas/contracts/interfaces.py`

No tests for this file — ABCs are tested through their implementations.

**Step 1: Write the interfaces**

```python
# src/atlas/contracts/interfaces.py
"""Canonical cross-domain interface definitions. Source of truth for all inter-domain contracts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from atlas.contracts.types import (
    ApprovalRequest,
    ApprovalResult,
    AuditEntry,
    ActionResult,
    AutonomyLevel,
    ClaudeResponse,
    ContextBundle,
    ContextQuery,
    Episode,
    EnvironmentAction,
    ExecutionContext,
    PolicyDecision,
    ProposedAction,
    SkillDescriptor,
    SkillResult,
)


class ControlPlaneInterface(ABC):
    """Consumed by all domains. Permission checks must be sub-millisecond."""

    @abstractmethod
    def check_permission(self, action: ProposedAction, ctx: ExecutionContext | None = None) -> PolicyDecision:
        ...

    @abstractmethod
    def get_autonomy_level(self, domain: str, skill: str | None = None) -> AutonomyLevel:
        ...

    @abstractmethod
    def log_action(self, entry: AuditEntry) -> None:
        ...

    @abstractmethod
    async def request_approval(self, request: ApprovalRequest, ctx: ExecutionContext | None = None) -> ApprovalResult:
        ...


class MemoryInterface(ABC):
    """Consumed by Core, Skills, Control."""

    @abstractmethod
    def retrieve_context(self, query: ContextQuery) -> ContextBundle:
        ...

    @abstractmethod
    def record_episode(self, episode: Episode) -> str:
        ...

    @abstractmethod
    def set_working(self, key: str, value: Any, ttl: int | None = None) -> None:
        ...

    @abstractmethod
    def get_working(self, key: str) -> Any | None:
        ...

    @abstractmethod
    def clear_working(self) -> None:
        ...

    @abstractmethod
    def search_episodes(self, text_query: str, limit: int = 20) -> list[Episode]:
        ...


class EnvironmentInterface(ABC):
    """Consumed by Core, Skills."""

    @abstractmethod
    async def execute(self, action: EnvironmentAction, ctx: ExecutionContext | None = None) -> ActionResult:
        ...

    @abstractmethod
    def get_state(self) -> dict[str, Any]:
        ...

    @abstractmethod
    async def claude_oneshot(self, prompt: str, system_prompt: str | None = None,
                              ctx: ExecutionContext | None = None) -> ClaudeResponse:
        ...


class SkillEngineInterface(ABC):
    """Consumed by Core."""

    @abstractmethod
    def search(self, query: str) -> list[SkillDescriptor]:
        ...

    @abstractmethod
    def get(self, skill_id: str) -> SkillDescriptor:
        ...

    @abstractmethod
    def list_all(self) -> list[SkillDescriptor]:
        ...

    @abstractmethod
    async def invoke(self, skill_id: str, params: dict[str, Any],
                     ctx: ExecutionContext | None = None) -> SkillResult:
        ...

    @abstractmethod
    def register(self, skill_id: str, name: str, description: str,
                 handler: Any, risk_level: str = "low") -> None:
        ...
```

**Step 2: Verify it imports**

Run: `python -c "from atlas.contracts.interfaces import ControlPlaneInterface; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add src/atlas/contracts/interfaces.py
git commit -m "feat: add canonical cross-domain interface ABCs"
```

---

## Task 5: Control Plane — Policy Engine

**Files:**
- Create: `src/atlas/control/policy.py`
- Test: `tests/unit/control/test_policy.py`

**Step 1: Write the failing test**

```python
# tests/unit/control/test_policy.py
from atlas.contracts.types import (
    AutonomyLevel,
    PolicyDecision,
    ProposedAction,
    RiskLevel,
)
from atlas.control.policy import PolicyEngine


def test_observe_mode_denies_all_actions():
    engine = PolicyEngine(autonomy_level=AutonomyLevel.OBSERVE)
    action = ProposedAction(
        action_type="filesystem_read",
        domain="skills",
        description="read a file",
    )
    assert engine.evaluate(action) == PolicyDecision.DENY


def test_suggest_mode_requires_approval_for_all():
    engine = PolicyEngine(autonomy_level=AutonomyLevel.SUGGEST)
    action = ProposedAction(
        action_type="filesystem_read",
        domain="skills",
        description="read a file",
    )
    assert engine.evaluate(action) == PolicyDecision.REQUIRE_APPROVAL


def test_act_within_bounds_allows_low_risk():
    engine = PolicyEngine(autonomy_level=AutonomyLevel.ACT_WITHIN_BOUNDS)
    action = ProposedAction(
        action_type="filesystem_read",
        domain="skills",
        description="read a file",
        risk_level=RiskLevel.LOW,
    )
    assert engine.evaluate(action) == PolicyDecision.ALLOW


def test_act_within_bounds_requires_approval_for_medium_risk():
    engine = PolicyEngine(autonomy_level=AutonomyLevel.ACT_WITHIN_BOUNDS)
    action = ProposedAction(
        action_type="filesystem_write",
        domain="skills",
        description="write a file",
        risk_level=RiskLevel.MEDIUM,
    )
    assert engine.evaluate(action) == PolicyDecision.REQUIRE_APPROVAL


def test_act_within_bounds_denies_critical_risk():
    engine = PolicyEngine(autonomy_level=AutonomyLevel.ACT_WITHIN_BOUNDS)
    action = ProposedAction(
        action_type="shell_execute",
        domain="skills",
        description="run rm -rf /",
        risk_level=RiskLevel.CRITICAL,
    )
    assert engine.evaluate(action) == PolicyDecision.DENY


def test_blocked_path_is_denied():
    engine = PolicyEngine(
        autonomy_level=AutonomyLevel.ACT_WITHIN_BOUNDS,
        blocked_paths=["~/.ssh", "~/.gnupg"],
    )
    action = ProposedAction(
        action_type="filesystem_read",
        domain="skills",
        description="read ssh key",
        params={"path": "~/.ssh/id_rsa"},
        risk_level=RiskLevel.LOW,
    )
    assert engine.evaluate(action) == PolicyDecision.DENY


def test_get_autonomy_level():
    engine = PolicyEngine(autonomy_level=AutonomyLevel.SUGGEST)
    assert engine.get_autonomy_level("core") == AutonomyLevel.SUGGEST
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/control/test_policy.py -v`
Expected: FAIL — module not found

**Step 3: Write implementation**

```python
# src/atlas/control/policy.py
"""Policy Engine — evaluates proposed actions against autonomy rules and boundaries."""

from __future__ import annotations

from pathlib import Path

from atlas.contracts.types import (
    AutonomyLevel,
    PolicyDecision,
    ProposedAction,
    RiskLevel,
)


class PolicyEngine:
    """Stateless policy evaluator. Every action passes through evaluate()."""

    def __init__(
        self,
        autonomy_level: AutonomyLevel = AutonomyLevel.ACT_WITHIN_BOUNDS,
        blocked_paths: list[str] | None = None,
    ):
        self._autonomy_level = autonomy_level
        self._blocked_paths = [
            str(Path(p).expanduser()) for p in (blocked_paths or [])
        ]

    def evaluate(self, action: ProposedAction) -> PolicyDecision:
        # Check blocked paths first
        if self._is_blocked_path(action):
            return PolicyDecision.DENY

        match self._autonomy_level:
            case AutonomyLevel.OBSERVE:
                return PolicyDecision.DENY
            case AutonomyLevel.SUGGEST:
                return PolicyDecision.REQUIRE_APPROVAL
            case AutonomyLevel.ACT_WITHIN_BOUNDS:
                return self._evaluate_bounded(action)

    def _evaluate_bounded(self, action: ProposedAction) -> PolicyDecision:
        match action.risk_level:
            case RiskLevel.LOW:
                return PolicyDecision.ALLOW
            case RiskLevel.MEDIUM:
                return PolicyDecision.REQUIRE_APPROVAL
            case RiskLevel.HIGH:
                return PolicyDecision.REQUIRE_APPROVAL
            case RiskLevel.CRITICAL:
                return PolicyDecision.DENY

    def _is_blocked_path(self, action: ProposedAction) -> bool:
        path_str = action.params.get("path", "")
        if not path_str:
            return False
        resolved = str(Path(path_str).expanduser())
        return any(resolved.startswith(bp) for bp in self._blocked_paths)

    def get_autonomy_level(self, domain: str, skill: str | None = None) -> AutonomyLevel:
        return self._autonomy_level
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/control/test_policy.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/atlas/control/policy.py tests/unit/control/test_policy.py
git commit -m "feat: add Policy Engine with autonomy levels and path blocking"
```

---

## Task 6: Control Plane — Audit Logger

**Files:**
- Create: `src/atlas/control/audit.py`
- Test: `tests/unit/control/test_audit.py`

**Step 1: Write the failing test**

```python
# tests/unit/control/test_audit.py
import asyncio
from pathlib import Path

import pytest

from atlas.contracts.types import AuditEntry, PolicyDecision
from atlas.control.audit import AuditLogger


@pytest.fixture
async def audit_logger(tmp_path: Path):
    db_path = tmp_path / "test.db"
    logger = AuditLogger(db_path=str(db_path))
    await logger.initialize()
    yield logger
    await logger.close()


async def test_log_and_query(audit_logger: AuditLogger):
    entry = AuditEntry(
        actor="core",
        action_type="filesystem_read",
        action_details={"path": "/tmp/test.txt"},
        policy_decision=PolicyDecision.ALLOW,
        outcome="success",
        correlation_id="corr-1",
    )
    await audit_logger.log(entry)
    entries = await audit_logger.query(limit=10)
    assert len(entries) == 1
    assert entries[0]["actor"] == "core"
    assert entries[0]["correlation_id"] == "corr-1"


async def test_log_multiple_and_query_recent(audit_logger: AuditLogger):
    for i in range(5):
        entry = AuditEntry(
            actor=f"actor-{i}",
            action_type="test",
            outcome="success",
        )
        await audit_logger.log(entry)
    entries = await audit_logger.query(limit=3)
    assert len(entries) == 3


async def test_query_empty_log(audit_logger: AuditLogger):
    entries = await audit_logger.query(limit=10)
    assert entries == []
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/control/test_audit.py -v`
Expected: FAIL — module not found

**Step 3: Write implementation**

```python
# src/atlas/control/audit.py
"""Audit Logger — append-only record of every significant ATLAS action."""

from __future__ import annotations

import json

import aiosqlite

from atlas.contracts.types import AuditEntry


class AuditLogger:
    """Append-only SQLite audit log."""

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                entry_id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                correlation_id TEXT,
                actor TEXT NOT NULL,
                action_type TEXT NOT NULL,
                action_details TEXT NOT NULL,
                policy_decision TEXT,
                outcome TEXT NOT NULL,
                mission_id TEXT,
                task_id TEXT
            )
        """)
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()

    async def log(self, entry: AuditEntry) -> None:
        if not self._db:
            return
        await self._db.execute(
            """INSERT INTO audit_log
               (entry_id, timestamp, correlation_id, actor, action_type,
                action_details, policy_decision, outcome, mission_id, task_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry.entry_id,
                entry.timestamp.isoformat(),
                entry.correlation_id,
                entry.actor,
                entry.action_type,
                json.dumps(entry.action_details),
                entry.policy_decision.value if entry.policy_decision else None,
                entry.outcome,
                entry.mission_id,
                entry.task_id,
            ),
        )
        await self._db.commit()

    async def query(self, limit: int = 50) -> list[dict]:
        if not self._db:
            return []
        cursor = await self._db.execute(
            "SELECT * FROM audit_log ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in rows]
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/control/test_audit.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/atlas/control/audit.py tests/unit/control/test_audit.py
git commit -m "feat: add append-only Audit Logger with SQLite storage"
```

---

## Task 7: Control Plane — Approval Workflow

**Files:**
- Create: `src/atlas/control/approval.py`
- Test: `tests/unit/control/test_approval.py`

**Step 1: Write the failing test**

```python
# tests/unit/control/test_approval.py
import asyncio

import pytest

from atlas.contracts.types import (
    ApprovalRequest,
    ApprovalResult,
    ProposedAction,
    RiskLevel,
)
from atlas.control.approval import ApprovalWorkflow


async def test_auto_approve_mode():
    workflow = ApprovalWorkflow(auto_approve=True)
    request = ApprovalRequest(
        action=ProposedAction(
            action_type="filesystem_write",
            domain="skills",
            description="write file",
            risk_level=RiskLevel.MEDIUM,
        ),
        reasoning="needed for task",
    )
    result = await workflow.request_approval(request)
    assert result == ApprovalResult.APPROVED


async def test_auto_deny_mode():
    workflow = ApprovalWorkflow(auto_deny=True)
    request = ApprovalRequest(
        action=ProposedAction(
            action_type="filesystem_write",
            domain="skills",
            description="write file",
        ),
    )
    result = await workflow.request_approval(request)
    assert result == ApprovalResult.DENIED
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/control/test_approval.py -v`
Expected: FAIL — module not found

**Step 3: Write implementation**

```python
# src/atlas/control/approval.py
"""Approval Workflow — human-in-the-loop approval for actions requiring permission."""

from __future__ import annotations

import sys

from atlas.contracts.types import ApprovalRequest, ApprovalResult


class ApprovalWorkflow:
    """Handles approval requests. Phase 1: terminal prompts or auto modes for testing."""

    def __init__(
        self,
        auto_approve: bool = False,
        auto_deny: bool = False,
        interactive: bool = True,
    ):
        self._auto_approve = auto_approve
        self._auto_deny = auto_deny
        self._interactive = interactive

    async def request_approval(self, request: ApprovalRequest) -> ApprovalResult:
        if self._auto_approve:
            return ApprovalResult.APPROVED
        if self._auto_deny:
            return ApprovalResult.DENIED

        if not self._interactive:
            return ApprovalResult.DENIED

        return self._prompt_terminal(request)

    def _prompt_terminal(self, request: ApprovalRequest) -> ApprovalResult:
        action = request.action
        print(f"\n[approval] {action.description if action else 'Unknown action'}")
        if request.reasoning:
            print(f"  Reason: {request.reasoning}")
        if action:
            print(f"  Risk: {action.risk_level.value}")
            if action.params:
                for k, v in action.params.items():
                    print(f"  {k}: {v}")

        try:
            response = input("  Approve? (y/n): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return ApprovalResult.DENIED

        if response in ("y", "yes"):
            return ApprovalResult.APPROVED
        return ApprovalResult.DENIED
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/control/test_approval.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/atlas/control/approval.py tests/unit/control/test_approval.py
git commit -m "feat: add Approval Workflow with terminal prompts and auto modes"
```

---

## Task 8: Memory — SQLite Store & Working Memory

**Files:**
- Create: `src/atlas/memory/store.py`
- Create: `src/atlas/memory/working.py`
- Test: `tests/unit/memory/test_working.py`

**Step 1: Write the failing test**

```python
# tests/unit/memory/test_working.py
from atlas.memory.working import WorkingMemoryStore


def test_set_and_get():
    store = WorkingMemoryStore()
    store.set("key1", "value1")
    assert store.get("key1") == "value1"


def test_get_missing_key_returns_none():
    store = WorkingMemoryStore()
    assert store.get("nonexistent") is None


def test_clear():
    store = WorkingMemoryStore()
    store.set("a", 1)
    store.set("b", 2)
    store.clear()
    assert store.get("a") is None
    assert store.get("b") is None


def test_overwrite():
    store = WorkingMemoryStore()
    store.set("key", "old")
    store.set("key", "new")
    assert store.get("key") == "new"


def test_max_keys_eviction():
    store = WorkingMemoryStore(max_keys=3)
    store.set("a", 1)
    store.set("b", 2)
    store.set("c", 3)
    store.set("d", 4)  # should evict "a"
    assert store.get("a") is None
    assert store.get("d") == 4


def test_get_all():
    store = WorkingMemoryStore()
    store.set("x", 10)
    store.set("y", 20)
    all_items = store.get_all()
    assert all_items == {"x": 10, "y": 20}
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/memory/test_working.py -v`
Expected: FAIL — module not found

**Step 3: Write implementations**

```python
# src/atlas/memory/store.py
"""SQLite database connection and schema management for ATLAS."""

from __future__ import annotations

import aiosqlite


class DatabaseStore:
    """Manages the single ATLAS SQLite database."""

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._create_tables()

    async def close(self) -> None:
        if self._db:
            await self._db.close()

    @property
    def db(self) -> aiosqlite.Connection:
        if not self._db:
            raise RuntimeError("Database not initialized. Call initialize() first.")
        return self._db

    async def _create_tables(self) -> None:
        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS episodes (
                episode_id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                episode_type TEXT NOT NULL,
                trigger_text TEXT,
                plan TEXT,
                actions TEXT,
                outcome TEXT,
                lessons TEXT,
                mission_id TEXT,
                task_id TEXT,
                tags TEXT,
                correlation_id TEXT
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS episodes_fts USING fts5(
                episode_id,
                trigger_text,
                plan,
                outcome,
                content=episodes,
                content_rowid=rowid
            );

            CREATE TRIGGER IF NOT EXISTS episodes_ai AFTER INSERT ON episodes BEGIN
                INSERT INTO episodes_fts(episode_id, trigger_text, plan, outcome)
                VALUES (new.episode_id, new.trigger_text, new.plan, new.outcome);
            END;

            CREATE TABLE IF NOT EXISTS audit_log (
                entry_id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                correlation_id TEXT,
                actor TEXT NOT NULL,
                action_type TEXT NOT NULL,
                action_details TEXT NOT NULL,
                policy_decision TEXT,
                outcome TEXT NOT NULL,
                mission_id TEXT,
                task_id TEXT
            );

            CREATE TABLE IF NOT EXISTS missions (
                mission_id TEXT PRIMARY KEY,
                goal_text TEXT NOT NULL,
                status TEXT NOT NULL,
                task_list TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                mission_id TEXT,
                description TEXT NOT NULL,
                task_type TEXT NOT NULL,
                skill_id TEXT,
                input_params TEXT,
                expected_outcome TEXT,
                status TEXT NOT NULL,
                result TEXT,
                priority INTEGER DEFAULT 0,
                retry_count INTEGER DEFAULT 0,
                max_retries INTEGER DEFAULT 3,
                created_at TEXT NOT NULL
            );
        """)
        await self._db.commit()
```

```python
# src/atlas/memory/working.py
"""Working Memory — fast in-memory key-value store for current operational context."""

from __future__ import annotations

from collections import OrderedDict
from typing import Any


class WorkingMemoryStore:
    """Dict-backed working memory with optional max key eviction (LRU)."""

    def __init__(self, max_keys: int = 100):
        self._store: OrderedDict[str, Any] = OrderedDict()
        self._max_keys = max_keys

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        if key in self._store:
            self._store.move_to_end(key)
        self._store[key] = value
        while len(self._store) > self._max_keys:
            self._store.popitem(last=False)

    def get(self, key: str) -> Any | None:
        if key in self._store:
            self._store.move_to_end(key)
            return self._store[key]
        return None

    def clear(self) -> None:
        self._store.clear()

    def get_all(self) -> dict[str, Any]:
        return dict(self._store)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/memory/test_working.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/atlas/memory/store.py src/atlas/memory/working.py tests/unit/memory/test_working.py
git commit -m "feat: add SQLite store schema and Working Memory with LRU eviction"
```

---

## Task 9: Memory — Episodic Memory

**Files:**
- Create: `src/atlas/memory/episodic.py`
- Test: `tests/unit/memory/test_episodic.py`

**Step 1: Write the failing test**

```python
# tests/unit/memory/test_episodic.py
from pathlib import Path

import pytest

from atlas.contracts.types import Episode, EpisodeType
from atlas.memory.store import DatabaseStore
from atlas.memory.episodic import EpisodicMemoryStore


@pytest.fixture
async def episodic_store(tmp_path: Path):
    db = DatabaseStore(str(tmp_path / "test.db"))
    await db.initialize()
    store = EpisodicMemoryStore(db)
    yield store
    await db.close()


async def test_record_and_retrieve(episodic_store: EpisodicMemoryStore):
    episode = Episode(
        episode_type=EpisodeType.TASK_EXECUTION,
        trigger="user goal",
        plan="read the file",
        outcome="file read successfully",
        tags=["filesystem"],
    )
    episode_id = await episodic_store.record(episode)
    assert episode_id == episode.episode_id

    result = await episodic_store.get_by_id(episode_id)
    assert result is not None
    assert result.trigger == "user goal"
    assert result.outcome == "file read successfully"


async def test_search_fts(episodic_store: EpisodicMemoryStore):
    await episodic_store.record(Episode(
        trigger="deploy the application",
        outcome="deployment succeeded",
    ))
    await episodic_store.record(Episode(
        trigger="fix the login bug",
        outcome="bug fixed",
    ))
    results = await episodic_store.search("deploy", limit=10)
    assert len(results) == 1
    assert "deploy" in results[0].trigger


async def test_query_recent(episodic_store: EpisodicMemoryStore):
    for i in range(5):
        await episodic_store.record(Episode(trigger=f"task-{i}", outcome=f"done-{i}"))
    results = await episodic_store.query_recent(limit=3)
    assert len(results) == 3


async def test_get_by_id_missing(episodic_store: EpisodicMemoryStore):
    result = await episodic_store.get_by_id("nonexistent")
    assert result is None
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/memory/test_episodic.py -v`
Expected: FAIL — module not found

**Step 3: Write implementation**

```python
# src/atlas/memory/episodic.py
"""Episodic Memory — chronological record of agent actions and observations."""

from __future__ import annotations

import json

from atlas.contracts.types import Episode, EpisodeType
from atlas.memory.store import DatabaseStore


class EpisodicMemoryStore:
    """SQLite-backed episodic memory with FTS5 full-text search."""

    def __init__(self, db: DatabaseStore):
        self._db = db

    async def record(self, episode: Episode) -> str:
        await self._db.db.execute(
            """INSERT INTO episodes
               (episode_id, timestamp, episode_type, trigger_text, plan,
                actions, outcome, lessons, mission_id, task_id, tags, correlation_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                episode.episode_id,
                episode.timestamp.isoformat(),
                episode.episode_type.value,
                episode.trigger,
                episode.plan,
                json.dumps(episode.actions),
                episode.outcome,
                json.dumps(episode.lessons),
                episode.mission_id,
                episode.task_id,
                json.dumps(episode.tags),
                episode.correlation_id,
            ),
        )
        await self._db.db.commit()
        return episode.episode_id

    async def get_by_id(self, episode_id: str) -> Episode | None:
        cursor = await self._db.db.execute(
            "SELECT * FROM episodes WHERE episode_id = ?", (episode_id,)
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return self._row_to_episode(cursor.description, row)

    async def search(self, text_query: str, limit: int = 20) -> list[Episode]:
        cursor = await self._db.db.execute(
            """SELECT e.* FROM episodes e
               JOIN episodes_fts fts ON e.episode_id = fts.episode_id
               WHERE episodes_fts MATCH ?
               ORDER BY e.timestamp DESC LIMIT ?""",
            (text_query, limit),
        )
        rows = await cursor.fetchall()
        return [self._row_to_episode(cursor.description, row) for row in rows]

    async def query_recent(self, limit: int = 50) -> list[Episode]:
        cursor = await self._db.db.execute(
            "SELECT * FROM episodes ORDER BY timestamp DESC LIMIT ?", (limit,)
        )
        rows = await cursor.fetchall()
        return [self._row_to_episode(cursor.description, row) for row in rows]

    def _row_to_episode(self, description, row) -> Episode:
        cols = [desc[0] for desc in description]
        data = dict(zip(cols, row))
        return Episode(
            episode_id=data["episode_id"],
            episode_type=EpisodeType(data["episode_type"]),
            trigger=data.get("trigger_text", ""),
            plan=data.get("plan", ""),
            actions=json.loads(data.get("actions", "[]")),
            outcome=data.get("outcome", ""),
            lessons=json.loads(data.get("lessons", "[]")),
            mission_id=data.get("mission_id"),
            task_id=data.get("task_id"),
            tags=json.loads(data.get("tags", "[]")),
            correlation_id=data.get("correlation_id"),
        )
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/memory/test_episodic.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/atlas/memory/episodic.py tests/unit/memory/test_episodic.py
git commit -m "feat: add Episodic Memory with SQLite storage and FTS5 search"
```

---

## Task 10: Memory — Context Assembler

**Files:**
- Create: `src/atlas/memory/retrieval.py`
- Test: `tests/unit/memory/test_retrieval.py`

**Step 1: Write the failing test**

```python
# tests/unit/memory/test_retrieval.py
from atlas.contracts.types import ContextQuery, Episode
from atlas.memory.retrieval import ContextAssembler


def test_assemble_within_budget():
    episodes = [
        Episode(trigger=f"task-{i}", outcome=f"result-{i}" * 50)
        for i in range(10)
    ]
    assembler = ContextAssembler()
    query = ContextQuery(
        purpose="planning",
        task_description="test task",
        token_budget=500,
    )
    bundle = assembler.assemble(query, episodes)
    assert bundle.total_tokens <= bundle.budget_tokens
    assert bundle.budget_tokens == 500
    assert len(bundle.contents) > 0


def test_assemble_empty_episodes():
    assembler = ContextAssembler()
    query = ContextQuery(purpose="planning", task_description="test")
    bundle = assembler.assemble(query, [])
    assert bundle.total_tokens == 0
    assert len(bundle.contents) == 0


def test_estimate_tokens():
    assembler = ContextAssembler()
    # ~4 chars per token is the approximation
    assert assembler.estimate_tokens("a" * 400) == 100
    assert assembler.estimate_tokens("") == 0


def test_assemble_prioritizes_recent():
    episodes = [
        Episode(trigger=f"old-task-{i}", outcome="old result")
        for i in range(5)
    ]
    recent = Episode(trigger="recent-task", outcome="recent result")
    episodes.append(recent)

    assembler = ContextAssembler()
    query = ContextQuery(
        purpose="planning",
        task_description="test",
        token_budget=200,  # tight budget — only a few fit
    )
    bundle = assembler.assemble(query, episodes)
    # Most recent should be included
    sources = [c["source"] for c in bundle.contents]
    assert any("recent-task" in s for s in sources)
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/memory/test_retrieval.py -v`
Expected: FAIL — module not found

**Step 3: Write implementation**

```python
# src/atlas/memory/retrieval.py
"""Context Assembler — builds token-budgeted context bundles for Claude Code prompts."""

from __future__ import annotations

from atlas.contracts.types import ContextBundle, ContextQuery, Episode


class ContextAssembler:
    """Assembles context from episodes into token-budgeted bundles."""

    CHARS_PER_TOKEN = 4  # rough approximation

    def estimate_tokens(self, text: str) -> int:
        if not text:
            return 0
        return len(text) // self.CHARS_PER_TOKEN

    def assemble(self, query: ContextQuery, episodes: list[Episode]) -> ContextBundle:
        if not episodes:
            return ContextBundle(budget_tokens=query.token_budget)

        # Most recent first (episodes should already be ordered, but ensure it)
        sorted_episodes = list(reversed(episodes))

        contents: list[dict] = []
        total_tokens = 0

        for episode in sorted_episodes:
            text = self._episode_to_text(episode)
            tokens = self.estimate_tokens(text)

            if total_tokens + tokens > query.token_budget:
                # Try to fit a truncated version
                remaining = query.token_budget - total_tokens
                if remaining > 20:  # worth including something
                    truncated = text[: remaining * self.CHARS_PER_TOKEN]
                    contents.append({
                        "source": episode.trigger,
                        "text": truncated,
                        "tokens": remaining,
                        "truncated": True,
                    })
                    total_tokens += remaining
                break

            contents.append({
                "source": episode.trigger,
                "text": text,
                "tokens": tokens,
                "truncated": False,
            })
            total_tokens += tokens

        return ContextBundle(
            contents=contents,
            total_tokens=total_tokens,
            budget_tokens=query.token_budget,
        )

    def _episode_to_text(self, episode: Episode) -> str:
        parts = []
        if episode.trigger:
            parts.append(f"Trigger: {episode.trigger}")
        if episode.plan:
            parts.append(f"Plan: {episode.plan}")
        if episode.outcome:
            parts.append(f"Outcome: {episode.outcome}")
        if episode.lessons:
            parts.append(f"Lessons: {', '.join(episode.lessons)}")
        return "\n".join(parts)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/memory/test_retrieval.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/atlas/memory/retrieval.py tests/unit/memory/test_retrieval.py
git commit -m "feat: add Context Assembler with token budgeting and recency priority"
```

---

## Task 11: Environment — Filesystem Provider

**Files:**
- Create: `src/atlas/env/filesystem.py`
- Test: `tests/unit/env/test_filesystem.py`

**Step 1: Write the failing test**

```python
# tests/unit/env/test_filesystem.py
from pathlib import Path

import pytest

from atlas.env.filesystem import FilesystemProvider


@pytest.fixture
def fs(tmp_workspace: Path) -> FilesystemProvider:
    return FilesystemProvider(workspace=str(tmp_workspace))


def test_read_file(fs: FilesystemProvider, tmp_workspace: Path):
    result = fs.read(str(tmp_workspace / "src" / "main.py"))
    assert "hello" in result


def test_read_missing_file(fs: FilesystemProvider):
    with pytest.raises(FileNotFoundError):
        fs.read("/nonexistent/file.py")


def test_write_file(fs: FilesystemProvider, tmp_workspace: Path):
    path = str(tmp_workspace / "output.txt")
    fs.write(path, "test content")
    assert Path(path).read_text() == "test content"


def test_list_dir(fs: FilesystemProvider, tmp_workspace: Path):
    entries = fs.list_dir(str(tmp_workspace))
    names = [e["name"] for e in entries]
    assert "src" in names


def test_search_glob(fs: FilesystemProvider, tmp_workspace: Path):
    results = fs.search(str(tmp_workspace), pattern="**/*.py")
    assert len(results) >= 1
    assert any("main.py" in r for r in results)
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/env/test_filesystem.py -v`
Expected: FAIL — module not found

**Step 3: Write implementation**

```python
# src/atlas/env/filesystem.py
"""Filesystem Provider — file and directory operations."""

from __future__ import annotations

import glob
from pathlib import Path


class FilesystemProvider:
    """Wraps pathlib for file operations with workspace awareness."""

    def __init__(self, workspace: str = "."):
        self._workspace = Path(workspace).resolve()

    def read(self, path: str) -> str:
        p = Path(path).resolve()
        if not p.exists():
            raise FileNotFoundError(f"File not found: {path}")
        return p.read_text()

    def write(self, path: str, content: str) -> None:
        p = Path(path).resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)

    def list_dir(self, path: str, recursive: bool = False) -> list[dict]:
        p = Path(path).resolve()
        if not p.is_dir():
            raise NotADirectoryError(f"Not a directory: {path}")
        entries = []
        items = p.rglob("*") if recursive else p.iterdir()
        for item in sorted(items):
            entries.append({
                "name": item.name,
                "path": str(item),
                "is_dir": item.is_dir(),
                "size": item.stat().st_size if item.is_file() else 0,
            })
        return entries

    def search(self, root: str, pattern: str) -> list[str]:
        p = Path(root).resolve()
        return [str(match) for match in sorted(p.glob(pattern))]

    @property
    def workspace(self) -> str:
        return str(self._workspace)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/env/test_filesystem.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/atlas/env/filesystem.py tests/unit/env/test_filesystem.py
git commit -m "feat: add Filesystem Provider with read/write/list/search"
```

---

## Task 12: Environment — Process Provider

**Files:**
- Create: `src/atlas/env/process.py`
- Test: `tests/unit/env/test_process.py`

**Step 1: Write the failing test**

```python
# tests/unit/env/test_process.py
import pytest

from atlas.env.process import ProcessProvider


@pytest.fixture
def proc() -> ProcessProvider:
    return ProcessProvider()


async def test_execute_simple_command(proc: ProcessProvider):
    result = await proc.execute("echo hello")
    assert result["exit_code"] == 0
    assert "hello" in result["stdout"]


async def test_execute_failing_command(proc: ProcessProvider):
    result = await proc.execute("false")
    assert result["exit_code"] != 0


async def test_execute_with_timeout(proc: ProcessProvider):
    result = await proc.execute("sleep 10", timeout=1)
    assert result["exit_code"] != 0
    assert "timeout" in result.get("error", "").lower() or result["exit_code"] == -1


async def test_execute_captures_stderr(proc: ProcessProvider):
    result = await proc.execute("echo error >&2")
    assert "error" in result["stderr"]
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/env/test_process.py -v`
Expected: FAIL — module not found

**Step 3: Write implementation**

```python
# src/atlas/env/process.py
"""Process Provider — spawn and manage external processes."""

from __future__ import annotations

import asyncio
import time


class ProcessProvider:
    """Async process execution with timeout support."""

    def __init__(self, default_timeout: int = 30):
        self._default_timeout = default_timeout

    async def execute(
        self, cmd: str, cwd: str | None = None, timeout: int | None = None
    ) -> dict:
        timeout = timeout or self._default_timeout
        start = time.monotonic()

        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
            elapsed = int((time.monotonic() - start) * 1000)

            return {
                "exit_code": proc.returncode,
                "stdout": stdout.decode(errors="replace"),
                "stderr": stderr.decode(errors="replace"),
                "execution_time_ms": elapsed,
            }
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            elapsed = int((time.monotonic() - start) * 1000)
            return {
                "exit_code": -1,
                "stdout": "",
                "stderr": "",
                "error": f"Timeout after {timeout}s",
                "execution_time_ms": elapsed,
            }
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/env/test_process.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/atlas/env/process.py tests/unit/env/test_process.py
git commit -m "feat: add Process Provider with async execution and timeout"
```

---

## Task 13: Environment — Claude Code Bridge

**Files:**
- Create: `src/atlas/env/claude.py`
- Test: `tests/unit/env/test_claude.py`

**Step 1: Write the failing test**

```python
# tests/unit/env/test_claude.py
import json

import pytest

from atlas.contracts.types import ClaudeResponse
from atlas.env.claude import ClaudeCodeBridge, parse_claude_response


def test_parse_claude_response_plain_text():
    raw = "Here is the plan:\n1. Read file\n2. Modify it\n3. Write it back"
    response = parse_claude_response(raw)
    assert response.content == raw
    assert response.parsed_output is None


def test_parse_claude_response_json_block():
    raw = '''Here is the plan:
```json
{"tasks": [{"description": "read file", "skill": "file.read"}]}
```
Done.'''
    response = parse_claude_response(raw)
    assert response.parsed_output is not None
    assert response.parsed_output["tasks"][0]["skill"] == "file.read"


def test_parse_claude_response_no_json():
    raw = "Just a text response with no structured data."
    response = parse_claude_response(raw)
    assert response.content == raw
    assert response.parsed_output is None


def test_parse_claude_response_invalid_json_block():
    raw = '```json\n{invalid json}\n```'
    response = parse_claude_response(raw)
    assert response.parsed_output is None
    assert response.content == raw
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/env/test_claude.py -v`
Expected: FAIL — module not found

**Step 3: Write implementation**

```python
# src/atlas/env/claude.py
"""Claude Code Bridge — manages interactions with the Claude Code CLI."""

from __future__ import annotations

import asyncio
import json
import re
import time

from atlas.contracts.errors import ClaudeCodeError, ClaudeCodeUnavailableError
from atlas.contracts.types import ClaudeResponse


def parse_claude_response(raw: str) -> ClaudeResponse:
    """Extract structured output from Claude Code CLI response text."""
    parsed = None
    # Look for ```json ... ``` blocks
    pattern = r"```json\s*\n(.*?)\n```"
    match = re.search(pattern, raw, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(1))
        except json.JSONDecodeError:
            parsed = None

    return ClaudeResponse(content=raw, parsed_output=parsed)


class ClaudeCodeBridge:
    """Manages Claude Code CLI subprocess calls. Phase 1: one-shot only."""

    def __init__(self, timeout: int = 120):
        self._timeout = timeout

    async def oneshot(
        self, prompt: str, system_prompt: str | None = None
    ) -> ClaudeResponse:
        cmd = ["claude", "-p", prompt]
        if system_prompt:
            cmd.extend(["--system", system_prompt])

        start = time.monotonic()
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self._timeout
            )
        except FileNotFoundError:
            raise ClaudeCodeUnavailableError(
                "Claude Code CLI not found. Is 'claude' on PATH?"
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise ClaudeCodeError(
                f"Claude Code CLI timed out after {self._timeout}s"
            )

        elapsed = int((time.monotonic() - start) * 1000)

        if proc.returncode != 0:
            error_text = stderr.decode(errors="replace").strip()
            raise ClaudeCodeError(
                f"Claude Code CLI exited with code {proc.returncode}: {error_text}"
            )

        raw_output = stdout.decode(errors="replace")
        response = parse_claude_response(raw_output)
        response.execution_time_ms = elapsed
        return response
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/env/test_claude.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/atlas/env/claude.py tests/unit/env/test_claude.py
git commit -m "feat: add Claude Code Bridge with one-shot mode and response parsing"
```

---

## Task 14: Environment — Facade & State

**Files:**
- Create: `src/atlas/env/facade.py`
- Create: `src/atlas/env/state.py`

**Step 1: Write implementation**

```python
# src/atlas/env/state.py
"""Environment State Model — structured snapshot for prompt injection."""

from __future__ import annotations

import platform
from pathlib import Path

from atlas.env.filesystem import FilesystemProvider


class EnvironmentStateModel:
    """Produces a token-efficient environment state snapshot."""

    def __init__(self, filesystem: FilesystemProvider):
        self._filesystem = filesystem

    def snapshot(self) -> dict:
        return {
            "workspace": self._workspace_summary(),
            "system": self._system_info(),
        }

    def _workspace_summary(self) -> dict:
        workspace = self._filesystem.workspace
        try:
            entries = self._filesystem.list_dir(workspace)
            return {
                "path": workspace,
                "entries": [e["name"] for e in entries[:50]],
                "total_entries": len(entries),
            }
        except Exception:
            return {"path": workspace, "entries": [], "error": "could not list"}

    def _system_info(self) -> dict:
        return {
            "os": platform.system(),
            "python": platform.python_version(),
        }
```

```python
# src/atlas/env/facade.py
"""Environment Facade — single entry point for all environment interactions."""

from __future__ import annotations

from atlas.contracts.errors import EnvironmentActionError
from atlas.contracts.types import (
    ActionResult,
    ClaudeResponse,
    EnvironmentAction,
    ExecutionContext,
)
from atlas.env.claude import ClaudeCodeBridge
from atlas.env.filesystem import FilesystemProvider
from atlas.env.process import ProcessProvider
from atlas.env.state import EnvironmentStateModel


class EnvironmentFacade:
    """Routes EnvironmentAction objects to the appropriate provider."""

    def __init__(
        self,
        filesystem: FilesystemProvider | None = None,
        process: ProcessProvider | None = None,
        claude: ClaudeCodeBridge | None = None,
    ):
        self._fs = filesystem or FilesystemProvider()
        self._proc = process or ProcessProvider()
        self._claude = claude or ClaudeCodeBridge()
        self._state = EnvironmentStateModel(self._fs)

    async def execute(
        self, action: EnvironmentAction, ctx: ExecutionContext | None = None
    ) -> ActionResult:
        try:
            match action.action_type:
                case "filesystem_read":
                    content = self._fs.read(action.params["path"])
                    return ActionResult(
                        action_id=action.action_id, status="success", output=content
                    )
                case "filesystem_write":
                    self._fs.write(action.params["path"], action.params["content"])
                    return ActionResult(
                        action_id=action.action_id, status="success"
                    )
                case "filesystem_search":
                    results = self._fs.search(
                        action.params.get("root", "."),
                        action.params["pattern"],
                    )
                    return ActionResult(
                        action_id=action.action_id, status="success", output=results
                    )
                case "process_execute":
                    result = await self._proc.execute(
                        action.params["command"],
                        cwd=action.params.get("cwd"),
                        timeout=action.timeout,
                    )
                    status = "success" if result["exit_code"] == 0 else "failure"
                    return ActionResult(
                        action_id=action.action_id,
                        status=status,
                        output=result,
                        error=result.get("error"),
                    )
                case _:
                    return ActionResult(
                        action_id=action.action_id,
                        status="failure",
                        error=f"Unknown action type: {action.action_type}",
                    )
        except Exception as e:
            return ActionResult(
                action_id=action.action_id,
                status="failure",
                error=str(e),
            )

    def get_state(self) -> dict:
        return self._state.snapshot()

    async def claude_oneshot(
        self,
        prompt: str,
        system_prompt: str | None = None,
        ctx: ExecutionContext | None = None,
    ) -> ClaudeResponse:
        return await self._claude.oneshot(prompt, system_prompt)
```

**Step 2: Verify imports**

Run: `python -c "from atlas.env.facade import EnvironmentFacade; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add src/atlas/env/facade.py src/atlas/env/state.py
git commit -m "feat: add Environment Facade and State Model"
```

---

## Task 15: Skills — Models, Registry & Runtime

**Files:**
- Create: `src/atlas/skills/models.py`
- Create: `src/atlas/skills/registry.py`
- Create: `src/atlas/skills/runtime.py`
- Test: `tests/unit/skills/test_registry.py`

**Step 1: Write the failing test**

```python
# tests/unit/skills/test_registry.py
import pytest

from atlas.contracts.errors import SkillNotFoundError
from atlas.skills.registry import SkillRegistry


@pytest.fixture
def registry() -> SkillRegistry:
    reg = SkillRegistry()

    async def read_handler(params: dict) -> dict:
        return {"content": f"contents of {params['path']}"}

    async def write_handler(params: dict) -> dict:
        return {"written": True}

    reg.register("file.read", "Read File", "Read contents of a file",
                 handler=read_handler, risk_level="low")
    reg.register("file.write", "Write File", "Write content to a file",
                 handler=write_handler, risk_level="medium")
    return reg


def test_list_all(registry: SkillRegistry):
    skills = registry.list_all()
    assert len(skills) == 2
    ids = [s.skill_id for s in skills]
    assert "file.read" in ids
    assert "file.write" in ids


def test_get_existing(registry: SkillRegistry):
    skill = registry.get("file.read")
    assert skill.name == "Read File"


def test_get_missing_raises():
    reg = SkillRegistry()
    with pytest.raises(SkillNotFoundError):
        reg.get("nonexistent")


def test_search_keyword(registry: SkillRegistry):
    results = registry.search("read")
    assert len(results) >= 1
    assert results[0].skill_id == "file.read"


def test_search_no_match(registry: SkillRegistry):
    results = registry.search("deploy kubernetes")
    assert len(results) == 0
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/skills/test_registry.py -v`
Expected: FAIL — module not found

**Step 3: Write implementations**

```python
# src/atlas/skills/models.py
"""Skill data models — definitions, descriptors, and invocation types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

from atlas.contracts.types import RiskLevel, SkillDescriptor

# Type alias for async skill handlers
SkillHandler = Callable[[dict[str, Any]], Coroutine[Any, Any, dict[str, Any]]]


@dataclass
class SkillDefinition:
    """Full skill definition stored in the registry."""
    skill_id: str
    name: str
    description: str
    handler: SkillHandler
    risk_level: RiskLevel = RiskLevel.LOW
    tags: list[str] = field(default_factory=list)

    def to_descriptor(self) -> SkillDescriptor:
        return SkillDescriptor(
            skill_id=self.skill_id,
            name=self.name,
            description=self.description,
            risk_level=self.risk_level,
            tags=self.tags,
        )
```

```python
# src/atlas/skills/registry.py
"""Skill Registry — central catalog of available skills."""

from __future__ import annotations

from atlas.contracts.errors import SkillNotFoundError
from atlas.contracts.types import RiskLevel, SkillDescriptor
from atlas.skills.models import SkillDefinition, SkillHandler


class SkillRegistry:
    """In-memory skill registry with keyword search."""

    def __init__(self):
        self._skills: dict[str, SkillDefinition] = {}

    def register(
        self,
        skill_id: str,
        name: str,
        description: str,
        handler: SkillHandler,
        risk_level: str = "low",
        tags: list[str] | None = None,
    ) -> None:
        self._skills[skill_id] = SkillDefinition(
            skill_id=skill_id,
            name=name,
            description=description,
            handler=handler,
            risk_level=RiskLevel(risk_level),
            tags=tags or [],
        )

    def unregister(self, skill_id: str) -> None:
        self._skills.pop(skill_id, None)

    def get(self, skill_id: str) -> SkillDescriptor:
        if skill_id not in self._skills:
            raise SkillNotFoundError(f"Skill not found: {skill_id}")
        return self._skills[skill_id].to_descriptor()

    def get_definition(self, skill_id: str) -> SkillDefinition:
        if skill_id not in self._skills:
            raise SkillNotFoundError(f"Skill not found: {skill_id}")
        return self._skills[skill_id]

    def list_all(self) -> list[SkillDescriptor]:
        return [s.to_descriptor() for s in self._skills.values()]

    def search(self, query: str) -> list[SkillDescriptor]:
        query_lower = query.lower()
        terms = query_lower.split()
        results = []
        for skill in self._skills.values():
            searchable = f"{skill.name} {skill.description} {' '.join(skill.tags)}".lower()
            if all(term in searchable for term in terms):
                results.append(skill.to_descriptor())
        return results
```

```python
# src/atlas/skills/runtime.py
"""Invocation Runtime — executes skills with validation and result packaging."""

from __future__ import annotations

import time

from atlas.contracts.errors import SkillInvocationError
from atlas.contracts.types import ExecutionContext, SkillResult, new_id
from atlas.skills.registry import SkillRegistry


class InvocationRuntime:
    """Executes registered skills and packages results."""

    def __init__(self, registry: SkillRegistry):
        self._registry = registry

    async def invoke(
        self,
        skill_id: str,
        params: dict,
        ctx: ExecutionContext | None = None,
    ) -> SkillResult:
        definition = self._registry.get_definition(skill_id)
        invocation_id = new_id()
        start = time.monotonic()

        try:
            output = await definition.handler(params)
            elapsed = int((time.monotonic() - start) * 1000)
            return SkillResult(
                invocation_id=invocation_id,
                skill_id=skill_id,
                status="success",
                output=output,
                execution_time_ms=elapsed,
            )
        except Exception as e:
            elapsed = int((time.monotonic() - start) * 1000)
            return SkillResult(
                invocation_id=invocation_id,
                skill_id=skill_id,
                status="failure",
                error=str(e),
                execution_time_ms=elapsed,
            )
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/skills/test_registry.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/atlas/skills/ tests/unit/skills/test_registry.py
git commit -m "feat: add Skill Registry, Models, and Invocation Runtime"
```

---

## Task 16: Skills — Seed Skills

**Files:**
- Create: `src/atlas/skills/seed.py`
- Test: `tests/unit/skills/test_seed.py`

**Step 1: Write the failing test**

```python
# tests/unit/skills/test_seed.py
from pathlib import Path

import pytest

from atlas.env.filesystem import FilesystemProvider
from atlas.env.process import ProcessProvider
from atlas.skills.registry import SkillRegistry
from atlas.skills.seed import register_seed_skills


@pytest.fixture
def seeded_registry(tmp_workspace: Path) -> SkillRegistry:
    registry = SkillRegistry()
    fs = FilesystemProvider(workspace=str(tmp_workspace))
    proc = ProcessProvider()
    register_seed_skills(registry, fs, proc)
    return registry


def test_seed_skills_registered(seeded_registry: SkillRegistry):
    skills = seeded_registry.list_all()
    ids = [s.skill_id for s in skills]
    assert "file.read" in ids
    assert "file.write" in ids
    assert "file.search" in ids
    assert "shell.execute" in ids


async def test_file_read_skill(seeded_registry: SkillRegistry, tmp_workspace: Path):
    defn = seeded_registry.get_definition("file.read")
    result = await defn.handler({"path": str(tmp_workspace / "src" / "main.py")})
    assert "hello" in result["content"]


async def test_file_write_skill(seeded_registry: SkillRegistry, tmp_workspace: Path):
    path = str(tmp_workspace / "new_file.txt")
    defn = seeded_registry.get_definition("file.write")
    result = await defn.handler({"path": path, "content": "new content"})
    assert result["written"] is True
    assert Path(path).read_text() == "new content"


async def test_file_search_skill(seeded_registry: SkillRegistry, tmp_workspace: Path):
    defn = seeded_registry.get_definition("file.search")
    result = await defn.handler({"root": str(tmp_workspace), "pattern": "**/*.py"})
    assert len(result["matches"]) >= 1


async def test_shell_execute_skill(seeded_registry: SkillRegistry):
    defn = seeded_registry.get_definition("shell.execute")
    result = await defn.handler({"command": "echo test123"})
    assert "test123" in result["stdout"]
    assert result["exit_code"] == 0
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/skills/test_seed.py -v`
Expected: FAIL — module not found

**Step 3: Write implementation**

```python
# src/atlas/skills/seed.py
"""Seed Skills — the four built-in skills that ship with ATLAS Phase 1."""

from __future__ import annotations

from atlas.env.filesystem import FilesystemProvider
from atlas.env.process import ProcessProvider
from atlas.skills.registry import SkillRegistry


def register_seed_skills(
    registry: SkillRegistry,
    filesystem: FilesystemProvider,
    process: ProcessProvider,
) -> None:
    """Register the four Phase 1 seed skills."""

    async def file_read(params: dict) -> dict:
        content = filesystem.read(params["path"])
        return {"content": content}

    async def file_write(params: dict) -> dict:
        filesystem.write(params["path"], params["content"])
        return {"written": True, "path": params["path"]}

    async def file_search(params: dict) -> dict:
        matches = filesystem.search(
            params.get("root", filesystem.workspace),
            params["pattern"],
        )
        return {"matches": matches}

    async def shell_execute(params: dict) -> dict:
        result = await process.execute(
            params["command"],
            cwd=params.get("cwd"),
            timeout=params.get("timeout", 30),
        )
        return result

    registry.register(
        "file.read", "Read File",
        "Read the contents of a file at the given path",
        handler=file_read, risk_level="low",
        tags=["filesystem", "read"],
    )
    registry.register(
        "file.write", "Write File",
        "Write content to a file at the given path, creating directories if needed",
        handler=file_write, risk_level="medium",
        tags=["filesystem", "write"],
    )
    registry.register(
        "file.search", "Search Files",
        "Search for files matching a glob pattern in a directory tree",
        handler=file_search, risk_level="low",
        tags=["filesystem", "search"],
    )
    registry.register(
        "shell.execute", "Execute Shell Command",
        "Run a shell command and return stdout, stderr, and exit code",
        handler=shell_execute, risk_level="high",
        tags=["process", "shell"],
    )
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/skills/test_seed.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/atlas/skills/seed.py tests/unit/skills/test_seed.py
git commit -m "feat: add four seed skills (file.read, file.write, file.search, shell.execute)"
```

---

## Task 17: Core — Task Models & Queue

**Files:**
- Create: `src/atlas/core/tasks.py`
- Test: `tests/unit/core/test_tasks.py`

**Step 1: Write the failing test**

```python
# tests/unit/core/test_tasks.py
from atlas.contracts.types import TaskStatus
from atlas.core.tasks import Task, TaskQueue


def test_task_creation():
    task = Task(description="read a file", skill_id="file.read", input_params={"path": "test.py"})
    assert task.status == TaskStatus.PENDING
    assert task.skill_id == "file.read"


def test_task_queue_enqueue_and_dequeue():
    queue = TaskQueue()
    t1 = Task(description="first")
    t2 = Task(description="second")
    queue.enqueue(t1)
    queue.enqueue(t2)
    assert queue.size() == 2
    next_task = queue.get_next()
    assert next_task.description == "first"
    assert next_task.status == TaskStatus.EXECUTING


def test_task_queue_empty():
    queue = TaskQueue()
    assert queue.get_next() is None


def test_task_complete():
    queue = TaskQueue()
    task = Task(description="do something")
    queue.enqueue(task)
    pulled = queue.get_next()
    queue.complete(pulled.task_id, result={"done": True})
    assert pulled.status == TaskStatus.COMPLETED
    assert pulled.result == {"done": True}


def test_task_fail():
    queue = TaskQueue()
    task = Task(description="do something")
    queue.enqueue(task)
    pulled = queue.get_next()
    queue.fail(pulled.task_id, error="something broke")
    assert pulled.status == TaskStatus.FAILED


def test_task_queue_all_tasks():
    queue = TaskQueue()
    queue.enqueue(Task(description="a"))
    queue.enqueue(Task(description="b"))
    assert len(queue.all_tasks()) == 2
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/core/test_tasks.py -v`
Expected: FAIL — module not found

**Step 3: Write implementation**

```python
# src/atlas/core/tasks.py
"""Task models and queue for the Agent Core execution pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from atlas.contracts.types import TaskStatus, new_id


@dataclass
class Task:
    """A single executable unit of work."""
    description: str
    task_id: str = field(default_factory=new_id)
    mission_id: str | None = None
    skill_id: str | None = None
    input_params: dict[str, Any] = field(default_factory=dict)
    expected_outcome: str = ""
    status: TaskStatus = TaskStatus.PENDING
    result: Any = None
    error: str | None = None
    retry_count: int = 0
    max_retries: int = 3


class TaskQueue:
    """Simple FIFO task queue. Phase 1: no priority, no dependencies."""

    def __init__(self):
        self._tasks: dict[str, Task] = {}
        self._order: list[str] = []

    def enqueue(self, task: Task) -> None:
        self._tasks[task.task_id] = task
        self._order.append(task.task_id)

    def get_next(self) -> Task | None:
        for task_id in self._order:
            task = self._tasks[task_id]
            if task.status == TaskStatus.PENDING:
                task.status = TaskStatus.EXECUTING
                return task
        return None

    def complete(self, task_id: str, result: Any = None) -> None:
        task = self._tasks[task_id]
        task.status = TaskStatus.COMPLETED
        task.result = result

    def fail(self, task_id: str, error: str = "") -> None:
        task = self._tasks[task_id]
        task.status = TaskStatus.FAILED
        task.error = error

    def size(self) -> int:
        return len(self._tasks)

    def all_tasks(self) -> list[Task]:
        return [self._tasks[tid] for tid in self._order]

    def pending_count(self) -> int:
        return sum(1 for t in self._tasks.values() if t.status == TaskStatus.PENDING)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/core/test_tasks.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/atlas/core/tasks.py tests/unit/core/test_tasks.py
git commit -m "feat: add Task model and FIFO TaskQueue"
```

---

## Task 18: Core — Mission Planner (Claude Response Parsing)

**Files:**
- Create: `src/atlas/core/missions.py`
- Test: `tests/unit/core/test_missions.py`

**Step 1: Write the failing test**

```python
# tests/unit/core/test_missions.py
import json

import pytest

from atlas.core.missions import MissionPlanner, parse_task_plan
from atlas.core.tasks import Task


def test_parse_task_plan_json():
    raw = json.dumps({
        "tasks": [
            {"description": "Read the file", "skill": "file.read", "params": {"path": "main.py"}},
            {"description": "Modify the code", "skill": "file.write", "params": {"path": "main.py", "content": "new"}},
        ]
    })
    tasks = parse_task_plan(raw)
    assert len(tasks) == 2
    assert tasks[0].skill_id == "file.read"
    assert tasks[0].input_params["path"] == "main.py"
    assert tasks[1].skill_id == "file.write"


def test_parse_task_plan_json_in_markdown():
    raw = '''Here's the plan:
```json
{"tasks": [{"description": "Run tests", "skill": "shell.execute", "params": {"command": "pytest"}}]}
```
That should work.'''
    tasks = parse_task_plan(raw)
    assert len(tasks) == 1
    assert tasks[0].skill_id == "shell.execute"


def test_parse_task_plan_fallback_numbered_list():
    raw = """Here's what I'll do:
1. Read the file src/main.py
2. Add error handling to the main function
3. Write the updated file back"""
    tasks = parse_task_plan(raw)
    assert len(tasks) == 3
    assert "Read the file" in tasks[0].description


def test_parse_task_plan_empty():
    tasks = parse_task_plan("")
    assert tasks == []
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/unit/core/test_missions.py -v`
Expected: FAIL — module not found

**Step 3: Write implementation**

```python
# src/atlas/core/missions.py
"""Mission Planner — decomposes goals into task lists via Claude Code."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from atlas.contracts.types import MissionStatus, new_id
from atlas.core.tasks import Task


@dataclass
class Mission:
    """A user-assigned goal with its task list and state."""
    mission_id: str = field(default_factory=new_id)
    goal_text: str = ""
    status: MissionStatus = MissionStatus.PLANNING
    tasks: list[Task] = field(default_factory=list)


def parse_task_plan(raw: str) -> list[Task]:
    """Parse Claude Code response into a list of Tasks.

    Tries JSON first (structured), falls back to numbered list (unstructured).
    """
    if not raw.strip():
        return []

    # Try JSON block in markdown
    json_match = re.search(r"```json\s*\n(.*?)\n```", raw, re.DOTALL)
    if json_match:
        return _parse_json_tasks(json_match.group(1))

    # Try raw JSON
    try:
        return _parse_json_tasks(raw)
    except (json.JSONDecodeError, KeyError, TypeError):
        pass

    # Fallback: numbered list
    return _parse_numbered_list(raw)


def _parse_json_tasks(json_str: str) -> list[Task]:
    data = json.loads(json_str)
    tasks = []
    for item in data.get("tasks", []):
        tasks.append(Task(
            description=item.get("description", ""),
            skill_id=item.get("skill"),
            input_params=item.get("params", {}),
            expected_outcome=item.get("expected_outcome", ""),
        ))
    return tasks


def _parse_numbered_list(text: str) -> list[Task]:
    pattern = r"^\s*\d+[\.\)]\s*(.+)$"
    tasks = []
    for match in re.finditer(pattern, text, re.MULTILINE):
        description = match.group(1).strip()
        if description:
            tasks.append(Task(description=description))
    return tasks


PLANNING_PROMPT_TEMPLATE = """You are ATLAS, an autonomous agent. Decompose the following goal into a sequence of executable tasks.

GOAL: {goal}

AVAILABLE SKILLS:
{skills}

ENVIRONMENT STATE:
{env_state}

Respond with a JSON block:
```json
{{
  "tasks": [
    {{"description": "what this step does", "skill": "skill.id", "params": {{"key": "value"}}}},
    ...
  ]
}}
```

Keep the plan simple and linear. Use only the available skills. Each task should be one skill invocation."""
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/unit/core/test_missions.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/atlas/core/missions.py tests/unit/core/test_missions.py
git commit -m "feat: add Mission Planner with JSON and numbered-list plan parsing"
```

---

## Task 19: Core — Execution Loop

**Files:**
- Create: `src/atlas/core/loop.py`
- Test: `tests/integration/test_execution_loop.py`

This is the first **integration test** — it wires Core, Skills, Environment, Control, and Memory together.

**Step 1: Write the failing test**

```python
# tests/integration/test_execution_loop.py
from pathlib import Path

import pytest

from atlas.control.approval import ApprovalWorkflow
from atlas.control.audit import AuditLogger
from atlas.control.policy import PolicyEngine
from atlas.contracts.types import AutonomyLevel
from atlas.core.loop import ExecutionLoop
from atlas.core.missions import Mission
from atlas.core.tasks import Task
from atlas.env.facade import EnvironmentFacade
from atlas.env.filesystem import FilesystemProvider
from atlas.env.process import ProcessProvider
from atlas.memory.episodic import EpisodicMemoryStore
from atlas.memory.store import DatabaseStore
from atlas.memory.working import WorkingMemoryStore
from atlas.skills.registry import SkillRegistry
from atlas.skills.runtime import InvocationRuntime
from atlas.skills.seed import register_seed_skills


@pytest.fixture
async def loop(tmp_path: Path, tmp_workspace: Path):
    db = DatabaseStore(str(tmp_path / "test.db"))
    await db.initialize()

    fs = FilesystemProvider(workspace=str(tmp_workspace))
    proc = ProcessProvider()
    env = EnvironmentFacade(filesystem=fs, process=proc, claude=None)

    registry = SkillRegistry()
    register_seed_skills(registry, fs, proc)
    runtime = InvocationRuntime(registry)

    policy = PolicyEngine(autonomy_level=AutonomyLevel.ACT_WITHIN_BOUNDS)
    audit = AuditLogger(db_path=str(tmp_path / "audit.db"))
    await audit.initialize()
    approval = ApprovalWorkflow(auto_approve=True)

    working = WorkingMemoryStore()
    episodic = EpisodicMemoryStore(db)

    loop = ExecutionLoop(
        registry=registry,
        runtime=runtime,
        environment=env,
        policy=policy,
        audit=audit,
        approval=approval,
        working_memory=working,
        episodic_memory=episodic,
    )
    yield loop
    await audit.close()
    await db.close()


async def test_execute_file_read_task(loop: ExecutionLoop, tmp_workspace: Path):
    mission = Mission(goal_text="read a file")
    task = Task(
        description="Read main.py",
        skill_id="file.read",
        input_params={"path": str(tmp_workspace / "src" / "main.py")},
    )
    mission.tasks = [task]

    result = await loop.execute_mission(mission)
    assert result.status.value == "completed"
    assert len(result.tasks) == 1
    assert result.tasks[0].status.value == "completed"
    assert "hello" in result.tasks[0].result["content"]


async def test_execute_multiple_tasks(loop: ExecutionLoop, tmp_workspace: Path):
    mission = Mission(goal_text="read and search")
    mission.tasks = [
        Task(
            description="Read main.py",
            skill_id="file.read",
            input_params={"path": str(tmp_workspace / "src" / "main.py")},
        ),
        Task(
            description="Search for Python files",
            skill_id="file.search",
            input_params={"root": str(tmp_workspace), "pattern": "**/*.py"},
        ),
    ]

    result = await loop.execute_mission(mission)
    assert result.status.value == "completed"
    assert all(t.status.value == "completed" for t in result.tasks)


async def test_execute_records_episode(loop: ExecutionLoop, tmp_workspace: Path):
    mission = Mission(goal_text="test episode recording")
    mission.tasks = [
        Task(
            description="Read main.py",
            skill_id="file.read",
            input_params={"path": str(tmp_workspace / "src" / "main.py")},
        ),
    ]
    await loop.execute_mission(mission)

    episodes = await loop._episodic.query_recent(limit=1)
    assert len(episodes) == 1
    assert "test episode recording" in episodes[0].trigger
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_execution_loop.py -v`
Expected: FAIL — module not found

**Step 3: Write implementation**

```python
# src/atlas/core/loop.py
"""Execution Loop — the central plan-act-observe-reflect cycle."""

from __future__ import annotations

import logging

from atlas.contracts.types import (
    ApprovalRequest,
    ApprovalResult,
    AuditEntry,
    Episode,
    EpisodeType,
    ExecutionContext,
    MissionStatus,
    PolicyDecision,
    ProposedAction,
    TaskStatus,
)
from atlas.control.approval import ApprovalWorkflow
from atlas.control.audit import AuditLogger
from atlas.control.policy import PolicyEngine
from atlas.core.missions import Mission
from atlas.core.tasks import Task
from atlas.env.facade import EnvironmentFacade
from atlas.memory.episodic import EpisodicMemoryStore
from atlas.memory.working import WorkingMemoryStore
from atlas.skills.registry import SkillRegistry
from atlas.skills.runtime import InvocationRuntime

logger = logging.getLogger(__name__)


class ExecutionLoop:
    """Sequentially executes a mission's tasks, checking permissions and logging."""

    def __init__(
        self,
        registry: SkillRegistry,
        runtime: InvocationRuntime,
        environment: EnvironmentFacade,
        policy: PolicyEngine,
        audit: AuditLogger,
        approval: ApprovalWorkflow,
        working_memory: WorkingMemoryStore,
        episodic_memory: EpisodicMemoryStore,
    ):
        self._registry = registry
        self._runtime = runtime
        self._env = environment
        self._policy = policy
        self._audit = audit
        self._approval = approval
        self._working = working_memory
        self._episodic = episodic_memory

    async def execute_mission(self, mission: Mission) -> Mission:
        mission.status = MissionStatus.ACTIVE
        ctx = ExecutionContext.new(mission_id=mission.mission_id)
        actions_log: list[dict] = []

        total = len(mission.tasks)
        for i, task in enumerate(mission.tasks):
            step_ctx = ExecutionContext(
                correlation_id=ctx.correlation_id,
                mission_id=mission.mission_id,
                task_id=task.task_id,
            )
            logger.info(f"[task {i+1}/{total}] {task.description}")

            success = await self._execute_task(task, step_ctx)
            actions_log.append({
                "task_id": task.task_id,
                "description": task.description,
                "skill_id": task.skill_id,
                "status": task.status.value,
            })

            if not success:
                mission.status = MissionStatus.FAILED
                break
        else:
            mission.status = MissionStatus.COMPLETED

        # Record episode
        await self._episodic.record(Episode(
            episode_type=EpisodeType.TASK_EXECUTION,
            trigger=mission.goal_text,
            plan="; ".join(t.description for t in mission.tasks),
            actions=actions_log,
            outcome=mission.status.value,
            mission_id=mission.mission_id,
            correlation_id=ctx.correlation_id,
        ))

        return mission

    async def _execute_task(self, task: Task, ctx: ExecutionContext) -> bool:
        if not task.skill_id:
            task.status = TaskStatus.FAILED
            task.error = "No skill_id assigned to task"
            return False

        # Get skill info for risk assessment
        try:
            skill_desc = self._registry.get(task.skill_id)
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)
            return False

        # Check permission
        action = ProposedAction(
            action_type=f"skill_invoke:{task.skill_id}",
            domain="core",
            description=task.description,
            params=task.input_params,
            risk_level=skill_desc.risk_level,
            skill_id=task.skill_id,
        )
        decision = self._policy.evaluate(action)

        if decision == PolicyDecision.DENY:
            task.status = TaskStatus.FAILED
            task.error = "Permission denied by policy"
            await self._log_audit(task, ctx, decision, "denied")
            return False

        if decision == PolicyDecision.REQUIRE_APPROVAL:
            request = ApprovalRequest(
                action=action,
                reasoning=f"Task: {task.description}",
            )
            approval = await self._approval.request_approval(request)
            if approval != ApprovalResult.APPROVED:
                task.status = TaskStatus.FAILED
                task.error = "Approval denied by user"
                await self._log_audit(task, ctx, decision, "denied")
                return False

        # Execute skill
        task.status = TaskStatus.EXECUTING
        result = await self._runtime.invoke(task.skill_id, task.input_params, ctx)

        if result.status == "success":
            task.status = TaskStatus.COMPLETED
            task.result = result.output
            await self._log_audit(task, ctx, decision, "success")
            return True
        else:
            task.status = TaskStatus.FAILED
            task.error = result.error
            await self._log_audit(task, ctx, decision, "failure")
            return False

    async def _log_audit(
        self, task: Task, ctx: ExecutionContext,
        decision: PolicyDecision, outcome: str,
    ) -> None:
        await self._audit.log(AuditEntry(
            correlation_id=ctx.correlation_id,
            actor="core.execution_loop",
            action_type=f"skill_invoke:{task.skill_id}",
            action_details=task.input_params,
            policy_decision=decision,
            outcome=outcome,
            mission_id=ctx.mission_id,
            task_id=ctx.task_id,
        ))
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/integration/test_execution_loop.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add src/atlas/core/loop.py tests/integration/test_execution_loop.py
git commit -m "feat: add Execution Loop with permission checks, audit logging, and episode recording"
```

---

## Task 20: CLI — `atlas goal` Command

**Files:**
- Create: `src/atlas/cli.py`
- Modify: `src/atlas/__main__.py` (already created)

**Step 1: Write implementation**

```python
# src/atlas/cli.py
"""ATLAS CLI — command-line interface for the agent."""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

import click
import yaml

from atlas.contracts.types import AutonomyLevel
from atlas.control.approval import ApprovalWorkflow
from atlas.control.audit import AuditLogger
from atlas.control.policy import PolicyEngine
from atlas.core.loop import ExecutionLoop
from atlas.core.missions import Mission, parse_task_plan, PLANNING_PROMPT_TEMPLATE
from atlas.env.claude import ClaudeCodeBridge
from atlas.env.facade import EnvironmentFacade
from atlas.env.filesystem import FilesystemProvider
from atlas.env.process import ProcessProvider
from atlas.memory.episodic import EpisodicMemoryStore
from atlas.memory.store import DatabaseStore
from atlas.memory.working import WorkingMemoryStore
from atlas.skills.registry import SkillRegistry
from atlas.skills.runtime import InvocationRuntime
from atlas.skills.seed import register_seed_skills


def _ensure_data_dir() -> Path:
    data_dir = Path.home() / ".atlas"
    data_dir.mkdir(exist_ok=True)
    (data_dir / "config").mkdir(exist_ok=True)
    (data_dir / "data").mkdir(exist_ok=True)
    (data_dir / "logs").mkdir(exist_ok=True)
    return data_dir


def _setup_logging(data_dir: Path, level: str = "INFO") -> None:
    log_file = data_dir / "logs" / "atlas.log"
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format='{"timestamp":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stderr),
        ],
    )


@click.group()
def main():
    """ATLAS — Autonomous Tool-Learning Agent System"""
    pass


@main.command()
@click.argument("goal_text")
@click.option("--autonomy", type=click.Choice(["observe", "suggest", "act"]), default="act",
              help="Autonomy level")
@click.option("--auto-approve", is_flag=True, help="Auto-approve all actions (for testing)")
def goal(goal_text: str, autonomy: str, auto_approve: bool):
    """Submit a goal for ATLAS to accomplish."""
    asyncio.run(_run_goal(goal_text, autonomy, auto_approve))


async def _run_goal(goal_text: str, autonomy: str, auto_approve: bool) -> None:
    data_dir = _ensure_data_dir()
    _setup_logging(data_dir)
    logger = logging.getLogger("atlas.cli")

    # Map CLI autonomy flag
    autonomy_map = {
        "observe": AutonomyLevel.OBSERVE,
        "suggest": AutonomyLevel.SUGGEST,
        "act": AutonomyLevel.ACT_WITHIN_BOUNDS,
    }
    autonomy_level = autonomy_map[autonomy]

    # Initialize components
    db = DatabaseStore(str(data_dir / "data" / "atlas.db"))
    await db.initialize()

    fs = FilesystemProvider(workspace=str(Path.cwd()))
    proc = ProcessProvider()
    claude = ClaudeCodeBridge()
    env = EnvironmentFacade(filesystem=fs, process=proc, claude=claude)

    registry = SkillRegistry()
    register_seed_skills(registry, fs, proc)
    runtime = InvocationRuntime(registry)

    policy = PolicyEngine(autonomy_level=autonomy_level)
    audit = AuditLogger(db_path=str(data_dir / "data" / "atlas.db"))
    await audit.initialize()
    approval = ApprovalWorkflow(auto_approve=auto_approve)

    working = WorkingMemoryStore()
    episodic = EpisodicMemoryStore(db)

    loop = ExecutionLoop(
        registry=registry,
        runtime=runtime,
        environment=env,
        policy=policy,
        audit=audit,
        approval=approval,
        working_memory=working,
        episodic_memory=episodic,
    )

    # Plan the mission
    click.echo(f"[planning] Decomposing goal: {goal_text}")

    skills_desc = "\n".join(
        f"- {s.skill_id}: {s.description}" for s in registry.list_all()
    )
    env_state = str(env.get_state())

    prompt = PLANNING_PROMPT_TEMPLATE.format(
        goal=goal_text, skills=skills_desc, env_state=env_state
    )

    try:
        response = await env.claude_oneshot(prompt)
        tasks = parse_task_plan(response.content)
    except Exception as e:
        click.echo(f"[error] Planning failed: {e}", err=True)
        await db.close()
        sys.exit(1)

    if not tasks:
        click.echo("[error] Could not parse a task plan from Claude's response.", err=True)
        await db.close()
        sys.exit(1)

    mission = Mission(goal_text=goal_text, tasks=tasks)
    click.echo(f"[planned] {len(tasks)} tasks")

    # Execute
    result = await loop.execute_mission(mission)

    # Report
    completed = sum(1 for t in result.tasks if t.status.value == "completed")
    total = len(result.tasks)
    if result.status.value == "completed":
        click.echo(f"[complete] {completed}/{total} tasks succeeded. Episode recorded.")
    else:
        click.echo(f"[failed] {completed}/{total} tasks succeeded. Mission failed.", err=True)
        for t in result.tasks:
            if t.error:
                click.echo(f"  - {t.description}: {t.error}", err=True)

    await db.close()


@main.command()
def status():
    """Show ATLAS status."""
    click.echo("ATLAS is not running as a daemon. Use 'atlas goal' to execute tasks.")


if __name__ == "__main__":
    main()
```

**Step 2: Install and verify CLI**

Run: `pip install -e ".[dev]"`
Run: `atlas --help`
Expected: Shows help with `goal` and `status` commands

Run: `atlas status`
Expected: `ATLAS is not running as a daemon. Use 'atlas goal' to execute tasks.`

**Step 3: Commit**

```bash
git add src/atlas/cli.py
git commit -m "feat: add CLI with 'atlas goal' and 'atlas status' commands"
```

---

## Task 21: E2E Test — Full CLI Smoke Test (Mocked Claude)

**Files:**
- Create: `tests/integration/test_e2e.py`

**Step 1: Write the test**

```python
# tests/integration/test_e2e.py
"""End-to-end test: full goal execution with mocked Claude Code Bridge."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from atlas.contracts.types import AutonomyLevel, ClaudeResponse
from atlas.control.approval import ApprovalWorkflow
from atlas.control.audit import AuditLogger
from atlas.control.policy import PolicyEngine
from atlas.core.loop import ExecutionLoop
from atlas.core.missions import Mission, parse_task_plan
from atlas.env.facade import EnvironmentFacade
from atlas.env.filesystem import FilesystemProvider
from atlas.env.process import ProcessProvider
from atlas.memory.episodic import EpisodicMemoryStore
from atlas.memory.store import DatabaseStore
from atlas.memory.working import WorkingMemoryStore
from atlas.skills.registry import SkillRegistry
from atlas.skills.runtime import InvocationRuntime
from atlas.skills.seed import register_seed_skills


@pytest.fixture
async def e2e_env(tmp_path: Path, tmp_workspace: Path):
    """Full ATLAS environment with mocked Claude."""
    # Write a file to read in the workspace
    (tmp_workspace / "src" / "app.py").write_text(
        "def greet():\n    print('hello world')\n"
    )

    db = DatabaseStore(str(tmp_path / "e2e.db"))
    await db.initialize()

    fs = FilesystemProvider(workspace=str(tmp_workspace))
    proc = ProcessProvider()
    env = EnvironmentFacade(filesystem=fs, process=proc, claude=None)

    registry = SkillRegistry()
    register_seed_skills(registry, fs, proc)
    runtime = InvocationRuntime(registry)

    policy = PolicyEngine(autonomy_level=AutonomyLevel.ACT_WITHIN_BOUNDS)
    audit = AuditLogger(db_path=str(tmp_path / "audit.db"))
    await audit.initialize()
    approval = ApprovalWorkflow(auto_approve=True)

    working = WorkingMemoryStore()
    episodic = EpisodicMemoryStore(db)

    loop = ExecutionLoop(
        registry=registry,
        runtime=runtime,
        environment=env,
        policy=policy,
        audit=audit,
        approval=approval,
        working_memory=working,
        episodic_memory=episodic,
    )

    yield {
        "loop": loop,
        "workspace": tmp_workspace,
        "db": db,
        "audit": audit,
        "episodic": episodic,
    }

    await audit.close()
    await db.close()


async def test_full_goal_execution(e2e_env: dict):
    """Simulate: user submits goal, Claude returns plan, ATLAS executes it."""
    workspace = e2e_env["workspace"]
    loop = e2e_env["loop"]

    # Simulate Claude's planning response
    plan_json = json.dumps({
        "tasks": [
            {
                "description": "Read the application source",
                "skill": "file.read",
                "params": {"path": str(workspace / "src" / "app.py")},
            },
            {
                "description": "Write updated file with logging",
                "skill": "file.write",
                "params": {
                    "path": str(workspace / "src" / "app.py"),
                    "content": "import logging\n\ndef greet():\n    logging.info('hello world')\n",
                },
            },
        ]
    })

    tasks = parse_task_plan(plan_json)
    mission = Mission(goal_text="Add logging to app.py", tasks=tasks)

    result = await loop.execute_mission(mission)

    # Verify mission completed
    assert result.status.value == "completed"
    assert all(t.status.value == "completed" for t in result.tasks)

    # Verify file was actually modified
    content = (workspace / "src" / "app.py").read_text()
    assert "import logging" in content

    # Verify episode was recorded
    episodes = await e2e_env["episodic"].query_recent(limit=1)
    assert len(episodes) == 1
    assert "Add logging" in episodes[0].trigger

    # Verify audit entries were created
    audit_entries = await e2e_env["audit"].query(limit=10)
    assert len(audit_entries) >= 2  # one per task
```

**Step 2: Run test to verify it passes**

Run: `pytest tests/integration/test_e2e.py -v`
Expected: All PASS

**Step 3: Commit**

```bash
git add tests/integration/test_e2e.py
git commit -m "feat: add E2E test proving full goal execution with mocked Claude"
```

---

## Task 22: Run Full Test Suite & Final Commit

**Step 1: Run all tests**

Run: `pytest tests/ -v`
Expected: All tests PASS

**Step 2: Run linter**

Run: `ruff check src/ tests/`
Expected: No errors (or fix any that appear)

**Step 3: Final commit if any fixes were needed**

```bash
git add -A
git commit -m "fix: resolve linting issues from full suite run"
```

**Step 4: Verify the CLI entry point works**

Run: `atlas --help`
Expected: Shows help text

Run: `atlas status`
Expected: `ATLAS is not running as a daemon. Use 'atlas goal' to execute tasks.`
