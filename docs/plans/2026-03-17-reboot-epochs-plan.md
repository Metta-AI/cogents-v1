# Reboot Epochs Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace destructive reboot with epoch-based filtering so history is preserved and optionally visible in the dashboard.

**Architecture:** Add `epoch: int` field to all process-table models (Process, Run, Handler, ProcessCapability, Delivery). The repo tracks a `reboot_epoch` counter; all query methods filter by current epoch by default. A new `CogosOperation` model logs system operations. The dashboard gets a "Show history" toggle that fetches all epochs and dims old rows.

**Tech Stack:** Python/Pydantic (backend models), FastAPI (API), React/TypeScript (dashboard frontend)

---

### Task 1: CogosOperation model

**Files:**
- Create: `src/cogos/db/models/operation.py`
- Modify: `src/cogos/db/models/__init__.py`

**Step 1: Create the CogosOperation model**

Create `src/cogos/db/models/operation.py`:

```python
"""CogosOperation model — log of system operations (reboot, reload, etc.)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class CogosOperation(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    epoch: int = 0
    type: str = ""  # "reboot", "reload", etc.
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
```

**Step 2: Export from models __init__**

Add to `src/cogos/db/models/__init__.py`:
```python
from cogos.db.models.operation import CogosOperation
```
And add `"CogosOperation"` to `__all__`.

**Step 3: Commit**

```bash
git add src/cogos/db/models/operation.py src/cogos/db/models/__init__.py
git commit -m "feat: add CogosOperation model for system operation log"
```

---

### Task 2: Add `epoch` field to epoch-scoped models

**Files:**
- Modify: `src/cogos/db/models/process.py`
- Modify: `src/cogos/db/models/run.py`
- Modify: `src/cogos/db/models/handler.py`
- Modify: `src/cogos/db/models/process_capability.py`
- Modify: `src/cogos/db/models/delivery.py`

**Step 1: Add `epoch: int = 0` to each model**

In each file, add after the `id` field:
```python
    epoch: int = 0
```

Models to modify:
- `Process` in `process.py` — add `epoch: int = 0` after `id: UUID = Field(default_factory=uuid4)`
- `Run` in `run.py` — add `epoch: int = 0` after `id: UUID = Field(default_factory=uuid4)`
- `Handler` in `handler.py` — add `epoch: int = 0` after `id: UUID = Field(default_factory=uuid4)`
- `ProcessCapability` in `process_capability.py` — add `epoch: int = 0` after `id: UUID = Field(default_factory=uuid4)`
- `Delivery` in `delivery.py` — add `epoch: int = 0` after `id: UUID = Field(default_factory=uuid4)`

**Step 2: Commit**

```bash
git add src/cogos/db/models/process.py src/cogos/db/models/run.py src/cogos/db/models/handler.py src/cogos/db/models/process_capability.py src/cogos/db/models/delivery.py
git commit -m "feat: add epoch field to all process-table models"
```

---

### Task 3: Add epoch support to LocalRepository

**Files:**
- Modify: `src/cogos/db/local_repository.py`
- Test: `tests/cogos/test_reboot.py`

**Step 1: Add sentinel and epoch state**

At the top of `local_repository.py`, after imports, add:

```python
ALL_EPOCHS = -1  # sentinel: return records from every epoch
```

In `LocalRepository.__init__`, add:
```python
        self._operations: dict[UUID, CogosOperation] = {}
        self._reboot_epoch: int = 0
```

Add `CogosOperation` to the imports from `cogos.db.models`.

**Step 2: Persist/restore epoch and operations**

In `_serialize_state`, add:
```python
            "operations": [op.model_dump(mode="json") for op in self._operations.values()],
            "reboot_epoch": self._reboot_epoch,
```

In `_populate_from_data`, add:
```python
        self._reboot_epoch = data.get("reboot_epoch", 0)
        for op in data.get("operations", []):
            operation = CogosOperation(**op)
            self._operations[operation.id] = operation
```

In `_reset_state`, add:
```python
        self._operations.clear()
        self._reboot_epoch = 0
```

In `_merge_serialized_data`, add to the `specs` dict:
```python
            "operations": (("id",), None),
```

And after the loop, add:
```python
        merged["reboot_epoch"] = max(
            latest_data.get("reboot_epoch", 0),
            current_data.get("reboot_epoch", 0),
        )
```

**Step 3: Add epoch property and operation methods**

```python
    @property
    def reboot_epoch(self) -> int:
        self._maybe_reload()
        return self._reboot_epoch

    def increment_epoch(self) -> int:
        with self._writing():
            self._reboot_epoch += 1
            return self._reboot_epoch

    def add_operation(self, op: CogosOperation) -> UUID:
        with self._writing():
            from datetime import UTC
            op.created_at = op.created_at or datetime.now(UTC)
            self._operations[op.id] = op
            return op.id

    def list_operations(self, limit: int = 50) -> list[CogosOperation]:
        self._maybe_reload()
        ops = list(self._operations.values())
        ops.sort(key=lambda o: o.created_at or datetime.min, reverse=True)
        return ops[:limit]
```

**Step 4: Add epoch filtering to query methods**

Modify `list_processes` to accept an `epoch` parameter:

```python
    def list_processes(self, *, status: ProcessStatus | None = None, limit: int = 200, epoch: int | None = None) -> list[Process]:
        self._maybe_reload()
        effective_epoch = self._reboot_epoch if epoch is None else epoch
        procs = list(self._processes.values())
        if effective_epoch != ALL_EPOCHS:
            procs = [p for p in procs if p.epoch == effective_epoch]
        if status:
            procs = [p for p in procs if p.status == status]
        procs.sort(key=lambda p: p.name)
        return procs[:limit]
```

Modify `get_runnable_processes` to filter by current epoch:

```python
    def get_runnable_processes(self, limit: int = 50) -> list[Process]:
        self._maybe_reload()
        runnable = [p for p in self._processes.values()
                    if p.status == ProcessStatus.RUNNABLE and p.epoch == self._reboot_epoch]
        runnable.sort(
            key=lambda p: (
                -p.priority,
                p.runnable_since or datetime.max,
                p.name,
            ),
        )
        return runnable[:limit]
```

Modify `list_runs` to accept an `epoch` parameter:

```python
    def list_runs(self, *, process_id: UUID | None = None, limit: int = 50, epoch: int | None = None) -> list[Run]:
        self._maybe_reload()
        effective_epoch = self._reboot_epoch if epoch is None else epoch
        runs = list(self._runs.values())
        if effective_epoch != ALL_EPOCHS:
            runs = [r for r in runs if r.epoch == effective_epoch]
        if process_id:
            runs = [r for r in runs if r.process == process_id]
        runs.sort(key=lambda r: r.created_at or datetime.min, reverse=True)
        return runs[:limit]
```

Modify `list_recent_failed_runs` to filter by current epoch:

```python
    def list_recent_failed_runs(self, max_age_ms: int = 120_000) -> list[Run]:
        self._maybe_reload()
        from datetime import timedelta
        cutoff = datetime.now(UTC) - timedelta(milliseconds=max_age_ms)
        result = []
        for run in self._runs.values():
            if run.epoch != self._reboot_epoch:
                continue
            if run.status in (RunStatus.FAILED, RunStatus.TIMEOUT):
                if run.completed_at and run.completed_at >= cutoff:
                    result.append(run)
                elif run.created_at and run.created_at >= cutoff:
                    result.append(run)
        return result
```

Modify `list_handlers` to accept an `epoch` parameter:

```python
    def list_handlers(self, *, process_id: UUID | None = None, enabled_only: bool = False, epoch: int | None = None) -> list[Handler]:
```
Add epoch filtering like list_processes (filter by `effective_epoch` unless `ALL_EPOCHS`).

Modify `list_deliveries` similarly.

**Step 5: Stamp epoch on creation**

In `upsert_process`, when creating a new process (the `else` branch where `existing is None`), add:
```python
                if not p.epoch:
                    p.epoch = self._reboot_epoch
```

In `create_run` (or wherever runs are created), stamp:
```python
            run.epoch = self._reboot_epoch
```

In `create_handler`, stamp:
```python
            handler.epoch = self._reboot_epoch
```

In `create_delivery` / `record_delivery`, stamp:
```python
            delivery.epoch = self._reboot_epoch
```

In `upsert_process_capability`, stamp:
```python
            pc.epoch = self._reboot_epoch
```

**Step 6: Commit**

```bash
git add src/cogos/db/local_repository.py
git commit -m "feat: add epoch filtering and operation log to LocalRepository"
```

---

### Task 4: Update reboot to use epochs

**Files:**
- Modify: `src/cogos/runtime/reboot.py`
- Modify: `tests/cogos/test_reboot.py`

**Step 1: Write the failing test**

Add to `tests/cogos/test_reboot.py`:

```python
def test_reboot_preserves_old_processes_in_previous_epoch(tmp_path):
    from cogos.db.local_repository import ALL_EPOCHS
    repo = LocalRepository(str(tmp_path))
    old = Process(name="scheduler", mode=ProcessMode.DAEMON, status=ProcessStatus.RUNNING)
    repo.upsert_process(old)
    run = Run(process=old.id, status=RunStatus.RUNNING)
    repo.create_run(run)

    reboot(repo)

    # Current epoch: only init
    procs = repo.list_processes()
    assert len(procs) == 1
    assert procs[0].name == "init"

    # All epochs: old + init
    all_procs = repo.list_processes(epoch=ALL_EPOCHS)
    assert len(all_procs) == 2
    names = {p.name for p in all_procs}
    assert names == {"scheduler", "init"}

    # Old runs still visible in all epochs
    all_runs = repo.list_runs(epoch=ALL_EPOCHS)
    assert len(all_runs) == 1

    # Current epoch runs: none (old run was epoch 0, new epoch is 1)
    current_runs = repo.list_runs()
    assert len(current_runs) == 0


def test_reboot_logs_operation(tmp_path):
    repo = LocalRepository(str(tmp_path))
    repo.upsert_process(Process(name="init", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.COMPLETED))

    reboot(repo)

    ops = repo.list_operations()
    assert len(ops) == 1
    assert ops[0].type == "reboot"
    assert ops[0].epoch == 1


def test_reboot_epoch_increments(tmp_path):
    repo = LocalRepository(str(tmp_path))

    reboot(repo)
    assert repo.reboot_epoch == 1

    reboot(repo)
    assert repo.reboot_epoch == 2

    procs = repo.list_processes()
    assert len(procs) == 1  # only the latest init
```

Add necessary imports at the top of the test file:
```python
from cogos.db.models import Run, RunStatus
from cogos.db.local_repository import ALL_EPOCHS
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/cogos/test_reboot.py -v -k "epoch or operation"`
Expected: FAIL

**Step 3: Update reboot.py**

Replace the contents of `src/cogos/runtime/reboot.py`:

```python
"""Reboot: increment epoch, log operation, re-create init."""

from __future__ import annotations

import logging

from cogos.db.models import Process, ProcessMode, ProcessStatus
from cogos.db.models.operation import CogosOperation

logger = logging.getLogger(__name__)

INIT_PROCESS_CONTENT = "@{cogos/init.py}"


def reboot(repo) -> dict:
    """Increment epoch, log operation, create fresh init process.

    Preserves: files, coglets, channels, schemas, resources, cron.
    Old processes/runs/handlers stay in previous epochs, invisible by default.
    """
    from cogos.db.local_repository import ALL_EPOCHS

    # 1. Find and disable init (cascade disables children)
    init = repo.get_process_by_name("init")
    if init:
        repo.update_process_status(init.id, ProcessStatus.DISABLED)

    # 2. Count current-epoch processes for reporting
    all_procs = repo.list_processes(epoch=ALL_EPOCHS)
    prev_count = len(all_procs)

    # 3. Increment epoch
    new_epoch = repo.increment_epoch()

    # 4. Log operation
    repo.add_operation(CogosOperation(
        epoch=new_epoch,
        type="reboot",
        metadata={"prev_process_count": prev_count},
    ))

    # 5. Create fresh init process (stamped with new epoch automatically)
    init_proc = Process(
        name="init",
        mode=ProcessMode.ONE_SHOT,
        content=INIT_PROCESS_CONTENT,
        executor="python",
        priority=200.0,
        runner="lambda",
        status=ProcessStatus.RUNNABLE,
    )
    repo.upsert_process(init_proc)

    logger.info("Reboot complete: epoch=%d, prev_processes=%d", new_epoch, prev_count)
    return {"cleared_processes": prev_count, "epoch": new_epoch}
```

**Step 4: Update existing tests**

Update `test_reboot_clears_processes_and_creates_init` — it currently checks `len(procs) == 1` which is the current-epoch view, which should still pass. Update the assertion comment and verify it works.

Update `test_reboot_endpoint` in `tests/dashboard/test_reboot.py` to also check for the `epoch` key in the response.

**Step 5: Run all reboot tests**

Run: `pytest tests/cogos/test_reboot.py tests/dashboard/test_reboot.py -v`
Expected: PASS

**Step 6: Commit**

```bash
git add src/cogos/runtime/reboot.py tests/cogos/test_reboot.py tests/dashboard/test_reboot.py
git commit -m "feat: reboot uses epoch increment instead of deleting records"
```

---

### Task 5: Add epoch support to SQL Repository

**Files:**
- Modify: `src/cogos/db/repository.py`

**Step 1: Add epoch state and sentinel**

At the top of `repository.py`, add after imports:
```python
ALL_EPOCHS = -1
```

Add to the Repository class:
- `reboot_epoch` property that reads from a `cogos_meta` key
- `increment_epoch()` method
- `add_operation()` and `list_operations()` methods
- Add epoch filtering to `list_processes`, `get_runnable_processes`, `list_runs`, `list_handlers`, `list_deliveries`, `list_recent_failed_runs`
- Stamp `epoch` in `upsert_process`, `create_run`, `create_handler`, `record_delivery`, `upsert_process_capability`

For the SQL repo, epoch is stored in the meta table as `"reboot_epoch"`. The `reboot_epoch` property reads it:

```python
    @property
    def reboot_epoch(self) -> int:
        meta = self.get_meta("reboot_epoch")
        if meta and meta.get("value"):
            return int(meta["value"])
        return 0

    def increment_epoch(self) -> int:
        new_epoch = self.reboot_epoch + 1
        self.set_meta("reboot_epoch", str(new_epoch))
        return new_epoch
```

For `list_processes`, add the epoch filter to SQL:
```python
    def list_processes(
        self, *, status: ProcessStatus | None = None, limit: int = 200, epoch: int | None = None,
    ) -> list[Process]:
        effective_epoch = self.reboot_epoch if epoch is None else epoch
        conditions = []
        params = [self._param("limit", limit)]
        if effective_epoch != ALL_EPOCHS:
            conditions.append("epoch = :epoch")
            params.append(self._param("epoch", effective_epoch))
        if status:
            conditions.append("status = :status")
            params.append(self._param("status", status.value))
        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        response = self._execute(
            f"SELECT * FROM cogos_process{where} ORDER BY name LIMIT :limit",
            params,
        )
        return [self._process_from_row(r) for r in self._rows_to_dicts(response)]
```

Apply similar patterns to `get_runnable_processes` (hardcode `epoch = self.reboot_epoch`), `list_runs`, `list_handlers`, `list_deliveries`, `list_recent_failed_runs`.

For `upsert_process`, add `epoch` to the INSERT columns and values.

**Note:** The SQL schema migration (ALTER TABLE ADD COLUMN epoch) will need to be handled. Add `epoch` with `DEFAULT 0` to the INSERT/upsert statements. For the operations table, add a CREATE TABLE if not exists.

For the `cogos_operation` table, add a helper that creates it:
```sql
CREATE TABLE IF NOT EXISTS cogos_operation (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    epoch INTEGER NOT NULL DEFAULT 0,
    type TEXT NOT NULL DEFAULT '',
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now()
)
```

**Step 2: Commit**

```bash
git add src/cogos/db/repository.py
git commit -m "feat: add epoch filtering and operation log to SQL Repository"
```

---

### Task 6: Add epoch to dashboard API endpoints

**Files:**
- Modify: `src/dashboard/routers/processes.py`
- Modify: `src/dashboard/routers/runs.py`
- Modify: `src/dashboard/routers/cogos_status.py`
- Create: `src/dashboard/routers/operations.py`

**Step 1: Add epoch param to processes endpoint**

In `src/dashboard/routers/processes.py`, modify `list_processes`:

```python
from cogos.db.local_repository import ALL_EPOCHS

@router.get("/processes", response_model=ProcessesResponse)
def list_processes(
    name: str,
    status: str | None = Query(None, description="Filter by process status"),
    epoch: str | None = Query(None, description="Epoch filter: omit for current, 'all' for all epochs"),
) -> ProcessesResponse:
    repo = get_repo()
    ps = ProcessStatus(status) if status else None
    ep = ALL_EPOCHS if epoch == "all" else None
    procs = repo.list_processes(status=ps, epoch=ep)
    details = [_detail(p) for p in procs]
    return ProcessesResponse(cogent_name=name, count=len(details), processes=details)
```

Add `epoch: int = 0` to the `ProcessDetail` response model so the frontend knows each process's epoch.

In `_detail()`, add:
```python
        epoch=p.epoch,
```

**Step 2: Add epoch param to runs endpoint**

In `src/dashboard/routers/runs.py`, modify `list_runs`:

```python
from cogos.db.local_repository import ALL_EPOCHS

@router.get("/runs", response_model=RunsResponse)
def list_runs(
    name: str,
    process: str | None = Query(None, description="Filter by process UUID"),
    limit: int = Query(50, ge=1, le=500),
    epoch: str | None = Query(None, description="Epoch filter: omit for current, 'all' for all epochs"),
) -> RunsResponse:
    repo = get_repo()
    pid = UUID(process) if process else None
    ep = ALL_EPOCHS if epoch == "all" else None
    items = repo.list_runs(process_id=pid, limit=limit, epoch=ep)
    proc_epoch = ALL_EPOCHS if epoch == "all" else None
    processes = repo.list_processes(epoch=proc_epoch)
    process_names = {p.id: p.name for p in processes}
    process_runners = {p.id: p.runner for p in processes}
    out = [_summary(r, process_names, process_runners) for r in items]
    return RunsResponse(count=len(out), runs=out)
```

Add `epoch: int = 0` to `RunSummary` model and populate it in `_summary()`.

**Step 3: Add epoch to cogos-status**

In `src/dashboard/routers/cogos_status.py`, add epoch param and expose `reboot_epoch` in the response:

```python
from cogos.db.local_repository import ALL_EPOCHS

class CogosStatusResponse(BaseModel):
    # ... existing fields ...
    reboot_epoch: int = 0

@router.get("/cogos-status", response_model=CogosStatusResponse)
def cogos_status(
    name: str,
    epoch: str | None = Query(None),
) -> CogosStatusResponse:
    repo = get_repo()
    ep = ALL_EPOCHS if epoch == "all" else None
    all_procs = repo.list_processes(epoch=ep)
    # ... rest uses ep for runs too ...
    return CogosStatusResponse(
        # ... existing fields ...
        reboot_epoch=repo.reboot_epoch,
    )
```

**Step 4: Create operations endpoint**

Create `src/dashboard/routers/operations.py`:

```python
from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel

from dashboard.db import get_repo

router = APIRouter(tags=["cogos-operations"])


class OperationSummary(BaseModel):
    id: str
    epoch: int
    type: str
    metadata: dict
    created_at: str | None = None


class OperationsResponse(BaseModel):
    count: int
    operations: list[OperationSummary]


@router.get("/operations", response_model=OperationsResponse)
def list_operations(
    name: str,
    limit: int = Query(50, ge=1, le=200),
) -> OperationsResponse:
    repo = get_repo()
    ops = repo.list_operations(limit=limit)
    out = [
        OperationSummary(
            id=str(op.id),
            epoch=op.epoch,
            type=op.type,
            metadata=op.metadata,
            created_at=op.created_at.isoformat() if op.created_at else None,
        )
        for op in ops
    ]
    return OperationsResponse(count=len(out), operations=out)
```

Register this router in the dashboard app (find where routers are included and add it).

**Step 5: Commit**

```bash
git add src/dashboard/routers/processes.py src/dashboard/routers/runs.py src/dashboard/routers/cogos_status.py src/dashboard/routers/operations.py
git commit -m "feat: add epoch param to dashboard API endpoints, add operations endpoint"
```

---

### Task 7: Frontend — types and API

**Files:**
- Modify: `dashboard/frontend/src/lib/types.ts`
- Modify: `dashboard/frontend/src/lib/api.ts`

**Step 1: Update types**

Add `epoch` to `CogosProcess`:
```typescript
  epoch: number;
```

Add `epoch` to `CogosRun`:
```typescript
  epoch: number;
```

Add `reboot_epoch` to `CogosStatus`:
```typescript
  reboot_epoch: number;
```

Add new types:
```typescript
export interface CogosOperation {
  id: string;
  epoch: number;
  type: string;
  metadata: Record<string, unknown>;
  created_at: string | null;
}
```

**Step 2: Update API functions**

Modify `getProcesses` to accept optional epoch param:
```typescript
export async function getProcesses(name: string, epoch?: string): Promise<CogosProcess[]> {
  const params = epoch ? `?epoch=${epoch}` : "";
  const r = await fetchJSON<{ processes: CogosProcess[] }>(
    `/api/cogents/${name}/processes${params}`,
  );
  return r.processes;
}
```

Modify `getRuns` similarly:
```typescript
export async function getRuns(name: string, epoch?: string): Promise<CogosRun[]> {
  const params = epoch ? `?epoch=${epoch}` : "";
  const r = await fetchJSON<{ runs: CogosRun[] }>(
    `/api/cogents/${name}/runs${params}`,
  );
  return r.runs;
}
```

Modify `getCogosStatus` similarly.

Add new function:
```typescript
export async function getOperations(name: string): Promise<CogosOperation[]> {
  const r = await fetchJSON<{ operations: CogosOperation[] }>(
    `/api/cogents/${name}/operations`,
  );
  return r.operations;
}
```

**Step 3: Commit**

```bash
git add dashboard/frontend/src/lib/types.ts dashboard/frontend/src/lib/api.ts
git commit -m "feat: add epoch to frontend types and API functions"
```

---

### Task 8: Frontend — Header toggle and data hook

**Files:**
- Modify: `dashboard/frontend/src/hooks/useCogentData.ts`
- Modify: `dashboard/frontend/src/components/Header.tsx`
- Modify: `dashboard/frontend/src/app/page.tsx`

**Step 1: Add showHistory state to useCogentData**

In `useCogentData.ts`, add state:
```typescript
const [showHistory, setShowHistory] = useState(false);
```

Pass epoch to API calls:
```typescript
const epochParam = showHistory ? "all" : undefined;
```

Update the `refresh` callback to use `epochParam` in `getProcesses`, `getRuns`, and `getCogosStatus` calls.

Return `showHistory` and `setShowHistory` from the hook.

**Step 2: Add toggle to Header**

In `Header.tsx`, add to `HeaderProps`:
```typescript
  showHistory: boolean;
  onShowHistoryChange: (show: boolean) => void;
```

Add a checkbox next to the RebootButton:
```tsx
<label
  style={{
    display: "flex",
    alignItems: "center",
    gap: "4px",
    fontSize: "10px",
    fontFamily: "var(--font-mono)",
    color: "var(--text-muted)",
    cursor: "pointer",
  }}
>
  <input
    type="checkbox"
    checked={showHistory}
    onChange={(e) => onShowHistoryChange(e.target.checked)}
    style={{ margin: 0 }}
  />
  history
</label>
```

Place this between the time range picker and the reboot button in the right side of the header.

**Step 3: Wire it up in page.tsx**

Pass `showHistory` and `setShowHistory` from `useCogentData` through to `Header`.

**Step 4: Commit**

```bash
git add dashboard/frontend/src/hooks/useCogentData.ts dashboard/frontend/src/components/Header.tsx dashboard/frontend/src/app/page.tsx
git commit -m "feat: add 'history' toggle in dashboard header"
```

---

### Task 9: Frontend — dim old epoch rows

**Files:**
- Modify: `dashboard/frontend/src/components/processes/ProcessesPanel.tsx`
- Modify: `dashboard/frontend/src/components/runs/RunsPanel.tsx`
- Modify: `dashboard/frontend/src/app/page.tsx`

**Step 1: Pass currentEpoch to panels**

From `useCogentData`, the `cogosStatus.reboot_epoch` value is available. Pass it down as a prop to `ProcessesPanel` and `RunsPanel`.

**Step 2: Dim old rows in ProcessesPanel**

Add `currentEpoch: number` to the `Props` interface.

Where process rows are rendered, add conditional opacity:
```tsx
style={{ opacity: process.epoch < currentEpoch ? 0.5 : 1 }}
```

**Step 3: Dim old rows in RunsPanel**

Same pattern: add `currentEpoch` prop, apply `opacity: 0.5` to rows where `run.epoch < currentEpoch`.

**Step 4: Commit**

```bash
git add dashboard/frontend/src/components/processes/ProcessesPanel.tsx dashboard/frontend/src/components/runs/RunsPanel.tsx dashboard/frontend/src/app/page.tsx
git commit -m "feat: dim old-epoch rows in processes and runs panels"
```

---

### Task 10: Remove clear_process_tables

**Files:**
- Modify: `src/cogos/db/local_repository.py`
- Modify: `src/cogos/db/repository.py`

**Step 1: Remove the method**

Remove `clear_process_tables` from both `LocalRepository` and `Repository`.

Keep `clear_all` and `clear_config` (they're used elsewhere and are separate concerns).

**Step 2: Search for remaining callers**

Run: `grep -r "clear_process_tables" src/ tests/`

If any other callers exist, update them to use the epoch-based reboot flow.

**Step 3: Run full test suite**

Run: `pytest tests/cogos/ tests/dashboard/ -v`
Expected: PASS (the reboot tests should use the new epoch flow)

**Step 4: Commit**

```bash
git add src/cogos/db/local_repository.py src/cogos/db/repository.py
git commit -m "refactor: remove clear_process_tables, replaced by epoch-based reboot"
```

---

### Task 11: Run all tests and fix

**Step 1: Run full test suite**

Run: `pytest tests/ -v --tb=short`

**Step 2: Fix any failures**

Common issues to look for:
- Tests that check `len(repo.list_processes())` after creating processes — if they don't set epoch, they'll be epoch 0 and a test that reboots then lists may get wrong counts
- Tests that use `clear_process_tables` directly
- API tests that need updated response models

**Step 3: Commit fixes**

```bash
git add -A
git commit -m "fix: update tests for epoch-based reboot"
```
