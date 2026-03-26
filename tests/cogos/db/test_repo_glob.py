from __future__ import annotations

import pytest

from cogos.db.sqlite_repository import SqliteBackend
from cogos.db.unified_repository import UnifiedRepository


@pytest.fixture
def repo(tmp_path):
    return UnifiedRepository(SqliteBackend(str(tmp_path)))


class TestGlobFiles:
    def test_glob_returns_matching_keys(self, repo):
        repo.execute(
            "INSERT INTO cogos_file (id, key) VALUES (:id, :key)",
            {"id": "f1", "key": "src/config.yaml"},
        )
        results = repo.glob_files("src/*.yaml")
        assert results == ["src/config.yaml"]

    def test_glob_no_matches(self, repo):
        results = repo.glob_files("nonexistent/**")
        assert results == []


class TestGlobToRegex:
    def test_star(self):
        assert UnifiedRepository._glob_to_regex("src/*.py") == "^src/[^/]*\\.py$"

    def test_double_star(self):
        assert UnifiedRepository._glob_to_regex("src/**/*.py") == "^src/.*[^/]*\\.py$"

    def test_question_mark(self):
        assert UnifiedRepository._glob_to_regex("file?.txt") == "^file[^/]\\.txt$"

    def test_plain(self):
        assert UnifiedRepository._glob_to_regex("exact/path.md") == "^exact/path\\.md$"
