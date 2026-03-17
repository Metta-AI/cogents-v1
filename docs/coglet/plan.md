# Coglet Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement the coglet abstraction — a long-lived code+tests container with a PR-style patch workflow, exposed as CogOS capabilities.

**Architecture:** Two capabilities (`CogletsCapability` for CRUD, `CogletCapability` for patch/inspect), a core module for metadata/test-running, and image integration via `add_coglet()`. All file storage uses the existing FileStore with `/coglets/{id}/` prefixes.

**Tech Stack:** Python, Pydantic models, CogOS Capability base class, FileStore, subprocess for test execution, LocalRepository for tests.

**Reference:** Read `docs/coglet/design.md` for the full design spec.

---

### Task 1: Coglet Core — Metadata Model

**Files:**
- Create: `src/cogos/coglet/__init__.py`
- Test: `tests/cogos/test_coglet.py`

**Step 1: Write the failing test**

```python
# tests/cogos/test_coglet.py
import json
from cogos.coglet import CogletMeta, PatchInfo


def test_coglet_meta_defaults():
    meta = CogletMeta(name="my-thing", test_command="pytest tests/")
    assert meta.name == "my-thing"
    assert meta.test_command == "pytest tests/"
    assert meta.version == 0
    assert meta.executor == "subprocess"
    assert meta.timeout_seconds == 60
    assert meta.patches == {}


def test_coglet_meta_roundtrip():
    meta = CogletMeta(name="my-thing", test_command="pytest tests/", version=3)
    data = json.loads(meta.model_dump_json())
    restored = CogletMeta(**data)
    assert restored.name == meta.name
    assert restored.version == meta.version


def test_patch_info_defaults():
    info = PatchInfo(base_version=2, test_passed=True, test_output="ok")
    assert info.base_version == 2
    assert info.test_passed is True
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/daveey/code/cogents/cogents.2 && python -m pytest tests/cogos/test_coglet.py -v -x`
Expected: FAIL — `ModuleNotFoundError: No module named 'cogos.coglet'`

**Step 3: Write minimal implementation**

```python
# src/cogos/coglet/__init__.py
"""Coglet core — metadata model and helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class PatchInfo(BaseModel):
    base_version: int
    test_passed: bool
    test_output: str = ""
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class LogEntry(BaseModel):
    action: str  # "proposed", "merged", "discarded", "tests_run"
    patch_id: str | None = None
    version: int | None = None
    test_passed: bool | None = None
    test_output: str = ""
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class CogletMeta(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    test_command: str
    executor: str = "subprocess"  # "subprocess" or "sandbox"
    timeout_seconds: int = 60
    version: int = 0
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    patches: dict[str, PatchInfo] = Field(default_factory=dict)
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/daveey/code/cogents/cogents.2 && python -m pytest tests/cogos/test_coglet.py -v -x`
Expected: PASS (3 tests)

**Step 5: Commit**

```bash
git add src/cogos/coglet/__init__.py tests/cogos/test_coglet.py
git commit -m "feat(coglet): add core metadata models"
```

---

### Task 2: Coglet Core — Test Runner

**Files:**
- Modify: `src/cogos/coglet/__init__.py`
- Test: `tests/cogos/test_coglet.py`

**Step 1: Write the failing test**

```python
# append to tests/cogos/test_coglet.py
import tempfile
import os
from cogos.coglet import run_tests


def test_run_tests_passing(tmp_path):
    # Write a simple test file
    (tmp_path / "test_ok.py").write_text("assert 1 + 1 == 2")
    result = run_tests(
        test_command="python test_ok.py",
        file_tree={"test_ok.py": "assert 1 + 1 == 2"},
        timeout_seconds=10,
    )
    assert result.passed is True
    assert result.exit_code == 0


def test_run_tests_failing(tmp_path):
    result = run_tests(
        test_command="python test_fail.py",
        file_tree={"test_fail.py": "assert 1 == 2, 'math is broken'"},
        timeout_seconds=10,
    )
    assert result.passed is False
    assert result.exit_code != 0
    assert "math is broken" in result.output


def test_run_tests_timeout():
    result = run_tests(
        test_command="python slow.py",
        file_tree={"slow.py": "import time; time.sleep(100)"},
        timeout_seconds=1,
    )
    assert result.passed is False
    assert "timeout" in result.output.lower() or result.exit_code != 0
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/daveey/code/cogents/cogents.2 && python -m pytest tests/cogos/test_coglet.py::test_run_tests_passing -v -x`
Expected: FAIL — `ImportError: cannot import name 'run_tests' from 'cogos.coglet'`

**Step 3: Write minimal implementation**

Add to `src/cogos/coglet/__init__.py`:

```python
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass
class TestResult:
    passed: bool
    exit_code: int
    output: str


def run_tests(
    test_command: str,
    file_tree: dict[str, str],
    timeout_seconds: int = 60,
) -> TestResult:
    """Materialize file_tree to a temp dir and run test_command."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        for path, content in file_tree.items():
            fp = tmp / path
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(content)

        try:
            proc = subprocess.run(
                test_command,
                shell=True,
                cwd=tmpdir,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
            output = (proc.stdout + proc.stderr).strip()
            return TestResult(
                passed=proc.returncode == 0,
                exit_code=proc.returncode,
                output=output,
            )
        except subprocess.TimeoutExpired as e:
            output = ""
            if e.stdout:
                output += e.stdout.decode() if isinstance(e.stdout, bytes) else e.stdout
            if e.stderr:
                output += e.stderr.decode() if isinstance(e.stderr, bytes) else e.stderr
            return TestResult(
                passed=False,
                exit_code=-1,
                output=(output + "\nTimeout after %ds" % timeout_seconds).strip(),
            )
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/daveey/code/cogents/cogents.2 && python -m pytest tests/cogos/test_coglet.py -v -x`
Expected: PASS (6 tests)

**Step 5: Commit**

```bash
git add src/cogos/coglet/__init__.py tests/cogos/test_coglet.py
git commit -m "feat(coglet): add test runner with subprocess execution"
```

---

### Task 3: Coglet Core — File Tree Helpers

Helpers to read/write coglet file trees from FileStore using the `/coglets/{id}/main/` and `/coglets/{id}/patches/{patch_id}/` prefixes.

**Files:**
- Modify: `src/cogos/coglet/__init__.py`
- Test: `tests/cogos/test_coglet.py`

**Step 1: Write the failing test**

```python
# append to tests/cogos/test_coglet.py
from cogos.db.local_repository import LocalRepository
from cogos.files.store import FileStore
from cogos.coglet import read_file_tree, write_file_tree


def test_write_and_read_file_tree(tmp_path):
    repo = LocalRepository(str(tmp_path))
    store = FileStore(repo)
    coglet_id = "test-coglet-123"
    files = {"src/main.py": "print('hello')", "tests/test_main.py": "assert True"}

    write_file_tree(store, coglet_id, "main", files)
    result = read_file_tree(store, coglet_id, "main")

    assert result == files


def test_read_file_tree_empty(tmp_path):
    repo = LocalRepository(str(tmp_path))
    store = FileStore(repo)
    result = read_file_tree(store, "nonexistent", "main")
    assert result == {}


def test_write_file_tree_patch_branch(tmp_path):
    repo = LocalRepository(str(tmp_path))
    store = FileStore(repo)
    coglet_id = "test-coglet-123"
    files = {"src/main.py": "v2"}
    patch_id = "patch-abc"

    write_file_tree(store, coglet_id, f"patches/{patch_id}", files)
    result = read_file_tree(store, coglet_id, f"patches/{patch_id}")

    assert result == files
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/daveey/code/cogents/cogents.2 && python -m pytest tests/cogos/test_coglet.py::test_write_and_read_file_tree -v -x`
Expected: FAIL — `ImportError: cannot import name 'read_file_tree'`

**Step 3: Write minimal implementation**

Add to `src/cogos/coglet/__init__.py`:

```python
from cogos.files.store import FileStore


def _prefix(coglet_id: str, branch: str) -> str:
    """Build the FileStore key prefix for a coglet branch."""
    return f"coglets/{coglet_id}/{branch}/"


def write_file_tree(store: FileStore, coglet_id: str, branch: str, files: dict[str, str]) -> None:
    """Write a dict of {path: content} to the FileStore under the coglet's branch prefix."""
    pfx = _prefix(coglet_id, branch)
    for path, content in files.items():
        store.upsert(pfx + path, content, source="coglet")


def read_file_tree(store: FileStore, coglet_id: str, branch: str) -> dict[str, str]:
    """Read all files under a coglet's branch prefix. Returns {relative_path: content}."""
    pfx = _prefix(coglet_id, branch)
    files = store.list_files(prefix=pfx, limit=1000)
    result = {}
    for f in files:
        content = store.get_content(f.key)
        if content is not None:
            # Strip the prefix to get the relative path
            rel_path = f.key[len(pfx):]
            result[rel_path] = content
    return result


def delete_file_tree(store: FileStore, coglet_id: str, branch: str) -> int:
    """Delete all files under a coglet's branch prefix. Returns count deleted."""
    pfx = _prefix(coglet_id, branch)
    files = store.list_files(prefix=pfx, limit=1000)
    for f in files:
        store.delete(f.key)
    return len(files)
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/daveey/code/cogents/cogents.2 && python -m pytest tests/cogos/test_coglet.py -v -x`
Expected: PASS (9 tests)

**Step 5: Commit**

```bash
git add src/cogos/coglet/__init__.py tests/cogos/test_coglet.py
git commit -m "feat(coglet): add file tree read/write/delete helpers"
```

---

### Task 4: Coglet Core — Diff Application

Apply a unified diff to a file tree dict.

**Files:**
- Modify: `src/cogos/coglet/__init__.py`
- Test: `tests/cogos/test_coglet.py`

**Step 1: Write the failing test**

```python
# append to tests/cogos/test_coglet.py
from cogos.coglet import apply_diff


def test_apply_diff_modifies_file():
    files = {"src/main.py": "def hello():\n    return 'world'\n"}
    diff = """--- a/src/main.py
+++ b/src/main.py
@@ -1,2 +1,2 @@
 def hello():
-    return 'world'
+    return 'universe'
"""
    result = apply_diff(files, diff)
    assert "universe" in result["src/main.py"]
    assert "world" not in result["src/main.py"]


def test_apply_diff_adds_file():
    files = {"src/main.py": "pass\n"}
    diff = """--- /dev/null
+++ b/src/new.py
@@ -0,0 +1,2 @@
+def new():
+    pass
"""
    result = apply_diff(files, diff)
    assert "src/new.py" in result
    assert "def new():" in result["src/new.py"]


def test_apply_diff_deletes_file():
    files = {"src/old.py": "pass\n"}
    diff = """--- a/src/old.py
+++ /dev/null
@@ -1 +0,0 @@
-pass
"""
    result = apply_diff(files, diff)
    assert "src/old.py" not in result


def test_apply_diff_invalid_raises():
    files = {"src/main.py": "pass\n"}
    diff = "this is not a valid diff"
    try:
        apply_diff(files, diff)
        assert False, "should have raised"
    except ValueError:
        pass
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/daveey/code/cogents/cogents.2 && python -m pytest tests/cogos/test_coglet.py::test_apply_diff_modifies_file -v -x`
Expected: FAIL — `ImportError: cannot import name 'apply_diff'`

**Step 3: Write minimal implementation**

Add to `src/cogos/coglet/__init__.py`:

```python
import re


def apply_diff(files: dict[str, str], diff: str) -> dict[str, str]:
    """Apply a unified diff to a file tree dict. Returns a new dict with changes applied.

    Supports file modifications, additions, and deletions.
    Raises ValueError if the diff is malformed or cannot be applied.
    """
    result = dict(files)
    # Split into per-file hunks
    file_diffs = re.split(r'^(?=--- )', diff.strip(), flags=re.MULTILINE)
    file_diffs = [d for d in file_diffs if d.strip()]

    if not file_diffs:
        raise ValueError("No valid diff hunks found")

    for file_diff in file_diffs:
        lines = file_diff.split('\n')
        if len(lines) < 2:
            raise ValueError(f"Malformed diff section: {file_diff[:100]}")

        old_line = lines[0]  # --- a/path or --- /dev/null
        new_line = lines[1]  # +++ b/path or +++ /dev/null

        if not old_line.startswith('--- ') or not new_line.startswith('+++ '):
            raise ValueError(f"Expected --- and +++ headers, got: {old_line}, {new_line}")

        old_path = old_line[4:].strip()
        new_path = new_line[4:].strip()

        # Strip a/ b/ prefixes
        if old_path.startswith('a/'):
            old_path = old_path[2:]
        if new_path.startswith('b/'):
            new_path = new_path[2:]

        is_delete = new_path == '/dev/null' or new_path == 'dev/null'
        is_create = old_path == '/dev/null' or old_path == 'dev/null'

        if is_delete:
            result.pop(old_path, None)
            continue

        # Parse hunks
        hunk_lines = lines[2:]
        new_content_lines: list[str] = []

        if is_create:
            # New file — collect all + lines
            for hl in hunk_lines:
                if hl.startswith('+') and not hl.startswith('+++'):
                    new_content_lines.append(hl[1:])
                elif hl.startswith('@@'):
                    continue
                elif hl.startswith('-'):
                    continue
                elif hl.startswith(' '):
                    new_content_lines.append(hl[1:])
                elif hl.startswith('\\'):
                    continue
            result[new_path] = '\n'.join(new_content_lines)
            if new_content_lines and not result[new_path].endswith('\n'):
                result[new_path] += '\n'
            continue

        # Modification — apply hunks to existing content
        if old_path not in result:
            raise ValueError(f"Cannot patch '{old_path}': file not found in tree")

        original_lines = result[old_path].split('\n')
        # Remove trailing empty string from split if file ends with newline
        if original_lines and original_lines[-1] == '':
            original_lines = original_lines[:-1]

        output_lines = list(original_lines)
        offset = 0

        for hl_idx, hl in enumerate(hunk_lines):
            if not hl.startswith('@@'):
                continue
            # Parse @@ -start,count +start,count @@
            match = re.match(r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@', hl)
            if not match:
                raise ValueError(f"Malformed hunk header: {hl}")

            old_start = int(match.group(1)) - 1  # 0-indexed
            # Collect hunk body
            hunk_body = []
            for body_line in hunk_lines[hl_idx + 1:]:
                if body_line.startswith('@@'):
                    break
                if body_line.startswith('\\'):
                    continue
                hunk_body.append(body_line)

            # Apply hunk
            new_lines = []
            remove_count = 0
            for bl in hunk_body:
                if bl.startswith('+'):
                    new_lines.append(bl[1:])
                elif bl.startswith('-'):
                    remove_count += 1
                elif bl.startswith(' '):
                    new_lines.append(bl[1:])
                else:
                    new_lines.append(bl)

            pos = old_start + offset
            output_lines[pos:pos + remove_count + len([b for b in hunk_body if b.startswith(' ')])] = new_lines
            # Recalculate: we replaced (context + removed) lines with new_lines
            old_count = len([b for b in hunk_body if b.startswith(' ') or b.startswith('-')])
            offset += len(new_lines) - old_count

        result[new_path] = '\n'.join(output_lines) + '\n'

    return result
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/daveey/code/cogents/cogents.2 && python -m pytest tests/cogos/test_coglet.py -v -x`
Expected: PASS (13 tests)

Note: The diff application is the trickiest part. If the hand-written parser has edge cases, the implementation step should iterate until all 4 diff tests pass. An alternative is to use `subprocess.run(["patch", ...])` in the temp dir, but keeping it in-process is simpler for now. If it proves brittle, swap to `patch` command later.

**Step 5: Commit**

```bash
git add src/cogos/coglet/__init__.py tests/cogos/test_coglet.py
git commit -m "feat(coglet): add unified diff application"
```

---

### Task 5: CogletsCapability — Create and List

**Files:**
- Create: `src/cogos/capabilities/coglets.py`
- Test: `tests/cogos/test_coglet.py`

**Step 1: Write the failing test**

```python
# append to tests/cogos/test_coglet.py
from uuid import uuid4
from cogos.capabilities.coglets import CogletsCapability


def test_coglets_create(tmp_path):
    repo = LocalRepository(str(tmp_path))
    pid = uuid4()
    cap = CogletsCapability(repo, pid)

    result = cap.create(
        name="my-widget",
        test_command="python -c 'assert True'",
        files={"main.py": "print('hello')", "test_main.py": "assert True"},
    )

    assert result.coglet_id
    assert result.name == "my-widget"
    assert result.version == 0
    assert result.test_passed is True


def test_coglets_create_failing_tests(tmp_path):
    repo = LocalRepository(str(tmp_path))
    pid = uuid4()
    cap = CogletsCapability(repo, pid)

    result = cap.create(
        name="broken",
        test_command="python -c 'assert False'",
        files={"main.py": "pass"},
    )

    assert result.coglet_id
    assert result.test_passed is False


def test_coglets_list(tmp_path):
    repo = LocalRepository(str(tmp_path))
    pid = uuid4()
    cap = CogletsCapability(repo, pid)

    cap.create(name="a", test_command="true", files={"a.py": ""})
    cap.create(name="b", test_command="true", files={"b.py": ""})

    result = cap.list()
    names = [c.name for c in result]
    assert "a" in names
    assert "b" in names


def test_coglets_get(tmp_path):
    repo = LocalRepository(str(tmp_path))
    pid = uuid4()
    cap = CogletsCapability(repo, pid)

    created = cap.create(name="widget", test_command="true", files={"w.py": ""})
    got = cap.get(created.coglet_id)

    assert got.name == "widget"
    assert got.coglet_id == created.coglet_id


def test_coglets_delete(tmp_path):
    repo = LocalRepository(str(tmp_path))
    pid = uuid4()
    cap = CogletsCapability(repo, pid)

    created = cap.create(name="doomed", test_command="true", files={"d.py": ""})
    cap.delete(created.coglet_id)

    result = cap.list()
    assert len(result) == 0
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/daveey/code/cogents/cogents.2 && python -m pytest tests/cogos/test_coglet.py::test_coglets_create -v -x`
Expected: FAIL — `ModuleNotFoundError: No module named 'cogos.capabilities.coglets'`

**Step 3: Write minimal implementation**

```python
# src/cogos/capabilities/coglets.py
"""CogletsCapability — factory for creating and managing coglets."""

from __future__ import annotations

import json
import logging
from uuid import UUID

from pydantic import BaseModel

from cogos.capabilities.base import Capability
from cogos.coglet import (
    CogletMeta,
    TestResult,
    read_file_tree,
    run_tests,
    write_file_tree,
    delete_file_tree,
)
from cogos.files.store import FileStore

logger = logging.getLogger(__name__)

META_KEY = "coglets/{coglet_id}/meta.json"


class CogletInfo(BaseModel):
    coglet_id: str
    name: str
    version: int
    test_passed: bool
    test_output: str = ""
    test_command: str = ""
    executor: str = "subprocess"


class CogletError(BaseModel):
    error: str


class DeleteResult(BaseModel):
    deleted: bool
    coglet_id: str


def _meta_key(coglet_id: str) -> str:
    return f"coglets/{coglet_id}/meta.json"


def _load_meta(store: FileStore, coglet_id: str) -> CogletMeta | None:
    content = store.get_content(_meta_key(coglet_id))
    if content is None:
        return None
    return CogletMeta(**json.loads(content))


def _save_meta(store: FileStore, meta: CogletMeta) -> None:
    store.upsert(_meta_key(meta.id), meta.model_dump_json(indent=2), source="coglet")


class CogletsCapability(Capability):
    """Manage coglets — create, list, get, delete.

    Usage:
        coglets.create(name="my-thing", test_command="pytest", files={...})
        coglets.list()
        coglets.get(coglet_id)
        coglets.delete(coglet_id)
    """

    ALL_OPS = {"create", "list", "get", "delete"}

    def _narrow(self, existing: dict, requested: dict) -> dict:
        result = {}
        old_ops = set(existing.get("ops") or self.ALL_OPS)
        new_ops = set(requested.get("ops") or self.ALL_OPS)
        result["ops"] = sorted(old_ops & new_ops)
        # Narrow coglet_ids
        old_ids = existing.get("coglet_ids")
        new_ids = requested.get("coglet_ids")
        if old_ids is not None and new_ids is not None:
            result["coglet_ids"] = sorted(set(old_ids) & set(new_ids))
        elif old_ids is not None:
            result["coglet_ids"] = old_ids
        elif new_ids is not None:
            result["coglet_ids"] = new_ids
        return result

    def _check(self, op: str, **context: object) -> None:
        if not self._scope:
            return
        allowed_ops = set(self._scope.get("ops") or self.ALL_OPS)
        if op not in allowed_ops:
            raise PermissionError(f"Operation '{op}' not allowed (allowed: {sorted(allowed_ops)})")
        allowed_ids = self._scope.get("coglet_ids")
        if allowed_ids is not None:
            coglet_id = context.get("coglet_id", "")
            if coglet_id and str(coglet_id) not in allowed_ids:
                raise PermissionError(f"Coglet '{coglet_id}' not in allowed set")

    def create(
        self,
        name: str,
        test_command: str,
        files: dict[str, str],
        executor: str = "subprocess",
        timeout_seconds: int = 60,
    ) -> CogletInfo | CogletError:
        """Create a new coglet with initial files, run tests to validate."""
        self._check("create")
        store = FileStore(self.repo)

        meta = CogletMeta(
            name=name,
            test_command=test_command,
            executor=executor,
            timeout_seconds=timeout_seconds,
        )

        # Write files to main/
        write_file_tree(store, meta.id, "main", files)

        # Run initial tests
        test_result = run_tests(
            test_command=test_command,
            file_tree=files,
            timeout_seconds=timeout_seconds,
        )

        # Save metadata
        _save_meta(store, meta)

        return CogletInfo(
            coglet_id=meta.id,
            name=meta.name,
            version=meta.version,
            test_passed=test_result.passed,
            test_output=test_result.output,
            test_command=test_command,
            executor=executor,
        )

    def list(self) -> list[CogletInfo]:
        """List all coglets."""
        self._check("list")
        store = FileStore(self.repo)
        # Find all meta.json files under coglets/
        meta_files = store.list_files(prefix="coglets/", limit=1000)
        results = []
        for f in meta_files:
            if f.key.endswith("/meta.json"):
                content = store.get_content(f.key)
                if content:
                    meta = CogletMeta(**json.loads(content))
                    results.append(CogletInfo(
                        coglet_id=meta.id,
                        name=meta.name,
                        version=meta.version,
                        test_passed=True,
                        test_command=meta.test_command,
                        executor=meta.executor,
                    ))
        return results

    def get(self, coglet_id: str) -> CogletInfo | CogletError:
        """Get metadata for a coglet."""
        self._check("get", coglet_id=coglet_id)
        store = FileStore(self.repo)
        meta = _load_meta(store, coglet_id)
        if meta is None:
            return CogletError(error=f"Coglet '{coglet_id}' not found")
        return CogletInfo(
            coglet_id=meta.id,
            name=meta.name,
            version=meta.version,
            test_passed=True,
            test_command=meta.test_command,
            executor=meta.executor,
        )

    def delete(self, coglet_id: str) -> DeleteResult | CogletError:
        """Delete a coglet and all its files."""
        self._check("delete", coglet_id=coglet_id)
        store = FileStore(self.repo)
        meta = _load_meta(store, coglet_id)
        if meta is None:
            return CogletError(error=f"Coglet '{coglet_id}' not found")

        # Delete all files under coglets/{id}/
        all_files = store.list_files(prefix=f"coglets/{coglet_id}/", limit=10000)
        for f in all_files:
            store.delete(f.key)

        return DeleteResult(deleted=True, coglet_id=coglet_id)

    def __repr__(self) -> str:
        return "<CogletsCapability create() list() get() delete()>"
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/daveey/code/cogents/cogents.2 && python -m pytest tests/cogos/test_coglet.py -v -x`
Expected: PASS (18 tests)

**Step 5: Commit**

```bash
git add src/cogos/capabilities/coglets.py tests/cogos/test_coglet.py
git commit -m "feat(coglet): add CogletsCapability with create/list/get/delete"
```

---

### Task 6: CogletCapability — Propose Patch

**Files:**
- Create: `src/cogos/capabilities/coglet.py`
- Test: `tests/cogos/test_coglet.py`

**Step 1: Write the failing test**

```python
# append to tests/cogos/test_coglet.py
from cogos.capabilities.coglet import CogletCapability


def _create_test_coglet(tmp_path, files=None, test_command="python -c 'assert True'"):
    """Helper: create a coglet and return (repo, coglet_id)."""
    repo = LocalRepository(str(tmp_path))
    pid = uuid4()
    cap = CogletsCapability(repo, pid)
    if files is None:
        files = {"src/main.py": "def hello():\n    return 'world'\n",
                 "tests/test_main.py": "exec(open('src/main.py').read())\nassert hello() == 'world'\n"}
    result = cap.create(name="test-coglet", test_command=test_command, files=files)
    return repo, result.coglet_id


def test_propose_patch_passing(tmp_path):
    repo, coglet_id = _create_test_coglet(tmp_path)
    pid = uuid4()
    cap = CogletCapability(repo, pid)
    cap._scope = {"coglet_id": coglet_id}

    diff = """--- a/src/main.py
+++ b/src/main.py
@@ -1,2 +1,2 @@
 def hello():
-    return 'world'
+    return 'universe'
"""
    # Also update tests to match
    diff += """--- a/tests/test_main.py
+++ b/tests/test_main.py
@@ -1,2 +1,2 @@
 exec(open('src/main.py').read())
-assert hello() == 'world'
+assert hello() == 'universe'
"""
    result = cap.propose_patch(diff)
    assert result.patch_id
    assert result.base_version == 0
    assert result.test_passed is True


def test_propose_patch_failing(tmp_path):
    repo, coglet_id = _create_test_coglet(tmp_path)
    pid = uuid4()
    cap = CogletCapability(repo, pid)
    cap._scope = {"coglet_id": coglet_id}

    # Change code but not tests — tests should fail
    diff = """--- a/src/main.py
+++ b/src/main.py
@@ -1,2 +1,2 @@
 def hello():
-    return 'world'
+    return 'broken'
"""
    result = cap.propose_patch(diff)
    assert result.patch_id
    assert result.test_passed is False
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/daveey/code/cogents/cogents.2 && python -m pytest tests/cogos/test_coglet.py::test_propose_patch_passing -v -x`
Expected: FAIL — `ModuleNotFoundError: No module named 'cogos.capabilities.coglet'`

**Step 3: Write minimal implementation**

```python
# src/cogos/capabilities/coglet.py
"""CogletCapability — the Author's tendril into a single coglet."""

from __future__ import annotations

import json
import logging
from uuid import uuid4

from pydantic import BaseModel

from cogos.capabilities.base import Capability
from cogos.capabilities.coglets import _load_meta, _save_meta, CogletError
from cogos.coglet import (
    LogEntry,
    PatchInfo,
    apply_diff,
    read_file_tree,
    run_tests,
    write_file_tree,
    delete_file_tree,
)
from cogos.files.store import FileStore

logger = logging.getLogger(__name__)


class PatchResult(BaseModel):
    patch_id: str
    base_version: int
    test_passed: bool
    test_output: str = ""


class MergeResult(BaseModel):
    merged: bool
    new_version: int | None = None
    conflict: bool = False
    current_version: int | None = None
    base_version: int | None = None


class DiscardResult(BaseModel):
    discarded: bool
    patch_id: str


class PatchSummary(BaseModel):
    patch_id: str
    base_version: int
    test_passed: bool
    test_output: str = ""
    created_at: str = ""


class CogletStatus(BaseModel):
    coglet_id: str
    name: str
    version: int
    patch_count: int


class TestResultInfo(BaseModel):
    passed: bool
    output: str


class CogletCapability(Capability):
    """Operate on a single coglet — propose patches, inspect, merge.

    Must be scoped with coglet_id before use.

    Usage:
        coglet.propose_patch(diff)
        coglet.merge_patch(patch_id)
        coglet.discard_patch(patch_id)
        coglet.read_file("src/main.py")
        coglet.list_files()
        coglet.list_patches()
        coglet.get_status()
        coglet.run_tests()
        coglet.get_log()
    """

    ALL_OPS = {
        "propose_patch", "merge_patch", "discard_patch",
        "read_file", "list_files", "list_patches",
        "get_status", "run_tests", "get_log",
    }

    def _narrow(self, existing: dict, requested: dict) -> dict:
        result = {}
        old_ops = set(existing.get("ops") or self.ALL_OPS)
        new_ops = set(requested.get("ops") or self.ALL_OPS)
        result["ops"] = sorted(old_ops & new_ops)
        # coglet_id cannot change once set
        if "coglet_id" in existing and "coglet_id" in requested:
            if requested["coglet_id"] != existing["coglet_id"]:
                raise ValueError("Cannot change scoped coglet_id")
            result["coglet_id"] = existing["coglet_id"]
        elif "coglet_id" in existing:
            result["coglet_id"] = existing["coglet_id"]
        elif "coglet_id" in requested:
            result["coglet_id"] = requested["coglet_id"]
        return result

    def _check(self, op: str, **context: object) -> None:
        if not self._scope:
            return
        allowed_ops = set(self._scope.get("ops") or self.ALL_OPS)
        if op not in allowed_ops:
            raise PermissionError(f"Operation '{op}' not allowed")

    def _coglet_id(self) -> str:
        cid = self._scope.get("coglet_id")
        if not cid:
            raise ValueError("CogletCapability must be scoped with coglet_id")
        return cid

    def propose_patch(self, diff: str) -> PatchResult | CogletError:
        """Snapshot main, create branch, apply diff, run tests."""
        self._check("propose_patch")
        store = FileStore(self.repo)
        coglet_id = self._coglet_id()

        meta = _load_meta(store, coglet_id)
        if meta is None:
            return CogletError(error=f"Coglet '{coglet_id}' not found")

        # Read current main
        main_files = read_file_tree(store, coglet_id, "main")

        # Apply diff
        try:
            patched_files = apply_diff(main_files, diff)
        except ValueError as e:
            return CogletError(error=f"Failed to apply diff: {e}")

        # Create patch branch
        patch_id = str(uuid4())
        write_file_tree(store, coglet_id, f"patches/{patch_id}", patched_files)

        # Run tests
        test_result = run_tests(
            test_command=meta.test_command,
            file_tree=patched_files,
            timeout_seconds=meta.timeout_seconds,
        )

        # Record in metadata
        meta.patches[patch_id] = PatchInfo(
            base_version=meta.version,
            test_passed=test_result.passed,
            test_output=test_result.output,
        )
        _save_meta(store, meta)

        return PatchResult(
            patch_id=patch_id,
            base_version=meta.version,
            test_passed=test_result.passed,
            test_output=test_result.output,
        )

    def merge_patch(self, patch_id: str) -> MergeResult | CogletError:
        """Promote patch to main if base_version still matches."""
        self._check("merge_patch")
        store = FileStore(self.repo)
        coglet_id = self._coglet_id()

        meta = _load_meta(store, coglet_id)
        if meta is None:
            return CogletError(error=f"Coglet '{coglet_id}' not found")

        patch_info = meta.patches.get(patch_id)
        if patch_info is None:
            return CogletError(error=f"Patch '{patch_id}' not found")

        if not patch_info.test_passed:
            return CogletError(error=f"Patch '{patch_id}' tests did not pass")

        # Optimistic concurrency check
        if patch_info.base_version != meta.version:
            return MergeResult(
                merged=False,
                conflict=True,
                current_version=meta.version,
                base_version=patch_info.base_version,
            )

        # Read patch files and write to main
        patch_files = read_file_tree(store, coglet_id, f"patches/{patch_id}")

        # Delete old main files
        delete_file_tree(store, coglet_id, "main")

        # Write new main
        write_file_tree(store, coglet_id, "main", patch_files)

        # Bump version, clean up patch
        meta.version += 1
        del meta.patches[patch_id]
        _save_meta(store, meta)

        # Delete patch branch
        delete_file_tree(store, coglet_id, f"patches/{patch_id}")

        return MergeResult(merged=True, new_version=meta.version)

    def discard_patch(self, patch_id: str) -> DiscardResult | CogletError:
        """Delete a patch branch."""
        self._check("discard_patch")
        store = FileStore(self.repo)
        coglet_id = self._coglet_id()

        meta = _load_meta(store, coglet_id)
        if meta is None:
            return CogletError(error=f"Coglet '{coglet_id}' not found")

        if patch_id not in meta.patches:
            return CogletError(error=f"Patch '{patch_id}' not found")

        delete_file_tree(store, coglet_id, f"patches/{patch_id}")
        del meta.patches[patch_id]
        _save_meta(store, meta)

        return DiscardResult(discarded=True, patch_id=patch_id)

    def read_file(self, path: str, patch_id: str | None = None) -> str | CogletError:
        """Read a file from main or a specific patch branch."""
        self._check("read_file")
        store = FileStore(self.repo)
        coglet_id = self._coglet_id()
        branch = f"patches/{patch_id}" if patch_id else "main"
        prefix = f"coglets/{coglet_id}/{branch}/"
        content = store.get_content(prefix + path)
        if content is None:
            return CogletError(error=f"File '{path}' not found in {branch}")
        return content

    def list_files(self, patch_id: str | None = None) -> list[str]:
        """List files in main or a patch branch."""
        self._check("list_files")
        store = FileStore(self.repo)
        coglet_id = self._coglet_id()
        branch = f"patches/{patch_id}" if patch_id else "main"
        tree = read_file_tree(store, coglet_id, branch)
        return sorted(tree.keys())

    def list_patches(self) -> list[PatchSummary]:
        """All pending patches with status."""
        self._check("list_patches")
        store = FileStore(self.repo)
        coglet_id = self._coglet_id()
        meta = _load_meta(store, coglet_id)
        if meta is None:
            return []
        return [
            PatchSummary(
                patch_id=pid,
                base_version=info.base_version,
                test_passed=info.test_passed,
                test_output=info.test_output,
                created_at=info.created_at,
            )
            for pid, info in meta.patches.items()
        ]

    def get_status(self) -> CogletStatus | CogletError:
        """Current coglet state."""
        self._check("get_status")
        store = FileStore(self.repo)
        coglet_id = self._coglet_id()
        meta = _load_meta(store, coglet_id)
        if meta is None:
            return CogletError(error=f"Coglet '{coglet_id}' not found")
        return CogletStatus(
            coglet_id=meta.id,
            name=meta.name,
            version=meta.version,
            patch_count=len(meta.patches),
        )

    def run_tests(self) -> TestResultInfo | CogletError:
        """Run test_command against current main state."""
        self._check("run_tests")
        store = FileStore(self.repo)
        coglet_id = self._coglet_id()
        meta = _load_meta(store, coglet_id)
        if meta is None:
            return CogletError(error=f"Coglet '{coglet_id}' not found")
        main_files = read_file_tree(store, coglet_id, "main")
        result = run_tests(
            test_command=meta.test_command,
            file_tree=main_files,
            timeout_seconds=meta.timeout_seconds,
        )
        return TestResultInfo(passed=result.passed, output=result.output)

    def get_log(self) -> list[LogEntry]:
        """Return patch history from the log file."""
        self._check("get_log")
        store = FileStore(self.repo)
        coglet_id = self._coglet_id()
        content = store.get_content(f"coglets/{coglet_id}/log")
        if not content:
            return []
        entries = []
        for line in content.strip().split("\n"):
            if line.strip():
                entries.append(LogEntry(**json.loads(line)))
        return entries

    def __repr__(self) -> str:
        cid = self._scope.get("coglet_id", "?")
        return f"<CogletCapability coglet_id={cid}>"
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/daveey/code/cogents/cogents.2 && python -m pytest tests/cogos/test_coglet.py -v -x`
Expected: PASS (20 tests)

**Step 5: Commit**

```bash
git add src/cogos/capabilities/coglet.py tests/cogos/test_coglet.py
git commit -m "feat(coglet): add CogletCapability with propose_patch"
```

---

### Task 7: CogletCapability — Merge, Discard, Conflict Detection

**Files:**
- Test: `tests/cogos/test_coglet.py`

**Step 1: Write the failing tests**

```python
# append to tests/cogos/test_coglet.py


def test_merge_patch_success(tmp_path):
    repo, coglet_id = _create_test_coglet(tmp_path)
    pid = uuid4()
    cap = CogletCapability(repo, pid)
    cap._scope = {"coglet_id": coglet_id}

    diff = """--- a/src/main.py
+++ b/src/main.py
@@ -1,2 +1,2 @@
 def hello():
-    return 'world'
+    return 'universe'
--- a/tests/test_main.py
+++ b/tests/test_main.py
@@ -1,2 +1,2 @@
 exec(open('src/main.py').read())
-assert hello() == 'world'
+assert hello() == 'universe'
"""
    patch = cap.propose_patch(diff)
    assert patch.test_passed is True

    result = cap.merge_patch(patch.patch_id)
    assert result.merged is True
    assert result.new_version == 1

    # Verify main was updated
    content = cap.read_file("src/main.py")
    assert "universe" in content

    # Verify status shows new version
    status = cap.get_status()
    assert status.version == 1
    assert status.patch_count == 0


def test_merge_patch_conflict(tmp_path):
    repo, coglet_id = _create_test_coglet(tmp_path)
    pid = uuid4()
    cap = CogletCapability(repo, pid)
    cap._scope = {"coglet_id": coglet_id}

    # Create two patches based on version 0
    diff1 = """--- a/src/main.py
+++ b/src/main.py
@@ -1,2 +1,2 @@
 def hello():
-    return 'world'
+    return 'v1'
--- a/tests/test_main.py
+++ b/tests/test_main.py
@@ -1,2 +1,2 @@
 exec(open('src/main.py').read())
-assert hello() == 'world'
+assert hello() == 'v1'
"""
    diff2 = """--- a/src/main.py
+++ b/src/main.py
@@ -1,2 +1,2 @@
 def hello():
-    return 'world'
+    return 'v2'
--- a/tests/test_main.py
+++ b/tests/test_main.py
@@ -1,2 +1,2 @@
 exec(open('src/main.py').read())
-assert hello() == 'world'
+assert hello() == 'v2'
"""
    p1 = cap.propose_patch(diff1)
    p2 = cap.propose_patch(diff2)

    # Merge first patch — succeeds
    r1 = cap.merge_patch(p1.patch_id)
    assert r1.merged is True

    # Merge second patch — conflicts (base_version 0 != current 1)
    r2 = cap.merge_patch(p2.patch_id)
    assert r2.merged is False
    assert r2.conflict is True
    assert r2.current_version == 1
    assert r2.base_version == 0


def test_merge_patch_rejects_failed_tests(tmp_path):
    repo, coglet_id = _create_test_coglet(tmp_path)
    pid = uuid4()
    cap = CogletCapability(repo, pid)
    cap._scope = {"coglet_id": coglet_id}

    # Patch that breaks tests
    diff = """--- a/src/main.py
+++ b/src/main.py
@@ -1,2 +1,2 @@
 def hello():
-    return 'world'
+    return 'broken'
"""
    patch = cap.propose_patch(diff)
    assert patch.test_passed is False

    result = cap.merge_patch(patch.patch_id)
    assert hasattr(result, "error")
    assert "not pass" in result.error.lower() or "did not pass" in result.error.lower()


def test_discard_patch(tmp_path):
    repo, coglet_id = _create_test_coglet(tmp_path)
    pid = uuid4()
    cap = CogletCapability(repo, pid)
    cap._scope = {"coglet_id": coglet_id}

    diff = """--- a/src/main.py
+++ b/src/main.py
@@ -1,2 +1,2 @@
 def hello():
-    return 'world'
+    return 'discarded'
--- a/tests/test_main.py
+++ b/tests/test_main.py
@@ -1,2 +1,2 @@
 exec(open('src/main.py').read())
-assert hello() == 'world'
+assert hello() == 'discarded'
"""
    patch = cap.propose_patch(diff)
    result = cap.discard_patch(patch.patch_id)
    assert result.discarded is True

    patches = cap.list_patches()
    assert len(patches) == 0

    # Main unchanged
    content = cap.read_file("src/main.py")
    assert "world" in content
```

**Step 2: Run test to verify they pass** (implementation already exists from Task 6)

Run: `cd /Users/daveey/code/cogents/cogents.2 && python -m pytest tests/cogos/test_coglet.py -v -x`
Expected: PASS (24 tests) — merge/discard/conflict logic is already in Task 6's implementation. If any fail, fix the implementation.

**Step 3: Commit**

```bash
git add tests/cogos/test_coglet.py
git commit -m "test(coglet): add merge, discard, and conflict detection tests"
```

---

### Task 8: CogletCapability — Inspection Methods

**Files:**
- Test: `tests/cogos/test_coglet.py`

**Step 1: Write the tests**

```python
# append to tests/cogos/test_coglet.py


def test_list_files(tmp_path):
    repo, coglet_id = _create_test_coglet(tmp_path)
    pid = uuid4()
    cap = CogletCapability(repo, pid)
    cap._scope = {"coglet_id": coglet_id}

    files = cap.list_files()
    assert "src/main.py" in files
    assert "tests/test_main.py" in files


def test_read_file(tmp_path):
    repo, coglet_id = _create_test_coglet(tmp_path)
    pid = uuid4()
    cap = CogletCapability(repo, pid)
    cap._scope = {"coglet_id": coglet_id}

    content = cap.read_file("src/main.py")
    assert "hello" in content


def test_read_file_from_patch(tmp_path):
    repo, coglet_id = _create_test_coglet(tmp_path)
    pid = uuid4()
    cap = CogletCapability(repo, pid)
    cap._scope = {"coglet_id": coglet_id}

    diff = """--- a/src/main.py
+++ b/src/main.py
@@ -1,2 +1,2 @@
 def hello():
-    return 'world'
+    return 'patched'
--- a/tests/test_main.py
+++ b/tests/test_main.py
@@ -1,2 +1,2 @@
 exec(open('src/main.py').read())
-assert hello() == 'world'
+assert hello() == 'patched'
"""
    patch = cap.propose_patch(diff)

    # Read from patch branch
    content = cap.read_file("src/main.py", patch_id=patch.patch_id)
    assert "patched" in content

    # Main still has original
    main_content = cap.read_file("src/main.py")
    assert "world" in main_content


def test_get_status(tmp_path):
    repo, coglet_id = _create_test_coglet(tmp_path)
    pid = uuid4()
    cap = CogletCapability(repo, pid)
    cap._scope = {"coglet_id": coglet_id}

    status = cap.get_status()
    assert status.coglet_id == coglet_id
    assert status.version == 0
    assert status.patch_count == 0


def test_run_tests_on_main(tmp_path):
    repo, coglet_id = _create_test_coglet(tmp_path)
    pid = uuid4()
    cap = CogletCapability(repo, pid)
    cap._scope = {"coglet_id": coglet_id}

    result = cap.run_tests()
    assert result.passed is True
```

**Step 2: Run tests**

Run: `cd /Users/daveey/code/cogents/cogents.2 && python -m pytest tests/cogos/test_coglet.py -v -x`
Expected: PASS (29 tests) — all inspection methods are already implemented in Task 6.

**Step 3: Commit**

```bash
git add tests/cogos/test_coglet.py
git commit -m "test(coglet): add inspection method tests"
```

---

### Task 9: Image Integration — add_coglet()

**Files:**
- Modify: `src/cogos/image/spec.py`
- Modify: `src/cogos/image/apply.py`
- Test: `tests/cogos/test_coglet.py`

**Step 1: Write the failing test**

```python
# append to tests/cogos/test_coglet.py
from cogos.image.spec import ImageSpec, load_image
from cogos.image.apply import apply_image


def test_image_spec_add_coglet():
    spec = ImageSpec()
    spec.coglets.append({
        "name": "my-widget",
        "test_command": "python -c 'assert True'",
        "files": {"main.py": "pass", "test_main.py": "assert True"},
    })
    assert len(spec.coglets) == 1
    assert spec.coglets[0]["name"] == "my-widget"


def test_apply_image_creates_coglet(tmp_path):
    repo = LocalRepository(str(tmp_path))
    spec = ImageSpec(
        coglets=[{
            "name": "my-widget",
            "test_command": "python -c 'assert True'",
            "files": {"main.py": "pass", "test_main.py": "assert True"},
        }],
    )
    counts = apply_image(spec, repo)
    assert counts.get("coglets", 0) == 1

    # Verify coglet files exist
    store = FileStore(repo)
    meta_files = store.list_files(prefix="coglets/", limit=100)
    meta_keys = [f.key for f in meta_files]
    assert any("meta.json" in k for k in meta_keys)
    assert any("main/" in k for k in meta_keys)
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/daveey/code/cogents/cogents.2 && python -m pytest tests/cogos/test_coglet.py::test_image_spec_add_coglet -v -x`
Expected: FAIL — `AttributeError: 'ImageSpec' object has no attribute 'coglets'`

**Step 3: Write minimal implementation**

Add to `ImageSpec` in `src/cogos/image/spec.py`:
```python
# Add to the ImageSpec dataclass fields:
    coglets: list[dict] = field(default_factory=list)
```

Add `add_coglet` to the `load_image` function builtins:
```python
    def add_coglet(name, *, test_command, files, executor="subprocess", timeout_seconds=60):
        spec.coglets.append({
            "name": name, "test_command": test_command, "files": files,
            "executor": executor, "timeout_seconds": timeout_seconds,
        })
```
And add `"add_coglet": add_coglet` to the builtins dict.

Add to `apply_image` in `src/cogos/image/apply.py`, after the existing sections (before the stale-process cleanup):
```python
    # 8. Coglets
    from cogos.coglet import CogletMeta, run_tests, write_file_tree
    from cogos.capabilities.coglets import _load_meta, _save_meta, _meta_key
    counts["coglets"] = 0
    fs = FileStore(repo)
    for coglet_dict in spec.coglets:
        name = coglet_dict["name"]
        test_command = coglet_dict["test_command"]
        files = coglet_dict["files"]
        executor = coglet_dict.get("executor", "subprocess")
        timeout_seconds = coglet_dict.get("timeout_seconds", 60)

        # Check if coglet with this name already exists
        existing_metas = fs.list_files(prefix="coglets/", limit=1000)
        existing_id = None
        for mf in existing_metas:
            if mf.key.endswith("/meta.json"):
                content = fs.get_content(mf.key)
                if content:
                    try:
                        m = CogletMeta(**json.loads(content))
                        if m.name == name:
                            existing_id = m.id
                            break
                    except Exception:
                        pass

        if existing_id:
            # Update existing coglet's files
            meta = _load_meta(fs, existing_id)
            write_file_tree(fs, existing_id, "main", files)
            meta.test_command = test_command
            meta.executor = executor
            meta.timeout_seconds = timeout_seconds
            _save_meta(fs, meta)
        else:
            # Create new coglet
            meta = CogletMeta(
                name=name,
                test_command=test_command,
                executor=executor,
                timeout_seconds=timeout_seconds,
            )
            write_file_tree(fs, meta.id, "main", files)
            _save_meta(fs, meta)

        counts["coglets"] += 1
```

Also add `import json` at the top of `apply.py` if not already present.

**Step 4: Run test to verify it passes**

Run: `cd /Users/daveey/code/cogents/cogents.2 && python -m pytest tests/cogos/test_coglet.py -v -x`
Expected: PASS (31 tests)

**Step 5: Commit**

```bash
git add src/cogos/image/spec.py src/cogos/image/apply.py tests/cogos/test_coglet.py
git commit -m "feat(coglet): add image integration with add_coglet()"
```

---

### Task 10: Capability Registration

Register the coglet capabilities so they can be bound to processes via the image system.

**Files:**
- Test: `tests/cogos/test_coglet.py`

**Step 1: Write the test**

```python
# append to tests/cogos/test_coglet.py


def test_coglet_capabilities_in_image(tmp_path):
    """Verify coglet capabilities can be registered and bound to a process."""
    repo = LocalRepository(str(tmp_path))
    spec = ImageSpec(
        capabilities=[
            {"name": "coglets", "handler": "cogos.capabilities.coglets:CogletsCapability",
             "description": "Manage coglets", "instructions": "", "schema": None,
             "iam_role_arn": None, "metadata": None},
            {"name": "coglet", "handler": "cogos.capabilities.coglet:CogletCapability",
             "description": "Operate on a coglet", "instructions": "", "schema": None,
             "iam_role_arn": None, "metadata": None},
        ],
        processes=[
            {"name": "author", "mode": "one_shot", "content": "I author coglets",
             "runner": "lambda",
             "capabilities": ["coglets", "coglet"],
             "handlers": [], "metadata": {}},
        ],
    )
    counts = apply_image(spec, repo)
    assert counts["capabilities"] == 2
    assert counts["processes"] == 1

    # Verify the capabilities loaded
    cap = repo.get_capability_by_name("coglets")
    assert cap is not None
    assert "CogletsCapability" in cap.handler

    cap2 = repo.get_capability_by_name("coglet")
    assert cap2 is not None
    assert "CogletCapability" in cap2.handler
```

**Step 2: Run test**

Run: `cd /Users/daveey/code/cogents/cogents.2 && python -m pytest tests/cogos/test_coglet.py::test_coglet_capabilities_in_image -v -x`
Expected: PASS — the existing image apply logic handles arbitrary capability handlers.

**Step 3: Commit**

```bash
git add tests/cogos/test_coglet.py
git commit -m "test(coglet): verify capability registration through image system"
```

---

### Task 11: Full E2E Test — Author Creates and Patches a Coglet

One integration test that exercises the full workflow: create coglet, propose patch, merge, verify.

**Files:**
- Test: `tests/cogos/test_coglet.py`

**Step 1: Write the test**

```python
# append to tests/cogos/test_coglet.py


def test_full_e2e_create_patch_merge(tmp_path):
    """Full workflow: create coglet, propose passing patch, merge, verify."""
    repo = LocalRepository(str(tmp_path))
    pid = uuid4()

    # 1. Create coglet
    factory = CogletsCapability(repo, pid)
    created = factory.create(
        name="calculator",
        test_command="python tests/test_calc.py",
        files={
            "src/calc.py": "def add(a, b):\n    return a + b\n",
            "tests/test_calc.py": "exec(open('src/calc.py').read())\nassert add(1, 2) == 3\n",
        },
    )
    assert created.test_passed is True

    # 2. Propose a patch that adds multiply
    tendril = CogletCapability(repo, pid)
    tendril._scope = {"coglet_id": created.coglet_id}

    diff = """--- a/src/calc.py
+++ b/src/calc.py
@@ -1,2 +1,5 @@
 def add(a, b):
     return a + b
+
+def multiply(a, b):
+    return a * b
--- a/tests/test_calc.py
+++ b/tests/test_calc.py
@@ -1,2 +1,4 @@
 exec(open('src/calc.py').read())
 assert add(1, 2) == 3
+assert multiply(3, 4) == 12
+assert multiply(0, 5) == 0
"""
    patch = tendril.propose_patch(diff)
    assert patch.test_passed is True

    # 3. Merge
    merge = tendril.merge_patch(patch.patch_id)
    assert merge.merged is True
    assert merge.new_version == 1

    # 4. Verify main was updated
    files = tendril.list_files()
    assert "src/calc.py" in files
    content = tendril.read_file("src/calc.py")
    assert "multiply" in content
    assert "add" in content

    # 5. Status reflects new version
    status = tendril.get_status()
    assert status.version == 1
    assert status.patch_count == 0

    # 6. Tests still pass on main
    test_result = tendril.run_tests()
    assert test_result.passed is True
```

**Step 2: Run test**

Run: `cd /Users/daveey/code/cogents/cogents.2 && python -m pytest tests/cogos/test_coglet.py::test_full_e2e_create_patch_merge -v -x`
Expected: PASS

**Step 3: Commit**

```bash
git add tests/cogos/test_coglet.py
git commit -m "test(coglet): add full e2e create-patch-merge test"
```

---

### Task 12: Run Full Test Suite

Verify nothing is broken across the entire project.

**Step 1: Run all coglet tests**

Run: `cd /Users/daveey/code/cogents/cogents.2 && python -m pytest tests/cogos/test_coglet.py -v`
Expected: All tests pass

**Step 2: Run full test suite**

Run: `cd /Users/daveey/code/cogents/cogents.2 && python -m pytest tests/ -v --timeout=60`
Expected: No regressions in existing tests

**Step 3: Final commit if any fixups were needed**

```bash
git add -A
git commit -m "fix(coglet): address test suite fixups"
```
