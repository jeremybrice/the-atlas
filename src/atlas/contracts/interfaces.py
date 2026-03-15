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


class ConnectorInterface(ABC):
    """Consumed by Integration Layer. External service connector contract."""

    @property
    @abstractmethod
    def service_name(self) -> str: ...

    @abstractmethod
    async def authenticate(self, ctx: ExecutionContext | None = None) -> None: ...

    @abstractmethod
    async def handle_event(self, event_type: str, payload: dict[str, Any], ctx: ExecutionContext | None = None) -> dict[str, Any]: ...

    @abstractmethod
    async def execute_action(self, action: str, params: dict[str, Any], ctx: ExecutionContext | None = None) -> dict[str, Any]: ...
