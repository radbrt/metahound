import pytest
from unittest.mock import MagicMock, patch

from metadog.cli_functions import push_fn


def test_push_fn_success(backend_with_data, monkeypatch):
    """push_fn POSTs the payload and prints success."""
    monkeypatch.setenv("METADOG_BACKEND_URI", "sqlite:///:memory:")

    mock_response = MagicMock()
    mock_response.json.return_value = {"ingest_event_id": 1, "sources_processed": 1}
    mock_response.raise_for_status.return_value = None

    with patch("metadog.cli_functions.GenericBackendHandler", return_value=backend_with_data):
        with patch("requests.post", return_value=mock_response) as mock_post:
            push_fn(api_url="http://localhost:8000", api_token="test-token")

    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args
    assert call_kwargs[0][0] == "http://localhost:8000/api/v1/ingest"
    assert call_kwargs[1]["headers"]["Authorization"] == "Bearer test-token"


def test_push_fn_no_token_raises(monkeypatch):
    """push_fn raises ValueError when no token is available."""
    monkeypatch.delenv("METADOG_API_TOKEN", raising=False)

    with pytest.raises(ValueError, match="No API token"):
        push_fn(api_url="http://localhost:8000", api_token=None)


def test_push_fn_no_url_raises(monkeypatch):
    """push_fn raises ValueError when no API URL is available."""
    monkeypatch.setenv("METADOG_API_TOKEN", "some-token")
    monkeypatch.delenv("METADOG_API_URL", raising=False)

    with pytest.raises(ValueError, match="No API URL"):
        push_fn(api_url=None, api_token=None)
