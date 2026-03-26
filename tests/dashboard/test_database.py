"""Tests for the dashboard/cogos.api db module."""

from unittest.mock import MagicMock, patch

import pytest

import cogos.api.db as db_mod


@pytest.fixture(autouse=True)
def _reset_repo_cache(monkeypatch):
    """Clear the lru_cache before and after each test."""
    db_mod.get_repo.cache_clear()
    monkeypatch.delenv("USE_LOCAL_DB", raising=False)
    yield
    db_mod.get_repo.cache_clear()


def test_get_repo_returns_repository():
    """get_repo creates a UnifiedRepository via RdsBackend.create()."""
    mock_backend = MagicMock()
    with patch.dict("sys.modules", {"boto3": MagicMock()}), \
         patch("cogos.db.repository.RdsBackend") as MockBackend, \
         patch("cogos.db.unified_repository.UnifiedRepository") as MockRepo:
        MockBackend.create.return_value = mock_backend
        mock_repo = MagicMock()
        MockRepo.return_value = mock_repo
        result = db_mod.get_repo()
        assert result is mock_repo
        MockBackend.create.assert_called_once()


def test_get_repo_raises_on_missing_credentials():
    """get_repo raises when credentials are missing."""
    with patch.dict("sys.modules", {"boto3": MagicMock()}), \
         patch("cogos.db.repository.RdsBackend") as MockBackend:
        MockBackend.create.side_effect = ValueError("Missing credentials")
        with pytest.raises(ValueError, match="Missing credentials"):
            db_mod.get_repo()
