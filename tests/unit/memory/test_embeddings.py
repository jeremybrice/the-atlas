from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from atlas.memory.embeddings import EmbeddingProvider


@pytest.fixture
def mock_voyage_client():
    client = MagicMock()
    # voyage client's embed method returns an object with .embeddings attribute
    result = MagicMock()
    result.embeddings = [[0.1, 0.2, 0.3] * 341 + [0.1]]  # 1024 dims
    client.embed = MagicMock(return_value=result)
    return client


@pytest.fixture
def provider(mock_voyage_client):
    with patch("atlas.memory.embeddings.voyageai") as mock_voyageai:
        mock_voyageai.Client.return_value = mock_voyage_client
        p = EmbeddingProvider(api_key="test-key", model="voyage-3-lite")
        yield p


def test_embed_returns_numpy_array(provider, mock_voyage_client):
    result = provider.embed("hello world")
    assert isinstance(result, np.ndarray)
    assert result.dtype == np.float32
    mock_voyage_client.embed.assert_called_once_with(
        ["hello world"], model="voyage-3-lite", input_type="document",
    )


def test_embed_batch_returns_list_of_arrays(provider, mock_voyage_client):
    mock_result = MagicMock()
    mock_result.embeddings = [
        [0.1, 0.2, 0.3] * 341 + [0.1],
        [0.4, 0.5, 0.6] * 341 + [0.4],
    ]
    mock_voyage_client.embed.return_value = mock_result

    results = provider.embed_batch(["text one", "text two"])
    assert len(results) == 2
    assert all(isinstance(r, np.ndarray) for r in results)
    assert all(r.dtype == np.float32 for r in results)


def test_embed_query_uses_query_input_type(provider, mock_voyage_client):
    provider.embed_query("search for something")
    mock_voyage_client.embed.assert_called_once_with(
        ["search for something"], model="voyage-3-lite", input_type="query",
    )


def test_compose_episode_text(provider):
    from atlas.contracts.types import Episode
    episode = Episode(
        trigger="deploy the app",
        plan="run deploy script",
        outcome="deployment succeeded",
        lessons=["always check CI first"],
    )
    text = provider.compose_episode_text(episode)
    assert "deploy the app" in text
    assert "run deploy script" in text
    assert "deployment succeeded" in text
    assert "always check CI first" in text


def test_embed_returns_none_on_api_error(provider, mock_voyage_client):
    mock_voyage_client.embed.side_effect = Exception("API timeout")
    result = provider.embed("hello")
    assert result is None


def test_embed_batch_returns_empty_on_api_error(provider, mock_voyage_client):
    mock_voyage_client.embed.side_effect = Exception("API timeout")
    results = provider.embed_batch(["text"])
    assert results == []
