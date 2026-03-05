"""Tests for memory.store.MemoryStore."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from brain.db.models import MemoryRecord, MemoryScope
from memory.store import MemoryStore


@pytest.fixture
def repo():
    return MagicMock()


@pytest.fixture
def store(repo):
    return MemoryStore(repo)


def _rec(name: str, scope: MemoryScope = MemoryScope.COGENT) -> MemoryRecord:
    return MemoryRecord(scope=scope, name=name, content=f"content of {name}")


# ── resolve_keys ──


class TestResolveKeysAncestorInit:
    def test_ancestor_inits_are_fetched(self, store, repo):
        """Key /mind/channels/discord/api triggers ancestor /init lookups."""
        repo.get_memories_by_names.return_value = [
            _rec("/mind/init"),
            _rec("/mind/channels/init"),
            _rec("/mind/channels/discord/init"),
            _rec("/mind/channels/discord/api"),
        ]
        repo.query_memory_by_prefixes.return_value = []

        result = store.resolve_keys(["/mind/channels/discord/api"])

        fetched_names = set(repo.get_memories_by_names.call_args[0][0])
        assert "/mind/init" in fetched_names
        assert "/mind/channels/init" in fetched_names
        assert "/mind/channels/discord/init" in fetched_names
        assert "/mind/channels/discord/api" in fetched_names
        assert len(result) == 4


class TestResolveKeysChildInit:
    def test_child_init_records_included(self, store, repo):
        """Child /init records under the key prefix are included."""
        repo.get_memories_by_names.return_value = [_rec("/mind")]
        repo.query_memory_by_prefixes.return_value = [
            _rec("/mind/child/init"),
            _rec("/mind/child/notinit"),  # should be filtered out
        ]

        result = store.resolve_keys(["/mind"])

        names = [r.name for r in result]
        assert "/mind/child/init" in names
        assert "/mind/child/notinit" not in names


class TestResolveKeysCogentShadowsPolis:
    def test_cogent_overrides_polis(self, store, repo):
        """COGENT-scoped record shadows POLIS-scoped record with same name."""
        polis = _rec("/mind/init", MemoryScope.POLIS)
        polis.content = "polis"
        cogent = _rec("/mind/init", MemoryScope.COGENT)
        cogent.content = "cogent"
        # Repository returns polis first, then cogent overrides
        repo.get_memories_by_names.return_value = [polis, cogent]
        repo.query_memory_by_prefixes.return_value = []

        result = store.resolve_keys(["/mind/init"])

        matching = [r for r in result if r.name == "/mind/init"]
        assert len(matching) == 1
        assert matching[0].content == "cogent"


class TestResolveKeysEmpty:
    def test_empty_keys_returns_empty(self, store, repo):
        assert store.resolve_keys([]) == []
        repo.get_memories_by_names.assert_not_called()


class TestResolveKeysDedup:
    def test_shared_ancestors_not_duplicated(self, store, repo):
        """Two keys sharing /mind/init don't produce duplicate records."""
        init_rec = _rec("/mind/init")
        repo.get_memories_by_names.return_value = [
            init_rec,
            _rec("/mind/a"),
            _rec("/mind/b"),
        ]
        repo.query_memory_by_prefixes.return_value = []

        result = store.resolve_keys(["/mind/a", "/mind/b"])

        names = [r.name for r in result]
        assert names.count("/mind/init") == 1


class TestResolveKeysSortedByDepth:
    def test_results_sorted_root_to_leaf(self, store, repo):
        repo.get_memories_by_names.return_value = [
            _rec("/a/b/c/d"),
            _rec("/a/init"),
            _rec("/a/b/init"),
        ]
        repo.query_memory_by_prefixes.return_value = []

        result = store.resolve_keys(["/a/b/c/d"])

        names = [r.name for r in result]
        # Depth 2 (/a/init), depth 3 (/a/b/init, /a/b/c/init), depth 4 (/a/b/c/d)
        assert names[0] == "/a/init"
        assert names[-1] == "/a/b/c/d"
        # Shallower records come before deeper ones
        depths = [n.count("/") for n in names]
        assert depths == sorted(depths)


# ── upsert ──


class TestUpsert:
    def test_calls_insert_with_embedding(self, store, repo):
        embedding = [0.1, 0.2, 0.3]
        mock_bedrock = MagicMock()
        mock_bedrock.invoke_model.return_value = {
            "body": MagicMock(read=MagicMock(return_value=json.dumps({"embedding": embedding}).encode())),
        }
        store._bedrock = mock_bedrock

        result = store.upsert("/test", "hello world")

        mock_bedrock.invoke_model.assert_called_once()
        repo.insert_memory.assert_called_once()
        inserted = repo.insert_memory.call_args[0][0]
        assert inserted.embedding == embedding
        assert inserted.name == "/test"
        assert inserted.content == "hello world"

    def test_embedding_failure_is_non_fatal(self, store, repo):
        mock_bedrock = MagicMock()
        mock_bedrock.invoke_model.side_effect = RuntimeError("bedrock down")
        store._bedrock = mock_bedrock

        result = store.upsert("/test", "hello")

        repo.insert_memory.assert_called_once()
        inserted = repo.insert_memory.call_args[0][0]
        assert inserted.embedding is None

    def test_skip_embedding(self, store, repo):
        store._bedrock = MagicMock()

        result = store.upsert("/test", "hello", generate_embedding=False)

        store._bedrock.invoke_model.assert_not_called()
        repo.insert_memory.assert_called_once()


# ── list_memories ──


class TestListMemories:
    def test_delegates_to_repo(self, store, repo):
        repo.query_memory.return_value = [_rec("/a")]

        result = store.list_memories(prefix="/a", scope=MemoryScope.COGENT, limit=10)

        repo.query_memory.assert_called_once_with(scope=MemoryScope.COGENT, prefix="/a", limit=10)
        assert len(result) == 1


# ── get ──


class TestGet:
    def test_returns_record(self, store, repo):
        rec = _rec("/test")
        repo.query_memory.return_value = [rec]

        assert store.get("/test") == rec
        repo.query_memory.assert_called_once_with(name="/test", limit=1)

    def test_returns_none_when_not_found(self, store, repo):
        repo.query_memory.return_value = []

        assert store.get("/missing") is None


# ── delete_by_prefix ──


class TestDeleteByPrefix:
    def test_delegates_to_repo(self, store, repo):
        repo.delete_memories_by_prefix.return_value = 3

        result = store.delete_by_prefix("/old/", scope=MemoryScope.COGENT)

        repo.delete_memories_by_prefix.assert_called_once_with("/old/", MemoryScope.COGENT)
        assert result == 3
