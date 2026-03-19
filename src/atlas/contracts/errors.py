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
    """Anthropic API call failed (rate limit, timeout, parse error)."""


class ClaudeCodeUnavailableError(FatalError):
    """Anthropic API is not reachable (missing or invalid API key)."""


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
