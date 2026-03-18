# History Capability Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** New `history` capability exposing run history, file mutation tracking, and cross-process audit queries.

**Architecture:** New capability class (`HistoryCapability`) with `ProcessHistory` helper. One DB migration (add `run_id` to `cogos_file_version`). Extend `list_runs` with filters. Thread `run_id` through file writes. Both `Repository` and `LocalRepository` updated.

**Tech Stack:** Python, Postgres, RDS Data API, pydantic models

---

### Task 1: Add `run_id` to `FileVersion` model and DB migration

**Files:**
- Modify: `src/cogos/db/models/file.py`
- Create: `src/cogos/db/migrations/017_file_version_run_id.sql`

**Step 1: Add `run_id` field to FileVersion model**

In `src/cogos/db/models/file.py`, add to `FileVersion`:

```python
class FileVersion(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    file_id: UUID
    version: int
    read_only: bool = False
    content: str = ""
    source: str = "cogent"
    is_active: bool = True
    run_id: UUID | None = None
    created_at: datetime | None = None
```

**Step 2: Create migration**

```sql
-- 017_file_version_run_id.sql
ALTER TABLE cogos_file_version
  ADD COLUMN IF NOT EXISTS run_id UUID REFERENCES cogos_run(id);

CREATE INDEX IF NOT EXISTS idx_file_version_run_id
  ON cogos_file_version(run_id);
```

**Step 3: Verify model loads**

Run: `python -c "from cogos.db.models.file import FileVersion; print(FileVersion.model_fields.keys())"`
Expected: includes `run_id`

**Step 4: Commit**

```bash
git add src/cogos/db/models/file.py src/cogos/db/migrations/017_file_version_run_id.sql
git commit -m "feat: add run_id to FileVersion model and migration"
```

---

### Task 2: Thread `run_id` through file write paths

**Files:**
- Modify: `src/cogos/db/repository.py` — `insert_file_version` to persist `run_id`
- Modify: `src/cogos/db/local_repository.py` — `insert_file_version` (no-op, model already carries it)
- Modify: `src/cogos/files/store.py` — `create`, `new_version`, `upsert` accept optional `run_id`

**Step 1: Update `Repository.insert_file_version` SQL**

Add `run_id` column to the INSERT and ON CONFLICT UPDATE in `repository.py` (~line 1038):

```python
def insert_file_version(self, fv: FileVersion) -> None:
    self._execute(
        """INSERT INTO cogos_file_version (id, file_id, version, read_only, content, source, is_active, run_id)
           VALUES (:id, :file_id, :version, :read_only, :content, :source, :is_active, :run_id)
           ON CONFLICT (file_id, version) DO UPDATE SET
               content = EXCLUDED.content,
               source = EXCLUDED.source,
               is_active = EXCLUDED.is_active,
               run_id = COALESCE(EXCLUDED.run_id, cogos_file_version.run_id)""",
        [
            self._param("id", fv.id),
            self._param("file_id", fv.file_id),
            self._param("version", fv.version),
            self._param("read_only", fv.read_only),
            self._param("content", fv.content),
            self._param("source", fv.source),
            self._param("is_active", fv.is_active),
            self._param("run_id", fv.run_id),
        ],
    )
    self._execute(
        "UPDATE cogos_file SET updated_at = now() WHERE id = :id",
        [self._param("id", fv.file_id)],
    )
```

**Step 2: Update `FileStore` to accept and pass `run_id`**

In `src/cogos/files/store.py`, add `run_id: UUID | None = None` parameter to `create`, `new_version`, and `upsert`. Pass it to `FileVersion(...)` construction:

```python
def create(self, key, content, *, source="cogent", read_only=False, run_id=None):
    ...
    fv = FileVersion(..., run_id=run_id)
    ...

def new_version(self, key, content, *, source="cogent", read_only=False, run_id=None):
    ...
    fv = FileVersion(..., run_id=run_id)
    ...

def upsert(self, key, content, *, source="cogent", read_only=False, run_id=None):
    ...
    return self.create(key, content, source=source, read_only=read_only, run_id=run_id)
    ...
    return self.new_version(key, content, source=source, read_only=read_only, run_id=run_id)
```

**Step 3: Verify existing tests still pass**

Run: `pytest tests/ -x -q --timeout=30`
Expected: PASS (run_id defaults to None, no behavior change)

**Step 4: Commit**

```bash
git add src/cogos/db/repository.py src/cogos/db/local_repository.py src/cogos/files/store.py
git commit -m "feat: thread run_id through file write paths"
```

---

### Task 3: Pass `run_id` from capabilities into FileStore writes

**Files:**
- Modify: `src/cogos/capabilities/files.py` — `FilesCapability.write` passes `self.run_id`
- Modify: `src/cogos/capabilities/file_cap.py` — `FileCapability` and `DirCapability` write methods pass `self.run_id`

**Step 1: Update FilesCapability.write**

In `files.py` (~line 138), pass `run_id=self.run_id` to `store.upsert()`:

```python
result = store.upsert(key, content, source=source, read_only=read_only, run_id=self.run_id)
```

**Step 2: Update FileCapability and DirCapability write paths**

Find all calls to `store.upsert()`, `store.create()`, `store.new_version()`, `store.append()` in `file_cap.py` and pass `run_id=self.run_id`.

Note: `self.run_id` is already available on `Capability` base class (set in `__init__`).

**Step 3: Verify tests pass**

Run: `pytest tests/cogos/capabilities/ -x -q`
Expected: PASS

**Step 4: Commit**

```bash
git add src/cogos/capabilities/files.py src/cogos/capabilities/file_cap.py
git commit -m "feat: pass run_id from capabilities into FileStore writes"
```

---

### Task 4: Add `RunSummary` and `FileMutation` models

**Files:**
- Create: `src/cogos/capabilities/history.py`

**Step 1: Create file with models only (no capability class yet)**

```python
"""History capability — run history, file mutations, cross-process audit."""

from __future__ import annotations

from pydantic import BaseModel


class RunSummary(BaseModel):
    id: str
    process_id: str
    process_name: str
    status: str
    duration_ms: int | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: str = "0"
    error: str | None = None
    result: dict | None = None
    model_version: str | None = None
    created_at: str | None = None
    completed_at: str | None = None


class FileMutation(BaseModel):
    key: str
    version: int
    created_at: str | None = None


class HistoryError(BaseModel):
    error: str
```

**Step 2: Verify import**

Run: `python -c "from cogos.capabilities.history import RunSummary, FileMutation; print('ok')"`
Expected: `ok`

**Step 3: Commit**

```bash
git add src/cogos/capabilities/history.py
git commit -m "feat: add RunSummary, FileMutation, HistoryError models"
```

---

### Task 5: Extend repo `list_runs` with filters and add `list_file_mutations`

**Files:**
- Modify: `src/cogos/db/repository.py`
- Modify: `src/cogos/db/local_repository.py`

**Step 1: Write failing tests**

Create: `tests/cogos/db/test_repo_history.py`

```python
"""Tests for history-related repo queries."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from cogos.db.repository import Repository


@pytest.fixture
def repo():
    with patch.object(Repository, "__init__", lambda self: None):
        r = Repository.__new__(Repository)
        r._client = MagicMock()
        r._resource_arn = "arn:test"
        r._secret_arn = "arn:secret"
        r._database = "testdb"
        r._reboot_epoch = 0
        return r


class TestListRunsExtended:
    def test_list_runs_with_status_filter(self, repo):
        repo._client.execute_statement.return_value = {"records": []}
        runs = repo.list_runs(status="failed")
        sql = repo._client.execute_statement.call_args[1].get("sql", "")
        assert repo._client.execute_statement.called

    def test_list_runs_with_since_filter(self, repo):
        repo._client.execute_statement.return_value = {"records": []}
        runs = repo.list_runs(since="2026-03-17T00:00:00")
        assert repo._client.execute_statement.called

    def test_list_runs_with_process_ids(self, repo):
        repo._client.execute_statement.return_value = {"records": []}
        ids = [uuid4(), uuid4()]
        runs = repo.list_runs(process_ids=ids)
        assert repo._client.execute_statement.called


class TestListFileMutations:
    def test_returns_file_mutations(self, repo):
        repo._client.execute_statement.return_value = {
            "columnMetadata": [
                {"name": "key"}, {"name": "version"}, {"name": "created_at"},
            ],
            "records": [
                [{"stringValue": "src/main.py"}, {"longValue": 3}, {"stringValue": "2026-03-17T12:00:00Z"}],
            ],
        }
        results = repo.list_file_mutations(uuid4())
        assert len(results) == 1
        assert results[0]["key"] == "src/main.py"

    def test_no_mutations(self, repo):
        repo._client.execute_statement.return_value = {"records": []}
        results = repo.list_file_mutations(uuid4())
        assert results == []


class TestListRunsByProcessGlob:
    def test_returns_runs_matching_glob(self, repo):
        repo._client.execute_statement.return_value = {"records": []}
        runs = repo.list_runs_by_process_glob("worker-*")
        assert repo._client.execute_statement.called
```

Run: `pytest tests/cogos/db/test_repo_history.py -v`
Expected: FAIL — missing methods

**Step 2: Extend `Repository.list_runs`**

Update signature and implementation (~line 1335):

```python
def list_runs(
    self,
    *,
    process_id: UUID | None = None,
    process_ids: list[UUID] | None = None,
    status: str | None = None,
    since: str | None = None,
    limit: int = 50,
    epoch: int | None = None,
) -> list[Run]:
    effective_epoch = self.reboot_epoch if epoch is None else epoch
    conditions = []
    params = [self._param("limit", limit)]
    if effective_epoch != ALL_EPOCHS:
        conditions.append("epoch = :epoch")
        params.append(self._param("epoch", effective_epoch))
    if process_id:
        conditions.append("process = :process")
        params.append(self._param("process", process_id))
    if process_ids:
        placeholders = ", ".join(f":pid_{i}" for i in range(len(process_ids)))
        conditions.append(f"process IN ({placeholders})")
        for i, pid in enumerate(process_ids):
            params.append(self._param(f"pid_{i}", pid))
    if status:
        conditions.append("status = :status")
        params.append(self._param("status", status))
    if since:
        conditions.append("created_at >= :since::timestamptz")
        params.append(self._param("since", since))
    where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
    response = self._execute(
        f"SELECT * FROM cogos_run{where} ORDER BY created_at DESC LIMIT :limit",
        params,
    )
    return [self._run_from_row(r) for r in self._rows_to_dicts(response)]
```

**Step 3: Add `list_file_mutations`**

```python
def list_file_mutations(self, run_id: UUID) -> list[dict]:
    """List file versions created by a specific run."""
    response = self._execute(
        """SELECT f.key, fv.version, fv.created_at
           FROM cogos_file_version fv
           JOIN cogos_file f ON f.id = fv.file_id
           WHERE fv.run_id = :run_id
           ORDER BY fv.created_at""",
        [self._param("run_id", run_id)],
    )
    return self._rows_to_dicts(response)
```

**Step 4: Add `list_runs_by_process_glob`**

```python
def list_runs_by_process_glob(
    self,
    name_pattern: str,
    *,
    status: str | None = None,
    since: str | None = None,
    limit: int = 50,
) -> list[Run]:
    """List runs for processes whose name matches a glob pattern."""
    # Convert glob to SQL LIKE: * -> %, ? -> _
    like_pattern = name_pattern.replace("*", "%").replace("?", "_")
    conditions = ["p.name LIKE :name_pattern", "r.epoch = :epoch"]
    params = [
        self._param("name_pattern", like_pattern),
        self._param("epoch", self.reboot_epoch),
        self._param("limit", limit),
    ]
    if status:
        conditions.append("r.status = :status")
        params.append(self._param("status", status))
    if since:
        conditions.append("r.created_at >= :since::timestamptz")
        params.append(self._param("since", since))
    where = " AND ".join(conditions)
    response = self._execute(
        f"""SELECT r.* FROM cogos_run r
            JOIN cogos_process p ON p.id = r.process
            WHERE {where}
            ORDER BY r.created_at DESC LIMIT :limit""",
        params,
    )
    return [self._run_from_row(r) for r in self._rows_to_dicts(response)]
```

**Step 5: Mirror in `LocalRepository`**

Update `local_repository.py`:
- Extend `list_runs` with same new params (`process_ids`, `status`, `since`)
- Add `list_file_mutations` — scan `_file_versions` for matching `run_id`
- Add `list_runs_by_process_glob` — filter by `fnmatch` on process name

**Step 6: Run tests**

Run: `pytest tests/cogos/db/test_repo_history.py -v`
Expected: PASS

**Step 7: Commit**

```bash
git add src/cogos/db/repository.py src/cogos/db/local_repository.py tests/cogos/db/test_repo_history.py
git commit -m "feat: extend list_runs with filters, add list_file_mutations and list_runs_by_process_glob"
```

---

### Task 6: Implement `HistoryCapability` and `ProcessHistory`

**Files:**
- Modify: `src/cogos/capabilities/history.py`

**Step 1: Write failing tests**

Create: `tests/cogos/capabilities/test_history.py`

```python
"""Tests for HistoryCapability."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from cogos.capabilities.history import (
    FileMutation,
    HistoryCapability,
    HistoryError,
    RunSummary,
)
from cogos.db.models import Process, ProcessMode, ProcessStatus, Run, RunStatus


@pytest.fixture
def repo():
    r = MagicMock()
    r.reboot_epoch = 0
    return r


@pytest.fixture
def pid():
    return uuid4()


class TestHistoryProcess:
    def test_process_by_name(self, repo, pid):
        proc = Process(name="worker-1", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.COMPLETED)
        repo.get_process_by_name.return_value = proc
        cap = HistoryCapability(repo, pid)
        h = cap.process(name="worker-1")
        assert h is not None

    def test_process_not_found(self, repo, pid):
        repo.get_process_by_name.return_value = None
        repo.get_process.return_value = None
        cap = HistoryCapability(repo, pid)
        result = cap.process(name="missing")
        assert isinstance(result, HistoryError)

    def test_process_runs(self, repo, pid):
        proc = Process(name="w", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.COMPLETED)
        repo.get_process_by_name.return_value = proc
        run = Run(process=proc.id, status=RunStatus.COMPLETED, duration_ms=100)
        run.created_at = "2026-03-17T12:00:00"
        repo.list_runs.return_value = [run]
        repo.get_process.return_value = proc
        cap = HistoryCapability(repo, pid)
        h = cap.process(name="w")
        runs = h.runs(limit=5)
        assert len(runs) == 1
        assert runs[0].status == "completed"

    def test_process_files(self, repo, pid):
        proc = Process(name="w", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.COMPLETED)
        repo.get_process_by_name.return_value = proc
        repo.list_file_mutations.return_value = [
            {"key": "src/main.py", "version": 2, "created_at": "2026-03-17T12:00:00Z"}
        ]
        cap = HistoryCapability(repo, pid)
        h = cap.process(name="w")
        files = h.files(run_id=str(uuid4()))
        assert len(files) == 1
        assert files[0].key == "src/main.py"

    def test_process_scope_restricts_access(self, repo, pid):
        other_proc = Process(name="secret", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.COMPLETED)
        repo.get_process_by_name.return_value = other_proc
        cap = HistoryCapability(repo, pid)
        scoped = cap.scope(process_ids=[str(pid)])
        result = scoped.process(name="secret")
        assert isinstance(result, HistoryError)


class TestHistoryQuery:
    def test_query_all(self, repo, pid):
        run = Run(process=uuid4(), status=RunStatus.FAILED, error="boom")
        run.created_at = "2026-03-17T12:00:00"
        proc = Process(name="worker-1", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.COMPLETED)
        repo.list_runs.return_value = [run]
        repo.get_process.return_value = proc
        cap = HistoryCapability(repo, pid)
        results = cap.query(status="failed")
        assert len(results) == 1
        assert results[0].error == "boom"

    def test_query_with_process_glob(self, repo, pid):
        run = Run(process=uuid4(), status=RunStatus.FAILED)
        run.created_at = "2026-03-17T12:00:00"
        proc = Process(name="worker-1", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.COMPLETED)
        repo.list_runs_by_process_glob.return_value = [run]
        repo.get_process.return_value = proc
        cap = HistoryCapability(repo, pid)
        results = cap.query(process_name="worker-*")
        assert len(results) == 1

    def test_failed_shorthand(self, repo, pid):
        repo.list_runs.return_value = []
        cap = HistoryCapability(repo, pid)
        results = cap.failed()
        assert results == []

    def test_query_denied_without_op(self, repo, pid):
        cap = HistoryCapability(repo, pid)
        scoped = cap.scope(ops=["process"])
        with pytest.raises(PermissionError):
            scoped.query()
```

Run: `pytest tests/cogos/capabilities/test_history.py -v`
Expected: FAIL — HistoryCapability has no methods yet

**Step 2: Implement HistoryCapability and ProcessHistory**

Update `src/cogos/capabilities/history.py`:

```python
"""History capability — run history, file mutations, cross-process audit."""

from __future__ import annotations

import logging
from uuid import UUID

from pydantic import BaseModel

from cogos.capabilities.base import Capability

logger = logging.getLogger(__name__)


# ── IO Models ────────────────────────────────────────────────


class RunSummary(BaseModel):
    id: str
    process_id: str
    process_name: str
    status: str
    duration_ms: int | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: str = "0"
    error: str | None = None
    result: dict | None = None
    model_version: str | None = None
    created_at: str | None = None
    completed_at: str | None = None


class FileMutation(BaseModel):
    key: str
    version: int
    created_at: str | None = None


class HistoryError(BaseModel):
    error: str


# ── ProcessHistory handle ────────────────────────────────────


class ProcessHistory:
    """Scoped to a single process's run history."""

    def __init__(self, repo, process) -> None:
        self._repo = repo
        self._process = process

    def runs(self, limit: int = 10) -> list[RunSummary]:
        """Recent runs for this process."""
        raw = self._repo.list_runs(process_id=self._process.id, limit=limit)
        return [self._to_summary(r) for r in raw]

    def files(self, run_id: str) -> list[FileMutation]:
        """File versions created by a specific run."""
        raw = self._repo.list_file_mutations(UUID(run_id))
        return [
            FileMutation(
                key=r["key"],
                version=r["version"],
                created_at=str(r["created_at"]) if r.get("created_at") else None,
            )
            for r in raw
        ]

    def _to_summary(self, run) -> RunSummary:
        proc = self._repo.get_process(run.process)
        return RunSummary(
            id=str(run.id),
            process_id=str(run.process),
            process_name=proc.name if proc else "unknown",
            status=run.status.value if hasattr(run.status, "value") else str(run.status),
            duration_ms=run.duration_ms,
            tokens_in=run.tokens_in,
            tokens_out=run.tokens_out,
            cost_usd=str(run.cost_usd),
            error=run.error,
            result=run.result,
            model_version=run.model_version,
            created_at=str(run.created_at) if run.created_at else None,
            completed_at=str(run.completed_at) if run.completed_at else None,
        )

    def __repr__(self) -> str:
        return f"<ProcessHistory '{self._process.name}' runs() files()>"


# ── Capability ───────────────────────────────────────────────


class HistoryCapability(Capability):
    """Run history and file mutation audit.

    Usage:
        h = history.process("worker-3")
        h.runs(limit=5)
        h.files(run_id="...")
        history.query(status="failed")
        history.failed(since="1h")
    """

    ALL_OPS = {"query", "process"}

    def _narrow(self, existing: dict, requested: dict) -> dict:
        merged = {}
        old_ops = set(existing.get("ops") or self.ALL_OPS)
        new_ops = set(requested.get("ops") or self.ALL_OPS)
        merged["ops"] = sorted(old_ops & new_ops)
        # process_ids: intersection if both set, otherwise the more restrictive
        old_pids = set(existing.get("process_ids") or [])
        new_pids = set(requested.get("process_ids") or [])
        if old_pids and new_pids:
            merged["process_ids"] = sorted(old_pids & new_pids)
        elif old_pids:
            merged["process_ids"] = sorted(old_pids)
        elif new_pids:
            merged["process_ids"] = sorted(new_pids)
        return merged

    def _check(self, op: str, **context: object) -> None:
        if not self._scope:
            return
        allowed = set(self._scope.get("ops") or self.ALL_OPS)
        if op not in allowed:
            raise PermissionError(f"Operation '{op}' not allowed (allowed: {sorted(allowed)})")

    def _check_process_access(self, process_id: UUID) -> bool:
        """Check if scope restricts access to specific process IDs."""
        if not self._scope:
            return True
        allowed_pids = self._scope.get("process_ids")
        if not allowed_pids:
            return True
        return str(process_id) in allowed_pids

    def process(
        self, name: str | None = None, id: str | None = None,
    ) -> ProcessHistory | HistoryError:
        """Get a handle scoped to one process's history."""
        self._check("process")
        if id:
            proc = self.repo.get_process(UUID(id))
        elif name:
            proc = self.repo.get_process_by_name(name)
        else:
            return HistoryError(error="name or id required")

        if proc is None:
            return HistoryError(error="process not found")

        if not self._check_process_access(proc.id):
            return HistoryError(error="access denied for this process")

        return ProcessHistory(self.repo, proc)

    def query(
        self,
        status: str | None = None,
        process_name: str | None = None,
        since: str | None = None,
        limit: int = 50,
    ) -> list[RunSummary]:
        """Cross-process run query."""
        self._check("query")

        if process_name:
            raw = self.repo.list_runs_by_process_glob(
                process_name, status=status, since=since, limit=limit,
            )
        else:
            raw = self.repo.list_runs(status=status, since=since, limit=limit)

        # Apply process_ids scope filter
        allowed_pids = (self._scope or {}).get("process_ids")
        if allowed_pids:
            pid_set = {UUID(p) for p in allowed_pids}
            raw = [r for r in raw if r.process in pid_set]

        results = []
        proc_cache: dict[UUID, str] = {}
        for run in raw:
            if run.process not in proc_cache:
                proc = self.repo.get_process(run.process)
                proc_cache[run.process] = proc.name if proc else "unknown"
            results.append(RunSummary(
                id=str(run.id),
                process_id=str(run.process),
                process_name=proc_cache[run.process],
                status=run.status.value if hasattr(run.status, "value") else str(run.status),
                duration_ms=run.duration_ms,
                tokens_in=run.tokens_in,
                tokens_out=run.tokens_out,
                cost_usd=str(run.cost_usd),
                error=run.error,
                result=run.result,
                model_version=run.model_version,
                created_at=str(run.created_at) if run.created_at else None,
                completed_at=str(run.completed_at) if run.completed_at else None,
            ))
        return results

    def failed(self, since: str | None = None, limit: int = 20) -> list[RunSummary]:
        """Shorthand for query(status="failed", ...)."""
        return self.query(status="failed", since=since, limit=limit)

    def __repr__(self) -> str:
        return "<HistoryCapability process() query() failed()>"
```

**Step 3: Run tests**

Run: `pytest tests/cogos/capabilities/test_history.py -v`
Expected: PASS

**Step 4: Commit**

```bash
git add src/cogos/capabilities/history.py tests/cogos/capabilities/test_history.py
git commit -m "feat: implement HistoryCapability with ProcessHistory, query, failed"
```

---

### Task 7: Add registry entry for `history`

**Files:**
- Modify: `src/cogos/capabilities/registry.py`

**Step 1: Add `history` entry to `BUILTIN_CAPABILITIES`**

Add after the `procs` entry:

```python
{
    "name": "history",
    "description": "Run history, file mutation tracking, and cross-process audit queries.",
    "handler": "cogos.capabilities.history.HistoryCapability",
    "instructions": (
        "Use history to query run history and file mutations.\n"
        "- h = history.process(name) — get handle for one process\n"
        "- h.runs(limit=10) — recent runs\n"
        "- h.files(run_id) — files mutated by a run\n"
        "- history.query(status?, process_name?, since?, limit=50) — cross-process query\n"
        "- history.failed(since?, limit=20) — shorthand for failed runs"
    ),
    "schema": {
        "scope": {
            "properties": {
                "ops": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["query", "process"]},
                },
                "process_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Restrict to these process IDs. Empty = all.",
                },
            },
        },
        "process": {
            "input": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Process name"},
                    "id": {"type": "string", "description": "Process UUID"},
                },
            },
            "output": {"type": "object", "description": "ProcessHistory handle or HistoryError"},
        },
        "query": {
            "input": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "description": "Filter by run status"},
                    "process_name": {"type": "string", "description": "Glob pattern on process name"},
                    "since": {"type": "string", "description": "ISO timestamp or duration like '1h'"},
                    "limit": {"type": "integer", "default": 50},
                },
            },
            "output": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "process_id": {"type": "string"},
                        "process_name": {"type": "string"},
                        "status": {"type": "string"},
                        "duration_ms": {"type": "integer"},
                        "tokens_in": {"type": "integer"},
                        "tokens_out": {"type": "integer"},
                        "cost_usd": {"type": "string"},
                        "error": {"type": "string"},
                        "result": {"type": "object"},
                        "model_version": {"type": "string"},
                        "created_at": {"type": "string"},
                        "completed_at": {"type": "string"},
                    },
                },
            },
        },
        "failed": {
            "input": {
                "type": "object",
                "properties": {
                    "since": {"type": "string"},
                    "limit": {"type": "integer", "default": 20},
                },
            },
            "output": {"type": "array"},
        },
    },
},
```

**Step 2: Verify registry loads**

Run: `python -c "from cogos.capabilities.registry import BUILTIN_CAPABILITIES; names = [c['name'] for c in BUILTIN_CAPABILITIES]; print('history' in names, len(names), 'capabilities')"`
Expected: `True N capabilities`

**Step 3: Commit**

```bash
git add src/cogos/capabilities/registry.py
git commit -m "feat: add history capability to registry"
```

---

### Task 8: Create cogware instructions include

**Files:**
- Create: `images/cogent-v1/cogos/includes/history.md`

**Step 1: Write include file**

```markdown
# History

Query run history and file mutations across processes.

## Per-process history

```python
h = history.process("worker-3")

# Recent runs
for run in h.runs(limit=5):
    print(f"{run.status} {run.duration_ms}ms {run.error or ''}")

# Files mutated by a run
for f in h.files(run_id=run.id):
    print(f"  {f.key} v{f.version}")
```

## Cross-process queries

```python
# All failed runs
for run in history.failed(since="1h"):
    print(f"{run.process_name}: {run.error}")

# Custom query
runs = history.query(
    process_name="worker-*",
    status="failed",
    since="2026-03-17T00:00",
    limit=50,
)
```

## Return types

- `RunSummary` — id, process_id, process_name, status, duration_ms, tokens_in, tokens_out, cost_usd, error, result, model_version, created_at, completed_at
- `FileMutation` — key, version, created_at
- `HistoryError` — error (string)

Check for errors: `if isinstance(result, HistoryError): print(result.error)`
```

**Step 2: Commit**

```bash
git add images/cogent-v1/cogos/includes/history.md
git commit -m "feat: add cogware history instructions include"
```

---

### Task 9: Grant `history` capability to cogent images

**Files:**
- Modify: `images/cogent-v1/cogos/init/capabilities.py` — register history capability
- Modify: relevant process definitions to grant `history` to supervisor (full access) and workers (self-only)

**Step 1: Find where capabilities are registered**

Look at existing capability registrations in `images/cogent-v1/cogos/init/capabilities.py` and follow the pattern.

**Step 2: Add `history` to supervisor with full access**

Grant `history` with no scope restriction (all ops, all process_ids).

**Step 3: Add `history` to workers with self-only scope**

Grant `history` with `ops=["process"]` and `process_ids=[self_process_id]`.

**Step 4: Commit**

```bash
git add images/cogent-v1/
git commit -m "feat: grant history capability to supervisor (full) and workers (self-only)"
```

---

### Task 10: Run full test suite and fix

**Step 1: Run all history-related tests**

Run: `pytest tests/cogos/capabilities/test_history.py tests/cogos/db/test_repo_history.py -v`
Expected: ALL PASS

**Step 2: Run broader test suite**

Run: `pytest tests/ -x -q`
Expected: No regressions

**Step 3: Fix any issues**

**Step 4: Final commit if needed**
