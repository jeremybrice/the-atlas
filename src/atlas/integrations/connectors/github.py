"""GitHub Connector — handles GitHub API interactions and webhook events."""

import logging
from typing import Any, Callable, NoReturn

import httpx

from atlas.contracts.errors import ConnectorError, CredentialError
from atlas.contracts.types import EventType, ExecutionContext, ObservationEvent
from atlas.integrations.connector import ConnectorABC

logger = logging.getLogger(__name__)


class GitHubConnector(ConnectorABC):
    """Connector for GitHub API and webhook events."""

    def __init__(
        self,
        token: str,
        owner: str = "",
        repo: str = "",
        api_base: str = "https://api.github.com",
        rate_limit_rpm: int = 60,
    ):
        super().__init__(service_name="github", rate_limit_rpm=rate_limit_rpm)
        self._token = token
        self._owner = owner
        self._repo = repo
        self._api_base = api_base
        self._headers: dict[str, str] = {}

    @staticmethod
    def _log_ctx(ctx: ExecutionContext | None) -> str:
        """Format correlation_id for log messages."""
        if ctx:
            return f"[{ctx.correlation_id}] "
        return ""

    async def authenticate(self, ctx: ExecutionContext | None = None) -> None:
        self._headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        logger.info(
            "%sGitHub connector authenticated for %s/%s",
            self._log_ctx(ctx),
            self._owner,
            self._repo,
        )

    async def handle_event(
        self,
        event_type: str,
        payload: dict[str, Any],
        ctx: ExecutionContext | None = None,
    ) -> dict[str, Any]:
        logger.info(
            "%sGitHub event: %s action=%s",
            self._log_ctx(ctx),
            event_type,
            payload.get("action", ""),
        )
        return {"handled": True, "event_type": event_type}

    async def execute_action(
        self, action: str, params: dict[str, Any], ctx: ExecutionContext | None = None
    ) -> dict[str, Any]:
        await self._check_rate_limit()

        match action:
            case "comment":
                return await self._post_comment(params)
            case "create_issue":
                return await self._create_issue(params)
            case "list_pulls":
                return await self._list_pulls(params)
            case _:
                raise ConnectorError(
                    f"Unsupported GitHub action: {action}", max_retries=0
                )

    def get_event_parser(self) -> Callable[[str, dict], ObservationEvent]:
        """Return an EventBridge-compatible parser for GitHub webhooks."""

        def parser(event_type: str, payload: dict[str, Any]) -> ObservationEvent:
            return ObservationEvent(
                event_type=EventType.WEBHOOK,
                source="github",
                payload={**payload, "github_event": event_type},
                priority=self._event_priority(event_type, payload),
            )

        return parser

    def _raise_for_status(self, exc: httpx.HTTPStatusError) -> NoReturn:
        status = exc.response.status_code
        if status in (401, 403):
            raise CredentialError(f"GitHub auth failed ({status}): {exc}", cause=exc)
        if status == 429:
            raise ConnectorError(
                f"GitHub rate limit exceeded: {exc}", max_retries=5, cause=exc
            )
        if status >= 500:
            raise ConnectorError(
                f"GitHub server error ({status}): {exc}", max_retries=3, cause=exc
            )
        raise ConnectorError(
            f"GitHub client error ({status}): {exc}", max_retries=1, cause=exc
        )

    async def _post_comment(self, params: dict) -> dict:
        issue_number = params.get("issue_number")
        body = params.get("body", "")
        url = f"{self._api_base}/repos/{self._owner}/{self._repo}/issues/{issue_number}/comments"
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    url, json={"body": body}, headers=self._headers
                )
                resp.raise_for_status()
                return {"status": "success", "data": resp.json()}
        except httpx.HTTPStatusError as e:
            self._raise_for_status(e)
        except httpx.HTTPError as e:
            raise ConnectorError(f"GitHub API request failed: {e}", cause=e)

    async def _create_issue(self, params: dict) -> dict:
        url = f"{self._api_base}/repos/{self._owner}/{self._repo}/issues"
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, json=params, headers=self._headers)
                resp.raise_for_status()
                return {"status": "success", "data": resp.json()}
        except httpx.HTTPStatusError as e:
            self._raise_for_status(e)
        except httpx.HTTPError as e:
            raise ConnectorError(f"GitHub API request failed: {e}", cause=e)

    async def _list_pulls(self, params: dict) -> dict:
        url = f"{self._api_base}/repos/{self._owner}/{self._repo}/pulls"
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, headers=self._headers, params=params)
                resp.raise_for_status()
                return {"status": "success", "data": resp.json()}
        except httpx.HTTPStatusError as e:
            self._raise_for_status(e)
        except httpx.HTTPError as e:
            raise ConnectorError(f"GitHub API request failed: {e}", cause=e)

    def _event_priority(self, event_type: str, payload: dict) -> int:
        """Assign priority based on event type. Lower number = higher priority."""
        match event_type:
            case "check_run" | "check_suite":
                if (
                    payload.get("action") == "completed"
                    and payload.get("conclusion") == "failure"
                ):
                    return 2  # CI failure = high priority
            case "pull_request":
                return 4
            case "issues":
                return 5
            case "push":
                return 6
        return 5  # default
