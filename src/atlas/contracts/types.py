"""Shared data models, enums, and value types used across all ATLAS domains."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
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
    def new(
        cls, mission_id: str | None = None, task_id: str | None = None
    ) -> ExecutionContext:
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
    domain: str  # e.g., "skills", "core"
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
    actor: str = ""  # domain/component
    action_type: str = ""
    action_details: dict[str, Any] = field(default_factory=dict)
    policy_decision: PolicyDecision | None = None
    outcome: str = ""  # "success", "failure", "denied", "timeout"
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

    purpose: str  # "planning", "execution", "reflection"
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
    status: str = "success"  # "success", "failure", "timeout", "cancelled"
    output: Any = None
    error: str | None = None
    execution_time_ms: int = 0


@dataclass
class EnvironmentAction:
    """An action to be executed in the environment."""

    action_id: str = field(default_factory=new_id)
    action_type: str = (
        ""  # "filesystem_read", "filesystem_write", "process_execute", etc.
    )
    provider: str = ""  # "filesystem", "process", "claude_code"
    params: dict[str, Any] = field(default_factory=dict)
    timeout: int = 30


@dataclass
class ActionResult:
    """Result of an environment action."""

    action_id: str = ""
    status: str = "success"  # "success", "failure", "timeout", "denied"
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


# --- Phase 2: Observation, Daemon, Procedural Memory ---


class EventType(str, Enum):
    FILESYSTEM = "filesystem"
    SCHEDULED = "scheduled"
    GOAL = "goal"
    WEBHOOK = "webhook"


@dataclass
class ObservationEvent:
    event_type: EventType
    source: str
    payload: dict[str, Any] = field(default_factory=dict)
    event_id: str = field(default_factory=new_id)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    priority: int = 5
    correlation_id: str = field(default_factory=new_id)


@dataclass
class Procedure:
    name: str
    description: str
    trigger_pattern: str
    steps: list[dict[str, Any]]
    procedure_id: str = field(default_factory=new_id)
    success_rate: float = 0.0
    use_count: int = 0
    last_used: str = ""
    created_from: str = ""


@dataclass
class DaemonCommand:
    command: str
    payload: dict[str, Any] = field(default_factory=dict)
    command_id: str = field(default_factory=new_id)


@dataclass
class DaemonResponse:
    command_id: str
    status: str
    payload: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


# --- Phase 3: Trust Escalation ---


@dataclass
class TrustRecord:
    """Per-skill trust tracking for autonomy escalation/demotion."""

    skill_id: str
    successes: int = 0
    failures: int = 0
    consecutive_successes: int = 0
    total_invocations: int = 0
    autonomy_override: AutonomyLevel | None = None
    last_outcome: str = ""
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    recent_outcomes: str = "[]"


# --- Phase 3: Approval Rules ---


@dataclass
class ApprovalRule:
    """Persistent rule for auto-approving or auto-denying actions."""

    rule_id: str = field(default_factory=new_id)
    rule_type: str = "standing"
    match_skill: str = "*"
    match_risk: str = "*"
    match_path: str | None = None
    decision: str = "allow"
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    expires_at: str | None = None
    description: str = ""


# --- Phase 3: Trust Recommendations ---


@dataclass
class TrustRecommendation:
    """Recommendation to escalate or demote a skill's autonomy level."""

    recommendation_id: str = field(default_factory=new_id)
    skill_id: str = ""
    current_level: str = ""
    recommended_level: str = ""
    direction: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"
    mission_id: str | None = None
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    resolved_at: str | None = None
