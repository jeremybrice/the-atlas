import httpx
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from atlas.integrations.connectors.github import GitHubConnector
from atlas.contracts.errors import ConnectorError, CredentialError
from atlas.contracts.types import EventType, ObservationEvent


@pytest.fixture
def connector():
    return GitHubConnector(
        token="ghp_test_token_123", owner="test-owner", repo="test-repo"
    )


def test_service_name(connector):
    assert connector.service_name == "github"


def test_event_parser_returns_observation_event(connector):
    parser = connector.get_event_parser()
    event = parser("pull_request", {"action": "opened", "number": 42})
    assert isinstance(event, ObservationEvent)
    assert event.event_type == EventType.WEBHOOK
    assert event.source == "github"
    assert event.payload["action"] == "opened"
    assert event.payload["github_event"] == "pull_request"


def test_event_parser_push_event(connector):
    parser = connector.get_event_parser()
    event = parser("push", {"ref": "refs/heads/main", "commits": []})
    assert event.payload["github_event"] == "push"
    assert event.payload["ref"] == "refs/heads/main"


async def test_authenticate_sets_headers(connector):
    await connector.authenticate()
    assert connector._headers["Authorization"] == "Bearer ghp_test_token_123"
    assert "Accept" in connector._headers


async def test_execute_action_comment(connector):
    mock_response = MagicMock()
    mock_response.status_code = 201
    mock_response.json.return_value = {"id": 1, "body": "test comment"}
    mock_response.raise_for_status = MagicMock()

    with patch(
        "httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response
    ):
        result = await connector.execute_action(
            "comment",
            {
                "issue_number": 1,
                "body": "test comment",
            },
        )
    assert result["status"] == "success"


async def test_execute_action_unknown_raises(connector):
    with pytest.raises(ConnectorError, match="Unsupported"):
        await connector.execute_action("unknown_action", {})


async def test_post_comment_401_raises_credential_error(connector):
    await connector.authenticate()
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    exc = httpx.HTTPStatusError("Unauthorized", request=MagicMock(), response=mock_resp)
    mock_resp.raise_for_status.side_effect = exc
    with patch(
        "httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp
    ):
        with pytest.raises(CredentialError):
            await connector.execute_action(
                "comment", {"issue_number": 1, "body": "test"}
            )


async def test_post_comment_500_raises_connector_error(connector):
    await connector.authenticate()
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    exc = httpx.HTTPStatusError("Server Error", request=MagicMock(), response=mock_resp)
    mock_resp.raise_for_status.side_effect = exc
    with patch(
        "httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp
    ):
        with pytest.raises(ConnectorError):
            await connector.execute_action(
                "comment", {"issue_number": 1, "body": "test"}
            )


async def test_handle_event_pr_opened(connector):
    result = await connector.handle_event(
        "pull_request",
        {
            "action": "opened",
            "number": 42,
            "pull_request": {"title": "Fix bug"},
        },
    )
    assert result["handled"] is True
    assert result["event_type"] == "pull_request"


async def test_handle_event_logs_correlation_id(connector, caplog):
    """ExecutionContext.correlation_id should appear in log output."""
    from atlas.contracts.types import ExecutionContext

    ctx = ExecutionContext(
        correlation_id="test-corr-123", mission_id="m1", task_id="t1"
    )
    with caplog.at_level("INFO"):
        await connector.handle_event("push", {"ref": "main"}, ctx=ctx)
    assert "test-corr-123" in caplog.text


async def test_authenticate_logs_correlation_id(connector, caplog):
    from atlas.contracts.types import ExecutionContext

    ctx = ExecutionContext(
        correlation_id="auth-corr-456", mission_id="m1", task_id="t1"
    )
    with caplog.at_level("INFO"):
        await connector.authenticate(ctx=ctx)
    assert "auth-corr-456" in caplog.text
