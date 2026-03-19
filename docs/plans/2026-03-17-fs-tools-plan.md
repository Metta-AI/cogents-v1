# FS Tools Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Extend `dir` and `file` capabilities with grep, glob, tree, line-sliced reads, and surgical edit — making cogware as powerful as Claude Code's shell tools.

**Architecture:** Add new methods to existing `DirCapability` and `FileCapability` classes. Add two repo-layer queries (content regex search, key glob match). Update registry schemas and cogware include file.

**Tech Stack:** Python, Postgres regex (`~`), RDS Data API, pydantic models

---

### Task 1: Add `GrepMatch` and `GrepResult` pydantic models

**Files:**
- Modify: `src/cogos/capabilities/files.py`

**Step 1: Add models to files.py**

Add after the existing `FileError` class:

```python
class GrepMatch(BaseModel):
    line: int
    text: str
    before: list[str] = []
    after: list[str] = []


class GrepResult(BaseModel):
    key: str
    matches: list[GrepMatch]
```

**Step 2: Verify import works**

Run: `python -c "from cogos.capabilities.files import GrepMatch, GrepResult; print('ok')"`
Expected: `ok`

**Step 3: Commit**

```bash
git add src/cogos/capabilities/files.py
git commit -m "feat: add GrepMatch and GrepResult models for dir.grep"
```

---

### Task 2: Add `grep_files` repo-layer query

**Files:**
- Modify: `src/cogos/db/repository.py`

**Step 1: Write the failing test**

Create: `tests/cogos/db/test_repo_grep.py`

```python
"""Tests for repo grep_files and glob_files queries."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from cogos.db.repository import Repository


@pytest.fixture
def repo():
    """Create a Repository with mocked RDS client."""
    with patch.object(Repository, "__init__", lambda self: None):
        r = Repository.__new__(Repository)
        r._client = MagicMock()
        r._resource_arn = "arn:test"
        r._secret_arn = "arn:secret"
        r._database = "testdb"
        return r


class TestGrepFiles:
    def test_grep_returns_matching_keys_and_content(self, repo):
        repo._client.execute_statement.return_value = {
            "columnMetadata": [
                {"name": "key"},
                {"name": "content"},
            ],
            "records": [
                [
                    {"stringValue": "src/main.py"},
                    {"stringValue": "line1\nTODO fix this\nline3"},
                ],
            ],
        }
        results = repo.grep_files("TODO", prefix="src/", limit=100)
        assert len(results) == 1
        assert results[0][0] == "src/main.py"
        assert "TODO" in results[0][1]

    def test_grep_no_matches(self, repo):
        repo._client.execute_statement.return_value = {"records": []}
        results = repo.grep_files("nonexistent")
        assert results == []

    def test_grep_with_prefix(self, repo):
        repo._client.execute_statement.return_value = {"records": []}
        repo.grep_files("pattern", prefix="myprefix/")
        sql = repo._client.execute_statement.call_args[1]["sql"] if "sql" in repo._client.execute_statement.call_args[1] else repo._client.execute_statement.call_args[0][0]
        # Just verify it was called — SQL content tested via integration
        assert repo._client.execute_statement.called
```

Run: `pytest tests/cogos/db/test_repo_grep.py -v`
Expected: FAIL — `AttributeError: 'Repository' object has no attribute 'grep_files'`

**Step 2: Implement `grep_files` in repository.py**

Add after the `list_files` method (~line 832):

```python
def grep_files(
    self, pattern: str, *, prefix: str | None = None, limit: int = 100
) -> list[tuple[str, str]]:
    """Search active file versions by regex pattern. Returns (key, content) tuples."""
    if prefix:
        response = self._execute(
            """SELECT f.key, fv.content
               FROM cogos_file f
               JOIN cogos_file_version fv ON fv.file_id = f.id
               WHERE fv.is_active = true
                 AND f.key LIKE :prefix
                 AND fv.content ~ :pattern
               ORDER BY f.key
               LIMIT :limit""",
            [
                self._param("prefix", prefix + "%"),
                self._param("pattern", pattern),
                self._param("limit", limit),
            ],
        )
    else:
        response = self._execute(
            """SELECT f.key, fv.content
               FROM cogos_file f
               JOIN cogos_file_version fv ON fv.file_id = f.id
               WHERE fv.is_active = true
                 AND fv.content ~ :pattern
               ORDER BY f.key
               LIMIT :limit""",
            [
                self._param("pattern", pattern),
                self._param("limit", limit),
            ],
        )
    rows = self._rows_to_dicts(response)
    return [(r["key"], r["content"]) for r in rows]
```

**Step 3: Run tests**

Run: `pytest tests/cogos/db/test_repo_grep.py -v`
Expected: PASS

**Step 4: Commit**

```bash
git add src/cogos/db/repository.py tests/cogos/db/test_repo_grep.py
git commit -m "feat: add grep_files repo query for regex content search"
```

---

### Task 3: Add `glob_files` repo-layer query

**Files:**
- Modify: `src/cogos/db/repository.py`
- Modify: `tests/cogos/db/test_repo_grep.py`

**Step 1: Write the failing test**

Append to `tests/cogos/db/test_repo_grep.py`:

```python
class TestGlobFiles:
    def test_glob_returns_matching_keys(self, repo):
        repo._client.execute_statement.return_value = {
            "columnMetadata": [{"name": "key"}],
            "records": [[{"stringValue": "src/config.yaml"}]],
        }
        results = repo.glob_files("src/*.yaml")
        assert results == ["src/config.yaml"]

    def test_glob_no_matches(self, repo):
        repo._client.execute_statement.return_value = {"records": []}
        results = repo.glob_files("nonexistent/**")
        assert results == []
```

Run: `pytest tests/cogos/db/test_repo_grep.py::TestGlobFiles -v`
Expected: FAIL — `AttributeError: 'Repository' object has no attribute 'glob_files'`

**Step 2: Implement `glob_files` in repository.py**

Add after `grep_files`:

```python
@staticmethod
def _glob_to_regex(pattern: str) -> str:
    """Convert a glob pattern to a Postgres regex.

    * = one path segment (no slashes)
    ** = any depth (including slashes)
    ? = single character
    """
    import re

    parts: list[str] = []
    i = 0
    while i < len(pattern):
        c = pattern[i]
        if c == "*" and i + 1 < len(pattern) and pattern[i + 1] == "*":
            parts.append(".*")
            i += 2
            if i < len(pattern) and pattern[i] == "/":
                i += 1  # skip trailing slash after **
        elif c == "*":
            parts.append("[^/]*")
            i += 1
        elif c == "?":
            parts.append("[^/]")
            i += 1
        else:
            parts.append(re.escape(c))
            i += 1
    return "^" + "".join(parts) + "$"

def glob_files(
    self, pattern: str, *, prefix: str | None = None, limit: int = 200
) -> list[str]:
    """Match file keys by glob pattern. Returns list of matching keys."""
    regex = self._glob_to_regex(pattern)
    if prefix:
        response = self._execute(
            """SELECT f.key FROM cogos_file f
               WHERE f.key ~ :regex
                 AND f.key LIKE :prefix
               ORDER BY f.key
               LIMIT :limit""",
            [
                self._param("regex", regex),
                self._param("prefix", prefix + "%"),
                self._param("limit", limit),
            ],
        )
    else:
        response = self._execute(
            """SELECT f.key FROM cogos_file f
               WHERE f.key ~ :regex
               ORDER BY f.key
               LIMIT :limit""",
            [
                self._param("regex", regex),
                self._param("limit", limit),
            ],
        )
    return [r["key"] for r in self._rows_to_dicts(response)]
```

**Step 3: Run tests**

Run: `pytest tests/cogos/db/test_repo_grep.py -v`
Expected: PASS

**Step 4: Add tests for `_glob_to_regex`**

Append to test file:

```python
class TestGlobToRegex:
    def test_star(self):
        assert Repository._glob_to_regex("src/*.py") == "^src/[^/]*\\.py$"

    def test_double_star(self):
        assert Repository._glob_to_regex("src/**/*.py") == "^src/.*[^/]*\\.py$"

    def test_question_mark(self):
        assert Repository._glob_to_regex("file?.txt") == "^file[^/]\\.txt$"

    def test_plain(self):
        assert Repository._glob_to_regex("exact/path.md") == "^exact/path\\.md$"
```

Run: `pytest tests/cogos/db/test_repo_grep.py::TestGlobToRegex -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/cogos/db/repository.py tests/cogos/db/test_repo_grep.py
git commit -m "feat: add glob_files repo query with glob-to-regex translation"
```

---

### Task 4: Add `grep`, `glob`, `tree` to `DirCapability`

**Files:**
- Modify: `src/cogos/capabilities/file_cap.py`

**Step 1: Write failing tests**

Append to `tests/cogos/capabilities/test_file_caps.py`:

```python
from cogos.capabilities.files import GrepMatch, GrepResult


class TestDirGrepGlobTree:
    def test_grep_returns_results(self, repo, pid):
        cap = DirCapability(repo, pid)
        scoped = cap.scope(prefix="/workspace/")
        # Mock repo.grep_files to return one file with matching content
        repo.grep_files.return_value = [
            ("/workspace/main.py", "line1\n# TODO fix\nline3")
        ]
        results = scoped.grep("TODO")
        assert len(results) == 1
        assert results[0].key == "/workspace/main.py"
        assert results[0].matches[0].line == 1
        assert "TODO" in results[0].matches[0].text

    def test_grep_respects_prefix_scope(self, repo, pid):
        cap = DirCapability(repo, pid)
        scoped = cap.scope(prefix="/workspace/")
        repo.grep_files.return_value = []
        scoped.grep("pattern")
        repo.grep_files.assert_called_once_with(
            "pattern", prefix="/workspace/", limit=100
        )

    def test_grep_with_context(self, repo, pid):
        cap = DirCapability(repo, pid)
        repo.grep_files.return_value = [
            ("file.py", "a\nb\nTODO fix\nd\ne")
        ]
        results = cap.grep("TODO", context=1)
        m = results[0].matches[0]
        assert m.before == ["b"]
        assert m.after == ["d"]

    def test_grep_denied_without_op(self, repo, pid):
        cap = DirCapability(repo, pid)
        scoped = cap.scope(ops={"list"})
        with pytest.raises(PermissionError):
            scoped.grep("pattern")

    def test_glob_returns_keys(self, repo, pid):
        cap = DirCapability(repo, pid)
        scoped = cap.scope(prefix="/workspace/")
        repo.glob_files.return_value = ["/workspace/config.yaml"]
        results = scoped.glob("*.yaml")
        assert len(results) == 1
        assert results[0].key == "/workspace/config.yaml"

    def test_glob_respects_prefix_scope(self, repo, pid):
        cap = DirCapability(repo, pid)
        scoped = cap.scope(prefix="/workspace/")
        repo.glob_files.return_value = []
        scoped.glob("**/*.py")
        repo.glob_files.assert_called_once_with(
            "**/*.py", prefix="/workspace/", limit=50
        )

    def test_glob_denied_without_op(self, repo, pid):
        cap = DirCapability(repo, pid)
        scoped = cap.scope(ops={"list"})
        with pytest.raises(PermissionError):
            scoped.glob("*.py")

    def test_tree_returns_string(self, repo, pid):
        cap = DirCapability(repo, pid)
        scoped = cap.scope(prefix="/ws/")
        with patch("cogos.capabilities.file_cap.FileStore") as mock_cls:
            store = mock_cls.return_value
            from cogos.db.models import File
            store.list_files.return_value = [
                File(key="/ws/a.py"),
                File(key="/ws/sub/b.py"),
                File(key="/ws/sub/c.py"),
            ]
            result = scoped.tree()
            assert "a.py" in result
            assert "sub/" in result

    def test_tree_denied_without_op(self, repo, pid):
        cap = DirCapability(repo, pid)
        scoped = cap.scope(ops={"list"})
        with pytest.raises(PermissionError):
            scoped.tree()
```

Run: `pytest tests/cogos/capabilities/test_file_caps.py::TestDirGrepGlobTree -v`
Expected: FAIL — `AttributeError: 'DirCapability' object has no attribute 'grep'`

**Step 2: Implement grep, glob, tree on DirCapability**

In `src/cogos/capabilities/file_cap.py`, update `DirCapability`:

1. Update `ALL_OPS`:
```python
ALL_OPS = {"list", "get", "grep", "glob", "tree"}
```

2. Add imports at top:
```python
from cogos.capabilities.files import (
    FileContent,
    FileError,
    FileSearchResult,
    FileWriteResult,
    GrepMatch,
    GrepResult,
)
```

3. Add methods to `DirCapability` class:

```python
def grep(
    self,
    pattern: str,
    prefix: str | None = None,
    limit: int = 20,
    context: int = 0,
) -> list[GrepResult]:
    """Regex search across file contents. Returns keys + matching lines."""
    self._check("grep")
    effective_prefix = self._full_key(prefix) if prefix else self._scope.get("prefix")
    raw = self.repo.grep_files(pattern, prefix=effective_prefix, limit=100)

    import re

    results: list[GrepResult] = []
    total_matches = 0
    for key, content in raw:
        if total_matches >= limit:
            break
        lines = content.split("\n")
        matches: list[GrepMatch] = []
        for i, line in enumerate(lines):
            if total_matches >= limit:
                break
            if re.search(pattern, line):
                before = lines[max(0, i - context) : i] if context > 0 else []
                after = lines[i + 1 : i + 1 + context] if context > 0 else []
                matches.append(GrepMatch(line=i, text=line, before=before, after=after))
                total_matches += 1
        if matches:
            results.append(GrepResult(key=key, matches=matches))
    return results

def glob(
    self,
    pattern: str,
    limit: int = 50,
) -> list[FileSearchResult]:
    """Match file keys by glob pattern."""
    self._check("glob")
    prefix = self._scope.get("prefix")
    keys = self.repo.glob_files(pattern, prefix=prefix, limit=limit)
    return [FileSearchResult(id="", key=k) for k in keys]

def tree(
    self,
    prefix: str | None = None,
    depth: int = 3,
) -> str:
    """Compact directory tree of file keys."""
    self._check("tree")
    effective_prefix = self._full_key(prefix) if prefix else self._scope.get("prefix")

    store = FileStore(self.repo)
    files = store.list_files(prefix=effective_prefix, limit=500)

    # Build tree structure
    tree_dict: dict = {}
    strip = len(effective_prefix.rstrip("/") + "/") if effective_prefix else 0
    for f in files:
        rel = f.key[strip:]
        parts = rel.split("/")
        node = tree_dict
        for p in parts[:depth]:
            node = node.setdefault(p, {})

    # Render
    lines: list[str] = []
    root_label = effective_prefix.rstrip("/") + "/" if effective_prefix else "/"
    lines.append(root_label)

    def _render(node: dict, indent: str) -> None:
        items = sorted(node.items())
        for i, (name, children) in enumerate(items):
            is_last = i == len(items) - 1
            connector = "└── " if is_last else "├── "
            suffix = "/" if children else ""
            lines.append(f"{indent}{connector}{name}{suffix}")
            if children:
                extension = "    " if is_last else "│   "
                _render(children, indent + extension)

    _render(tree_dict, "")
    return "\n".join(lines)
```

4. Update `__repr__`:
```python
def __repr__(self) -> str:
    prefix = self._scope.get("prefix", "")
    if prefix:
        return f"<Dir '{prefix}' list() get(key) grep(pattern) glob(pattern) tree()>"
    return "<DirCapability list() get(key) grep(pattern) glob(pattern) tree()>"
```

**Step 3: Run tests**

Run: `pytest tests/cogos/capabilities/test_file_caps.py -v`
Expected: PASS

**Step 4: Commit**

```bash
git add src/cogos/capabilities/file_cap.py tests/cogos/capabilities/test_file_caps.py
git commit -m "feat: add grep, glob, tree to DirCapability"
```

---

### Task 5: Add line-sliced `read`, `head`, `tail` to `FileCapability`

**Files:**
- Modify: `src/cogos/capabilities/file_cap.py`
- Modify: `src/cogos/capabilities/files.py`

**Step 1: Add `total_lines` to `FileContent`**

In `files.py`, add field:

```python
class FileContent(BaseModel):
    id: str
    key: str
    version: int
    content: str
    read_only: bool = False
    source: str = ""
    total_lines: int | None = None
```

**Step 2: Write failing tests**

Append to `tests/cogos/capabilities/test_file_caps.py`:

```python
from cogos.capabilities.files import FileContent
from cogos.db.models import File, FileVersion


class TestFileSlicedRead:
    def _setup_file(self, repo, key="test.py"):
        content = "\n".join(f"line {i}" for i in range(100))
        f = File(key=key)
        fv = FileVersion(file_id=f.id, version=1, content=content, source="agent", is_active=True)
        repo.get_active_file_version.return_value = fv
        return f, fv, content

    def test_read_with_offset_limit(self, repo, pid):
        cap = FileCapability(repo, pid)
        f, fv, content = self._setup_file(repo)
        with patch("cogos.capabilities.file_cap.FileStore") as mock_cls:
            mock_cls.return_value.get.return_value = f
            result = cap.read("test.py", offset=10, limit=5)
            assert isinstance(result, FileContent)
            assert result.total_lines == 100
            lines = result.content.split("\n")
            assert len(lines) == 5
            assert lines[0] == "line 10"

    def test_read_no_slice_includes_total_lines(self, repo, pid):
        cap = FileCapability(repo, pid)
        f, fv, content = self._setup_file(repo)
        with patch("cogos.capabilities.file_cap.FileStore") as mock_cls:
            mock_cls.return_value.get.return_value = f
            result = cap.read("test.py")
            assert result.total_lines == 100

    def test_head(self, repo, pid):
        cap = FileCapability(repo, pid)
        f, fv, content = self._setup_file(repo)
        with patch("cogos.capabilities.file_cap.FileStore") as mock_cls:
            mock_cls.return_value.get.return_value = f
            result = cap.head("test.py", n=3)
            lines = result.content.split("\n")
            assert len(lines) == 3
            assert lines[0] == "line 0"

    def test_tail(self, repo, pid):
        cap = FileCapability(repo, pid)
        f, fv, content = self._setup_file(repo)
        with patch("cogos.capabilities.file_cap.FileStore") as mock_cls:
            mock_cls.return_value.get.return_value = f
            result = cap.tail("test.py", n=3)
            lines = result.content.split("\n")
            assert len(lines) == 3
            assert lines[-1] == "line 99"

    def test_read_negative_offset(self, repo, pid):
        """Negative offset reads from end, like tail."""
        cap = FileCapability(repo, pid)
        f, fv, content = self._setup_file(repo)
        with patch("cogos.capabilities.file_cap.FileStore") as mock_cls:
            mock_cls.return_value.get.return_value = f
            result = cap.read("test.py", offset=-5)
            lines = result.content.split("\n")
            assert len(lines) == 5
            assert lines[-1] == "line 99"
```

Run: `pytest tests/cogos/capabilities/test_file_caps.py::TestFileSlicedRead -v`
Expected: FAIL — `TypeError: read() got an unexpected keyword argument 'offset'`

**Step 3: Implement sliced read, head, tail**

Update `FileCapability.read` in `file_cap.py`:

```python
def read(
    self,
    key: str | None = None,
    offset: int | None = None,
    limit: int | None = None,
) -> FileContent | FileError:
    k = self._resolve_key(key)
    self._check("read", key=k)

    store = FileStore(self.repo)
    f = store.get(k)
    if f is None:
        return FileError(error=f"file '{k}' not found")

    fv = self.repo.get_active_file_version(f.id)
    if fv is None:
        return FileError(error=f"no active version for '{k}'")

    content = fv.content
    lines = content.split("\n")
    total_lines = len(lines)

    if offset is not None or limit is not None:
        start = offset or 0
        if start < 0:
            start = max(0, total_lines + start)
        end = start + limit if limit is not None else total_lines
        content = "\n".join(lines[start:end])

    return FileContent(
        id=str(f.id),
        key=f.key,
        version=fv.version,
        content=content,
        read_only=fv.read_only,
        source=fv.source,
        total_lines=total_lines,
    )

def head(self, key: str | None = None, n: int = 20) -> FileContent | FileError:
    """First n lines of a file."""
    return self.read(key, offset=0, limit=n)

def tail(self, key: str | None = None, n: int = 20) -> FileContent | FileError:
    """Last n lines of a file."""
    return self.read(key, offset=-n)
```

**Step 4: Run tests**

Run: `pytest tests/cogos/capabilities/test_file_caps.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/cogos/capabilities/file_cap.py src/cogos/capabilities/files.py tests/cogos/capabilities/test_file_caps.py
git commit -m "feat: add line-sliced read, head, tail to FileCapability"
```

---

### Task 6: Add `edit` to `FileCapability`

**Files:**
- Modify: `src/cogos/capabilities/file_cap.py`

**Step 1: Write failing tests**

Append to `tests/cogos/capabilities/test_file_caps.py`:

```python
class TestFileEdit:
    def _setup_file(self, repo, key="test.py", content="hello world\nfoo bar\nbaz"):
        f = File(key=key)
        fv = FileVersion(file_id=f.id, version=1, content=content, source="agent", is_active=True)
        repo.get_active_file_version.return_value = fv
        return f, fv

    def test_edit_replaces_unique_match(self, repo, pid):
        cap = FileCapability(repo, pid)
        f, fv = self._setup_file(repo)
        with patch("cogos.capabilities.file_cap.FileStore") as mock_cls:
            store = mock_cls.return_value
            store.get.return_value = f
            store.upsert.return_value = fv
            result = cap.edit("test.py", "foo bar", "replaced")
            store.upsert.assert_called_once()
            new_content = store.upsert.call_args[0][1]
            assert "replaced" in new_content
            assert "foo bar" not in new_content

    def test_edit_fails_if_not_found(self, repo, pid):
        cap = FileCapability(repo, pid)
        f, fv = self._setup_file(repo)
        with patch("cogos.capabilities.file_cap.FileStore") as mock_cls:
            store = mock_cls.return_value
            store.get.return_value = f
            result = cap.edit("test.py", "nonexistent", "replaced")
            assert isinstance(result, FileError)
            assert "not found" in result.error

    def test_edit_fails_if_not_unique(self, repo, pid):
        cap = FileCapability(repo, pid)
        f, fv = self._setup_file(repo, content="aaa\naaa\nbbb")
        with patch("cogos.capabilities.file_cap.FileStore") as mock_cls:
            store = mock_cls.return_value
            store.get.return_value = f
            result = cap.edit("test.py", "aaa", "replaced")
            assert isinstance(result, FileError)
            assert "not unique" in result.error

    def test_edit_replace_all(self, repo, pid):
        cap = FileCapability(repo, pid)
        f, fv = self._setup_file(repo, content="aaa\naaa\nbbb")
        with patch("cogos.capabilities.file_cap.FileStore") as mock_cls:
            store = mock_cls.return_value
            store.get.return_value = f
            store.upsert.return_value = fv
            result = cap.edit("test.py", "aaa", "xxx", replace_all=True)
            new_content = store.upsert.call_args[0][1]
            assert new_content == "xxx\nxxx\nbbb"

    def test_edit_replace_all_zero_matches(self, repo, pid):
        cap = FileCapability(repo, pid)
        f, fv = self._setup_file(repo)
        with patch("cogos.capabilities.file_cap.FileStore") as mock_cls:
            store = mock_cls.return_value
            store.get.return_value = f
            result = cap.edit("test.py", "nonexistent", "xxx", replace_all=True)
            assert isinstance(result, FileError)

    def test_edit_denied_without_op(self, repo, pid):
        cap = FileCapability(repo, pid)
        scoped = cap.scope(key="test.py", ops={"read"})
        with pytest.raises(PermissionError):
            scoped.edit("test.py", "old", "new")
```

Run: `pytest tests/cogos/capabilities/test_file_caps.py::TestFileEdit -v`
Expected: FAIL — `AttributeError: 'FileCapability' object has no attribute 'edit'`

**Step 2: Implement edit**

Update `FileCapability` in `file_cap.py`:

1. Update `ALL_OPS`:
```python
ALL_OPS = {"read", "write", "append", "edit"}
```

2. Add method:
```python
def edit(
    self,
    key: str | None = None,
    old: str = "",
    new: str = "",
    replace_all: bool = False,
    source: str = "agent",
) -> FileWriteResult | FileError:
    """Surgical string replacement. Fails if old not found or not unique (unless replace_all)."""
    k = self._resolve_key(key)
    self._check("edit", key=k)

    store = FileStore(self.repo)
    f = store.get(k)
    if f is None:
        return FileError(error=f"file '{k}' not found")

    fv = self.repo.get_active_file_version(f.id)
    if fv is None:
        return FileError(error=f"no active version for '{k}'")

    content = fv.content
    count = content.count(old)

    if count == 0:
        return FileError(error=f"old string not found in '{k}'")

    if not replace_all and count > 1:
        return FileError(error=f"old string not unique in '{k}' ({count} occurrences)")

    if replace_all:
        new_content = content.replace(old, new)
    else:
        new_content = content.replace(old, new, 1)

    return self._do_write(k, new_content, source)
```

3. Update `__repr__`:
```python
def __repr__(self) -> str:
    k = self._scope.get("key", "")
    if k:
        return f"<File '{k}' read() write() append() edit()>"
    return "<FileCapability read(key) write(content, key) append(content, key) edit(key, old, new)>"
```

**Step 3: Run tests**

Run: `pytest tests/cogos/capabilities/test_file_caps.py -v`
Expected: PASS

**Step 4: Commit**

```bash
git add src/cogos/capabilities/file_cap.py tests/cogos/capabilities/test_file_caps.py
git commit -m "feat: add edit method to FileCapability with replace_all support"
```

---

### Task 7: Update registry schemas

**Files:**
- Modify: `src/cogos/capabilities/registry.py`

**Step 1: Update `dir` registry entry**

Update the `dir` entry's `instructions` and `schema` to include grep, glob, tree. Replace the existing `dir` entry (lines 71-112):

Instructions:
```python
"instructions": (
    "Use dir to access files under a directory prefix.\n"
    "- dir.list(prefix?) — list files\n"
    "- f = dir.get(key) — get a file handle\n"
    "- dir.grep(pattern, prefix?, limit=20, context=0) — regex search file contents\n"
    "- dir.glob(pattern, limit=50) — match file keys by glob\n"
    "- dir.tree(prefix?, depth=3) — compact directory tree\n"
    "- f.read(offset?, limit?) — read file (line-sliced)\n"
    "- f.write(content) — overwrite file\n"
    "- f.append(content) — append to file\n"
    "- f.edit(old, new, replace_all=False) — surgical string replacement"
),
```

Add to schema dict:
```python
"grep": {
    "input": {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Regex pattern to search"},
            "prefix": {"type": "string", "description": "Narrow search prefix"},
            "limit": {"type": "integer", "default": 20},
            "context": {"type": "integer", "default": 0, "description": "Lines before/after match"},
        },
        "required": ["pattern"],
    },
    "output": {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "key": {"type": "string"},
                "matches": {"type": "array", "items": {
                    "type": "object",
                    "properties": {
                        "line": {"type": "integer"},
                        "text": {"type": "string"},
                        "before": {"type": "array", "items": {"type": "string"}},
                        "after": {"type": "array", "items": {"type": "string"}},
                    },
                }},
            },
        },
    },
},
"glob": {
    "input": {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Glob pattern (* = segment, ** = any depth, ? = char)"},
            "limit": {"type": "integer", "default": 50},
        },
        "required": ["pattern"],
    },
    "output": {
        "type": "array",
        "items": {"type": "object", "properties": {"key": {"type": "string"}}},
    },
},
"tree": {
    "input": {
        "type": "object",
        "properties": {
            "prefix": {"type": "string", "description": "Subtree prefix"},
            "depth": {"type": "integer", "default": 3},
        },
    },
    "output": {"type": "string", "description": "Tree-formatted string"},
},
```

**Step 2: Update `file` registry entry**

Update the `file` entry (the `FilesCapability` one) — update `read` schema to include offset/limit, add `edit` schema:

Update `read` input:
```python
"read": {
    "input": {
        "type": "object",
        "properties": {
            "key": {"type": "string", "description": "File key"},
            "offset": {"type": "integer", "description": "Start line (0-indexed, negative from end)"},
            "limit": {"type": "integer", "description": "Number of lines to return"},
        },
        "required": ["key"],
    },
    "output": {
        "type": "object",
        "properties": {
            "id": {"type": "string"}, "key": {"type": "string"},
            "version": {"type": "integer"}, "content": {"type": "string"},
            "read_only": {"type": "boolean"}, "source": {"type": "string"},
            "total_lines": {"type": "integer"},
        },
    },
},
```

Add `edit` schema:
```python
"edit": {
    "input": {
        "type": "object",
        "properties": {
            "key": {"type": "string", "description": "File key"},
            "old": {"type": "string", "description": "Exact string to find"},
            "new": {"type": "string", "description": "Replacement string"},
            "replace_all": {"type": "boolean", "default": False},
        },
        "required": ["key", "old", "new"],
    },
    "output": {
        "type": "object",
        "properties": {
            "id": {"type": "string"}, "key": {"type": "string"},
            "version": {"type": "integer"}, "created": {"type": "boolean"},
            "changed": {"type": "boolean"},
        },
    },
},
```

**Step 3: Verify registry loads**

Run: `python -c "from cogos.capabilities.registry import BUILTIN_CAPABILITIES; print(len(BUILTIN_CAPABILITIES), 'capabilities')"`
Expected: prints count without error

**Step 4: Commit**

```bash
git add src/cogos/capabilities/registry.py
git commit -m "feat: update registry schemas for grep, glob, tree, edit, sliced read"
```

---

### Task 8: Update cogware instructions include

**Files:**
- Modify: `images/cogent-v1/cogos/includes/files.md`

**Step 1: Replace contents with updated API reference**

```markdown
# Files API

Three capabilities for file access: `file` (single key), `dir` (prefix/directory), `file_version` (history).

Use exact file keys, including suffixes like `.md` and `.json`.

## Finding files

```python
# Regex search across file contents
results = dir.grep("TODO", prefix="src/", limit=20, context=1)
for r in results:
    for m in r.matches:
        print(f"{r.key}:{m.line}: {m.text}")

# Match file keys by glob pattern
files = dir.glob("**/*.py")

# Compact directory tree
print(dir.tree(depth=3))

# List files by prefix
entries = dir.list("cogos/docs/")
```

## Reading files

```python
# Full read
doc = dir.get("main.py").read()
print(doc.content, doc.total_lines)

# Line-sliced read (0-indexed)
chunk = dir.get("main.py").read(offset=50, limit=20)

# First/last N lines
top = dir.get("main.py").head(n=10)
bottom = dir.get("main.py").tail(n=10)

# Check file size without loading
info = dir.get("big.py").read(limit=1)
print(info.total_lines)
```

## Editing files

```python
# Surgical replacement (fails if old not found or not unique)
dir.get("main.py").edit(old="old_name", new="new_name")

# Replace all occurrences
dir.get("main.py").edit(old="old_name", new="new_name", replace_all=True)

# Overwrite entire file
dir.get("config.md").write("new content")

# Append to file
dir.get("log.md").append("\nnew entry")
```

## Patterns

- Explore: `dir.tree()` → `dir.grep(pattern)` → `file.read(offset, limit)` → `file.edit(old, new)`
- Bulk rename: `for r in dir.grep("old"): dir.get(r.key).edit(old="old", new="new", replace_all=True)`
- Large file: `dir.get(key).read(limit=1)` to check `total_lines`, then slice

## Return types

- `FileContent` — id, key, version, content, read_only, source, total_lines
- `FileWriteResult` — id, key, version, created, changed
- `FileSearchResult` — id, key
- `GrepResult` — key, matches (list of GrepMatch)
- `GrepMatch` — line, text, before, after
- `FileError` — error (string)

Check for errors: `if isinstance(result, FileError): print(result.error)`
```

**Step 2: Commit**

```bash
git add images/cogent-v1/cogos/includes/files.md
git commit -m "feat: update cogware files include with grep, glob, tree, edit, sliced read"
```

---

### Task 9: Run full test suite and fix

**Step 1: Run all file-related tests**

Run: `pytest tests/cogos/capabilities/test_file_caps.py tests/cogos/db/test_repo_grep.py tests/cogos/capabilities/test_files_scoping.py -v`
Expected: ALL PASS

**Step 2: Run broader test suite to catch regressions**

Run: `pytest tests/ -x -q`
Expected: No unexpected failures

**Step 3: Fix any issues found**

If tests fail, fix and re-run.

**Step 4: Final commit**

```bash
git commit -m "test: verify full test suite passes with fs-tools changes"
```
