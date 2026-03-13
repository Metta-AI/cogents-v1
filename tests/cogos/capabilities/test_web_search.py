"""Tests for WebSearchCapability."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from cogos.capabilities.web_search import (
    SearchResult,
    WebSearchCapability,
)


@pytest.fixture
def repo():
    return MagicMock()


@pytest.fixture
def pid():
    return uuid4()


class TestScoping:
    def test_unscoped_allows_any_search(self, repo, pid):
        cap = WebSearchCapability(repo, pid)
        cap._check("search")  # should not raise

    def test_scoped_ops_denies_unpermitted(self, repo, pid):
        cap = WebSearchCapability(repo, pid).scope(ops=["search"])
        with pytest.raises(PermissionError):
            cap._check("other_op")

    def test_narrow_intersects_ops(self, repo, pid):
        cap = WebSearchCapability(repo, pid)
        s1 = cap.scope(ops=["search"])
        s2 = s1.scope(ops=["search"])
        assert s2._scope["ops"] == ["search"]

    def test_narrow_intersects_domains(self, repo, pid):
        cap = WebSearchCapability(repo, pid)
        s1 = cap.scope(domains=["github.com", "linkedin.com"])
        s2 = s1.scope(domains=["github.com", "twitter.com"])
        assert s2._scope["domains"] == ["github.com"]

    def test_narrow_budget_takes_min(self, repo, pid):
        cap = WebSearchCapability(repo, pid)
        s1 = cap.scope(query_budget=100)
        s2 = s1.scope(query_budget=50)
        assert s2._scope["query_budget"] == 50


class TestSearch:
    @patch("cogos.capabilities.web_search.fetch_secret", return_value="test-api-key")
    def test_search_returns_results(self, mock_secret, repo, pid):
        cap = WebSearchCapability(repo, pid)
        mock_response = {
            "results": [
                {
                    "title": "Result 1",
                    "url": "https://example.com/1",
                    "content": "Snippet 1",
                    "score": 0.95,
                },
            ]
        }
        with patch("cogos.capabilities.web_search.TavilyClient") as MockTavily:
            mock_client = MagicMock()
            mock_client.search.return_value = mock_response
            MockTavily.return_value = mock_client

            results = cap.search("test query", limit=5)
            assert len(results) == 1
            assert isinstance(results[0], SearchResult)
            assert results[0].title == "Result 1"
            mock_client.search.assert_called_once_with(
                query="test query",
                max_results=5,
                include_domains=None,
            )

    @patch("cogos.capabilities.web_search.fetch_secret", return_value="test-api-key")
    def test_search_with_domain_scope(self, mock_secret, repo, pid):
        cap = WebSearchCapability(repo, pid).scope(domains=["github.com"])
        with patch("cogos.capabilities.web_search.TavilyClient") as MockTavily:
            mock_client = MagicMock()
            mock_client.search.return_value = {"results": []}
            MockTavily.return_value = mock_client

            cap.search("test query")
            mock_client.search.assert_called_once_with(
                query="test query",
                max_results=5,
                include_domains=["github.com"],
            )

    @patch("cogos.capabilities.web_search.fetch_secret", side_effect=RuntimeError("no key"))
    def test_search_returns_error_on_missing_key(self, mock_secret, repo, pid):
        cap = WebSearchCapability(repo, pid)
        result = cap.search("test")
        assert hasattr(result, "error")
        assert "no key" in result.error
