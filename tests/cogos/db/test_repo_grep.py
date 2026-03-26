from __future__ import annotations

import pytest

from cogos.db.sqlite_repository import SqliteBackend
from cogos.db.unified_repository import UnifiedRepository


@pytest.fixture
def repo(tmp_path):
    r = UnifiedRepository(SqliteBackend(str(tmp_path)))
    r.execute(
        "INSERT INTO cogos_file (id, key) VALUES (:id, :key)",
        {"id": "f1", "key": "src/main.py"},
    )
    r.execute(
        "INSERT INTO cogos_file_version (id, file_id, version, content, is_active) "
        "VALUES (:id, :fid, 1, :content, 1)",
        {"id": "fv1", "fid": "f1", "content": "line1\nTODO fix this\nline3"},
    )
    return r


class TestGrepFiles:
    def test_grep_returns_matching_keys_and_content(self, repo):
        results = repo.grep_files("TODO", prefix="src/", limit=100)
        assert len(results) == 1
        assert results[0][0] == "src/main.py"
        assert "TODO" in results[0][1]

    def test_grep_no_matches(self, repo):
        results = repo.grep_files("nonexistent")
        assert results == []

    def test_grep_with_prefix(self, repo):
        results = repo.grep_files("TODO", prefix="src/")
        assert len(results) == 1
