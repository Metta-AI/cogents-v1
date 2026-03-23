# Process Wait Conditions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `wait()`, `wait_any()`, `wait_all()` process synchronization to CogOS so a parent can suspend until children complete.

**Architecture:** New `cogos_wait_condition` table tracks pending waits. `ProcessHandle.wait*()` methods become side-effecting: write the condition row, raise `WaitSuspend` to end the run. Delivery gating in the repository checks wait conditions before waking processes. Resume enriches event data with child exit payloads.

**Tech Stack:** Python, Pydantic models, PostgreSQL/SQLite, pytest

**Spec:** `docs/superpowers/specs/2026-03-23-process-wait-conditions-design.md`

---

### Task 1: WaitCondition model and migration

**Files:**
- Create: `src/cogos/db/models/wait_condition.py`
- Modify: `src/cogos/db/models/__init__.py`
- Create: `src/cogos/db/migrations/021_wait_condition.sql`
- Test: `tests/cogos/db/test_wait_condition_model.py`

- [ ] **Step 1: Write the model**

Create `src/cogos/db/models/wait_condition.py`:

```python
"""WaitCondition model — tracks process wait-for-children conditions."""

from __future__ import annotations

import enum
from datetime import datetime
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class WaitConditionStatus(str, enum.Enum):
    PENDING = "pending"
    RESOLVED = "resolved"


class WaitConditionType(str, enum.Enum):
    WAIT = "wait"
    WAIT_ANY = "wait_any"
    WAIT_ALL = "wait_all"


class WaitCondition(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    run: UUID  # FK -> Run.id
    type: WaitConditionType
    status: WaitConditionStatus = WaitConditionStatus.PENDING
    pending: list[str] = Field(default_factory=list)  # process UUIDs still awaited
    created_at: datetime | None = None
```

- [ ] **Step 2: Export from models `__init__.py`**

Add to `src/cogos/db/models/__init__.py` (after line 19, the `Run` import):

```python
from cogos.db.models.wait_condition import WaitCondition, WaitConditionStatus, WaitConditionType
```

And add `"WaitCondition"`, `"WaitConditionStatus"`, `"WaitConditionType"` to the `__all__` list.

- [ ] **Step 3: Write the migration**

Create `src/cogos/db/migrations/021_wait_condition.sql`:

```sql
-- Process wait conditions for wait/wait_any/wait_all synchronization.

CREATE TABLE IF NOT EXISTS cogos_wait_condition (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run        UUID NOT NULL REFERENCES cogos_run(id),
    type       TEXT NOT NULL CHECK (type IN ('wait', 'wait_any', 'wait_all')),
    status     TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'resolved')),
    pending    JSONB NOT NULL DEFAULT '[]',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_wait_condition_run ON cogos_wait_condition(run);
CREATE INDEX IF NOT EXISTS idx_wait_condition_status ON cogos_wait_condition(status) WHERE status = 'pending';
```

- [ ] **Step 4: Write model test**

Create `tests/cogos/db/test_wait_condition_model.py`:

```python
from cogos.db.models import WaitCondition, WaitConditionStatus, WaitConditionType


def test_wait_condition_defaults():
    from uuid import uuid4
    wc = WaitCondition(run=uuid4(), type=WaitConditionType.WAIT_ALL, pending=["a", "b"])
    assert wc.status == WaitConditionStatus.PENDING
    assert wc.pending == ["a", "b"]
    assert wc.type == WaitConditionType.WAIT_ALL
```

- [ ] **Step 5: Run test**

Run: `pytest tests/cogos/db/test_wait_condition_model.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/cogos/db/models/wait_condition.py src/cogos/db/models/__init__.py \
  src/cogos/db/migrations/021_wait_condition.sql tests/cogos/db/test_wait_condition_model.py
git commit -m "add WaitCondition model and migration"
```

---

### Task 2: Repository methods for wait conditions

**Files:**
- Modify: `src/cogos/db/repository.py`
- Modify: `src/cogos/db/local_repository.py`
- Test: `tests/cogos/db/test_wait_condition_repo.py`

- [ ] **Step 1: Add repository methods to `src/cogos/db/repository.py`**

Add these methods to the `Repository` class (after `update_process_status` around line 542):

```python
def create_wait_condition(self, wc: WaitCondition) -> UUID:
    """Insert a new wait condition."""
    self._execute(
        """INSERT INTO cogos_wait_condition (id, run, type, status, pending)
           VALUES (:id, :run, :type, :status, :pending::jsonb)""",
        [
            self._param("id", wc.id),
            self._param("run", wc.run),
            self._param("type", wc.type.value),
            self._param("status", wc.status.value),
            self._param("pending", wc.pending),
        ],
    )
    return wc.id

def get_pending_wait_condition_for_process(self, process_id: UUID) -> WaitCondition | None:
    """Find an active (pending) wait condition for a process, joining through run."""
    row = self._first_row(self._execute(
        """SELECT wc.* FROM cogos_wait_condition wc
           JOIN cogos_run r ON wc.run = r.id
           WHERE r.process = :process_id AND wc.status = 'pending'
           LIMIT 1""",
        [self._param("process_id", process_id)],
    ))
    if not row:
        return None
    return WaitCondition(
        id=UUID(row["id"]),
        run=UUID(row["run"]),
        type=WaitConditionType(row["type"]),
        status=WaitConditionStatus(row["status"]),
        pending=self._parse_json(row.get("pending", "[]")),
        created_at=self._ts(row, "created_at"),
    )

def remove_from_pending(self, wc_id: UUID, child_pid: str) -> list[str]:
    """Atomically remove a child PID from pending and return the updated list."""
    row = self._first_row(self._execute(
        """UPDATE cogos_wait_condition
           SET pending = pending - :child_pid::jsonb
           WHERE id = :id
           RETURNING pending""",
        [self._param("id", wc_id), self._param("child_pid", f'"{child_pid}"')],
    ))
    return self._parse_json(row["pending"]) if row else []

def resolve_wait_condition(self, wc_id: UUID) -> None:
    """Mark a wait condition as resolved."""
    self._execute(
        "UPDATE cogos_wait_condition SET status = 'resolved' WHERE id = :id",
        [self._param("id", wc_id)],
    )

def resolve_wait_conditions_for_process(self, process_id: UUID) -> None:
    """Resolve all pending wait conditions for a process (orphan cleanup)."""
    self._execute(
        """UPDATE cogos_wait_condition SET status = 'resolved'
           WHERE status = 'pending' AND run IN (
               SELECT id FROM cogos_run WHERE process = :process_id
           )""",
        [self._param("process_id", process_id)],
    )
```

Add imports at the top of `repository.py`:

```python
from cogos.db.models.wait_condition import WaitCondition, WaitConditionStatus, WaitConditionType
```

- [ ] **Step 2: Add local repository methods to `src/cogos/db/local_repository.py`**

Add to the `LocalRepository` class (in-memory dict storage):

```python
def create_wait_condition(self, wc: WaitCondition) -> UUID:
    with self._writing():
        if wc.created_at is None:
            wc.created_at = datetime.now(UTC)
        self._wait_conditions[wc.id] = wc
        return wc.id

def get_pending_wait_condition_for_process(self, process_id: UUID) -> WaitCondition | None:
    self._maybe_reload()
    for wc in self._wait_conditions.values():
        if wc.status != WaitConditionStatus.PENDING:
            continue
        run = self._runs.get(wc.run)
        if run and run.process == process_id:
            return wc
    return None

def remove_from_pending(self, wc_id: UUID, child_pid: str) -> list[str]:
    with self._writing():
        wc = self._wait_conditions.get(wc_id)
        if not wc:
            return []
        wc.pending = [p for p in wc.pending if p != child_pid]
        return list(wc.pending)

def resolve_wait_condition(self, wc_id: UUID) -> None:
    with self._writing():
        wc = self._wait_conditions.get(wc_id)
        if wc:
            wc.status = WaitConditionStatus.RESOLVED

def resolve_wait_conditions_for_process(self, process_id: UUID) -> None:
    with self._writing():
        for wc in self._wait_conditions.values():
            if wc.status != WaitConditionStatus.PENDING:
                continue
            run = self._runs.get(wc.run)
            if run and run.process == process_id:
                wc.status = WaitConditionStatus.RESOLVED
```

Also add `_wait_conditions: dict[UUID, WaitCondition] = {}` to the `LocalRepository.__init__` method (in the dict initialization section), and add the import for `WaitCondition, WaitConditionStatus`.

- [ ] **Step 3: Write repository tests**

Create `tests/cogos/db/test_wait_condition_repo.py` testing the local repository path:

```python
"""Tests for WaitCondition repository methods."""
from uuid import uuid4

import pytest

from cogos.db.local_repository import LocalRepository
from cogos.db.models import Process, ProcessMode, ProcessStatus, Run, RunStatus
from cogos.db.models.wait_condition import WaitCondition, WaitConditionStatus, WaitConditionType


@pytest.fixture
def repo():
    return LocalRepository()


@pytest.fixture
def process_and_run(repo):
    proc = Process(name="parent", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.RUNNING)
    repo.upsert_process(proc)
    run = Run(process=proc.id, status=RunStatus.RUNNING)
    repo.create_run(run)
    return proc, run


def test_create_and_get_pending(repo, process_and_run):
    proc, run = process_and_run
    child_a, child_b = uuid4(), uuid4()
    wc = WaitCondition(run=run.id, type=WaitConditionType.WAIT_ALL, pending=[str(child_a), str(child_b)])
    repo.create_wait_condition(wc)

    found = repo.get_pending_wait_condition_for_process(proc.id)
    assert found is not None
    assert found.type == WaitConditionType.WAIT_ALL
    assert len(found.pending) == 2


def test_remove_from_pending(repo, process_and_run):
    _proc, run = process_and_run
    child_a, child_b = str(uuid4()), str(uuid4())
    wc = WaitCondition(run=run.id, type=WaitConditionType.WAIT_ALL, pending=[child_a, child_b])
    repo.create_wait_condition(wc)

    remaining = repo.remove_from_pending(wc.id, child_a)
    assert remaining == [child_b]


def test_resolve(repo, process_and_run):
    proc, run = process_and_run
    wc = WaitCondition(run=run.id, type=WaitConditionType.WAIT, pending=[str(uuid4())])
    repo.create_wait_condition(wc)

    repo.resolve_wait_condition(wc.id)
    assert repo.get_pending_wait_condition_for_process(proc.id) is None


def test_resolve_for_process_orphan_cleanup(repo, process_and_run):
    proc, run = process_and_run
    wc = WaitCondition(run=run.id, type=WaitConditionType.WAIT_ALL, pending=[str(uuid4())])
    repo.create_wait_condition(wc)

    repo.resolve_wait_conditions_for_process(proc.id)
    assert repo.get_pending_wait_condition_for_process(proc.id) is None
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/cogos/db/test_wait_condition_repo.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/cogos/db/repository.py src/cogos/db/local_repository.py tests/cogos/db/test_wait_condition_repo.py
git commit -m "add wait condition repository methods"
```

---

### Task 3: WaitSuspend exception and sandbox propagation

**Files:**
- Modify: `src/cogos/sandbox/executor.py`
- Test: `tests/cogos/sandbox/test_wait_suspend.py`

- [ ] **Step 1: Add WaitSuspend to sandbox/executor.py**

Add after line 22 (after `_SandboxExit`), in `src/cogos/sandbox/executor.py`:

```python
class WaitSuspend(Exception):
    """Raised by wait()/wait_any()/wait_all() to suspend and resume later."""
    pass
```

Do NOT add `WaitSuspend` to the `except` block in `execute()` (line 240). It must propagate out of the sandbox so the handler can catch it. The current code catches `_SandboxExit` at line 238 and `Exception` at line 240. `WaitSuspend` inherits from `Exception`, so add a re-raise before the generic `except`:

At line 238-243 in `execute()`, change from:

```python
        except _SandboxExit:
            pass  # Clean exit requested by sandbox code
        except Exception:
            error = traceback.format_exc()
            stderr_buf.write(error)
            self.error = error
```

to:

```python
        except _SandboxExit:
            pass  # Clean exit requested by sandbox code
        except WaitSuspend:
            raise  # Propagate to handler for session checkpoint
        except Exception:
            error = traceback.format_exc()
            stderr_buf.write(error)
            self.error = error
```

- [ ] **Step 2: Write test**

Create `tests/cogos/sandbox/test_wait_suspend.py`:

```python
"""WaitSuspend propagates out of SandboxExecutor.execute()."""
import pytest

from cogos.sandbox.executor import SandboxExecutor, VariableTable, WaitSuspend


def test_wait_suspend_propagates():
    vt = VariableTable()
    sandbox = SandboxExecutor(vt)
    with pytest.raises(WaitSuspend):
        sandbox.execute("from cogos.sandbox.executor import WaitSuspend; raise WaitSuspend()")


def test_sandbox_exit_does_not_propagate():
    vt = VariableTable()
    sandbox = SandboxExecutor(vt)
    result = sandbox.execute("exit()")
    assert sandbox.error is None


def test_normal_exception_captured():
    vt = VariableTable()
    sandbox = SandboxExecutor(vt)
    result = sandbox.execute("raise ValueError('boom')")
    assert sandbox.error is not None
    assert "boom" in result
```

- [ ] **Step 3: Run tests**

Run: `pytest tests/cogos/sandbox/test_wait_suspend.py -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/cogos/sandbox/executor.py tests/cogos/sandbox/test_wait_suspend.py
git commit -m "add WaitSuspend exception that propagates from sandbox"
```

---

### Task 4: Side-effecting ProcessHandle.wait/wait_any/wait_all

**Files:**
- Modify: `src/cogos/capabilities/process_handle.py`
- Modify: `tests/cogos/capabilities/test_process_handle.py`

- [ ] **Step 1: Add `_run_id` and early-exit helper to ProcessHandle**

In `src/cogos/capabilities/process_handle.py`, update `__init__` (line 36) to accept `run_id`:

```python
def __init__(
    self,
    repo,
    caller_process_id: UUID,
    process,
    send_channel: Channel | None,
    recv_channel: Channel | None,
    run_id: UUID | None = None,
):
    self._repo = repo
    self._caller_id = caller_process_id
    self._process = process
    self._send_channel = send_channel
    self._recv_channel = recv_channel
    self._run_id = run_id
```

Add the early-exit helper method:

```python
def _child_already_exited(self, child_pid: UUID) -> bool:
    """Check if child already sent a child:exited message on the spawn channel."""
    ch = self._repo.get_channel_by_name(f"spawn:{child_pid}\u2192{self._caller_id}")
    if not ch:
        return False
    msgs = self._repo.list_channel_messages(ch.id, limit=50)
    return any(
        isinstance(m.payload, dict) and m.payload.get("type") == "child:exited"
        for m in msgs
    )
```

Add the import at the top of the file:

```python
from cogos.sandbox.executor import WaitSuspend
```

And the import for the WaitCondition model:

```python
from cogos.db.models.wait_condition import WaitCondition, WaitConditionType
```

- [ ] **Step 2: Replace wait/wait_any/wait_all**

Replace the current `wait()` method (line 115-117) with:

```python
def wait(self) -> None:
    """Suspend until child exits. Returns immediately if child already exited."""
    if self._child_already_exited(self._process.id):
        return
    if self._run_id is None:
        raise RuntimeError("wait() requires run_id on ProcessHandle")
    self._repo.create_wait_condition(WaitCondition(
        run=self._run_id,
        type=WaitConditionType.WAIT,
        pending=[str(self._process.id)],
    ))
    raise WaitSuspend()
```

Replace `wait_any` (lines 119-121):

```python
@staticmethod
def wait_any(handles: list[ProcessHandle]) -> None:
    """Suspend until any child exits. Returns immediately if any already exited."""
    if any(h._child_already_exited(h._process.id) for h in handles):
        return
    repo = handles[0]._repo
    run_id = handles[0]._run_id
    if run_id is None:
        raise RuntimeError("wait_any() requires run_id on ProcessHandle")
    repo.create_wait_condition(WaitCondition(
        run=run_id,
        type=WaitConditionType.WAIT_ANY,
        pending=[h.id for h in handles],
    ))
    raise WaitSuspend()
```

Replace `wait_all` (lines 123-125):

```python
@staticmethod
def wait_all(handles: list[ProcessHandle]) -> None:
    """Suspend until all children exit. Returns immediately if all already exited."""
    still_pending = [h.id for h in handles if not h._child_already_exited(h._process.id)]
    if not still_pending:
        return
    repo = handles[0]._repo
    run_id = handles[0]._run_id
    if run_id is None:
        raise RuntimeError("wait_all() requires run_id on ProcessHandle")
    repo.create_wait_condition(WaitCondition(
        run=run_id,
        type=WaitConditionType.WAIT_ALL,
        pending=still_pending,
    ))
    raise WaitSuspend()
```

- [ ] **Step 3: Update tests**

In `tests/cogos/capabilities/test_process_handle.py`, update `TestWait` class. The tests now need to account for `run_id` and the side-effecting behavior:

```python
from cogos.sandbox.executor import WaitSuspend
from cogos.db.models.wait_condition import WaitCondition


class TestWait:
    def test_wait_suspends(self, repo, parent_id, child_process):
        run_id = uuid4()
        repo.get_channel_by_name.return_value = None  # no exited message
        repo.list_channel_messages.return_value = []
        handle = ProcessHandle(
            repo=repo, caller_process_id=parent_id, process=child_process,
            send_channel=None, recv_channel=None, run_id=run_id,
        )
        with pytest.raises(WaitSuspend):
            handle.wait()
        repo.create_wait_condition.assert_called_once()

    def test_wait_returns_if_child_already_exited(self, repo, parent_id, child_process):
        run_id = uuid4()
        ch = Channel(name="spawn", owner_process=child_process.id, channel_type=ChannelType.SPAWN)
        repo.get_channel_by_name.return_value = ch
        repo.list_channel_messages.return_value = [
            ChannelMessage(channel=ch.id, sender_process=child_process.id,
                           payload={"type": "child:exited", "exit_code": 0}),
        ]
        handle = ProcessHandle(
            repo=repo, caller_process_id=parent_id, process=child_process,
            send_channel=None, recv_channel=None, run_id=run_id,
        )
        handle.wait()  # should NOT raise
        repo.create_wait_condition.assert_not_called()

    def test_wait_any_suspends(self, repo, parent_id):
        run_id = uuid4()
        p1 = Process(name="a", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.RUNNING)
        p2 = Process(name="b", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.RUNNING)
        repo.get_channel_by_name.return_value = None
        repo.list_channel_messages.return_value = []
        h1 = ProcessHandle(repo=repo, caller_process_id=parent_id, process=p1,
                           send_channel=None, recv_channel=None, run_id=run_id)
        h2 = ProcessHandle(repo=repo, caller_process_id=parent_id, process=p2,
                           send_channel=None, recv_channel=None, run_id=run_id)
        with pytest.raises(WaitSuspend):
            ProcessHandle.wait_any([h1, h2])

    def test_wait_all_suspends(self, repo, parent_id):
        run_id = uuid4()
        p1 = Process(name="a", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.RUNNING)
        p2 = Process(name="b", mode=ProcessMode.ONE_SHOT, status=ProcessStatus.RUNNING)
        repo.get_channel_by_name.return_value = None
        repo.list_channel_messages.return_value = []
        h1 = ProcessHandle(repo=repo, caller_process_id=parent_id, process=p1,
                           send_channel=None, recv_channel=None, run_id=run_id)
        h2 = ProcessHandle(repo=repo, caller_process_id=parent_id, process=p2,
                           send_channel=None, recv_channel=None, run_id=run_id)
        with pytest.raises(WaitSuspend):
            ProcessHandle.wait_all([h1, h2])

    def test_wait_without_run_id_raises(self, repo, parent_id, child_process):
        repo.get_channel_by_name.return_value = None
        handle = ProcessHandle(
            repo=repo, caller_process_id=parent_id, process=child_process,
            send_channel=None, recv_channel=None,
        )
        with pytest.raises(RuntimeError, match="requires run_id"):
            handle.wait()
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/cogos/capabilities/test_process_handle.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/cogos/capabilities/process_handle.py tests/cogos/capabilities/test_process_handle.py
git commit -m "make wait/wait_any/wait_all side-effecting with early-exit"
```

---

### Task 5: Thread run_id into ProcessHandle construction

**Files:**
- Modify: `src/cogos/capabilities/procs.py`

- [ ] **Step 1: Update `get()` to pass run_id**

In `src/cogos/capabilities/procs.py`, at line 115, change the ProcessHandle construction in `get()`:

From:
```python
return ProcessHandle(
    repo=self.repo,
    caller_process_id=self.process_id,
    process=proc,
    send_channel=send_ch,
    recv_channel=recv_ch,
)
```

To:
```python
return ProcessHandle(
    repo=self.repo,
    caller_process_id=self.process_id,
    process=proc,
    send_channel=send_ch,
    recv_channel=recv_ch,
    run_id=self.run_id,
)
```

- [ ] **Step 2: Update `spawn()` to pass run_id**

In `src/cogos/capabilities/procs.py`, at line 352, change the ProcessHandle construction in `spawn()`:

From:
```python
return ProcessHandle(
    repo=self.repo,
    caller_process_id=self.process_id,
    process=child,
    send_channel=send_ch_model,
    recv_channel=recv_ch_model,
)
```

To:
```python
return ProcessHandle(
    repo=self.repo,
    caller_process_id=self.process_id,
    process=child,
    send_channel=send_ch_model,
    recv_channel=recv_ch_model,
    run_id=self.run_id,
)
```

- [ ] **Step 3: Run existing procs tests**

Run: `pytest tests/cogos/capabilities/test_procs.py -v`
Expected: PASS (run_id is optional with default None, so existing callers are unaffected)

- [ ] **Step 4: Commit**

```bash
git add src/cogos/capabilities/procs.py
git commit -m "thread run_id into ProcessHandle from procs capability"
```

---

### Task 6: Delivery gating in repository

**Files:**
- Modify: `src/cogos/db/repository.py` (around line 2174 in `append_channel_message`)
- Modify: `src/cogos/db/local_repository.py` (around line 1370 in `append_channel_message`)
- Modify: `src/cogos/capabilities/scheduler.py` (around line 118 in `match_messages`)
- Test: `tests/cogos/db/test_delivery_gating.py`

- [ ] **Step 1: Write the failing test first**

Create `tests/cogos/db/test_delivery_gating.py`:

```python
"""Tests for wait-condition delivery gating."""
from uuid import uuid4

import pytest

from cogos.db.local_repository import LocalRepository
from cogos.db.models import (
    Channel, ChannelMessage, ChannelType, Handler, Process, ProcessMode, ProcessStatus, Run, RunStatus,
)
from cogos.db.models.wait_condition import WaitCondition, WaitConditionType, WaitConditionStatus


@pytest.fixture
def repo():
    return LocalRepository()


def _setup_parent_child(repo, *, num_children=1):
    """Create parent + children with spawn channels and handlers."""
    parent = Process(name="parent", mode=ProcessMode.DAEMON, status=ProcessStatus.WAITING)
    repo.upsert_process(parent)
    run = Run(process=parent.id, status=RunStatus.SUSPENDED)
    repo.create_run(run)

    children = []
    for i in range(num_children):
        child = Process(name=f"child-{i}", mode=ProcessMode.ONE_SHOT,
                        status=ProcessStatus.RUNNING, parent_process=parent.id)
        repo.upsert_process(child)

        recv_ch = Channel(
            name=f"spawn:{child.id}\u2192{parent.id}",
            owner_process=child.id,
            channel_type=ChannelType.SPAWN,
        )
        repo.upsert_channel(recv_ch)
        repo.create_handler(Handler(process=parent.id, channel=recv_ch.id))
        children.append((child, recv_ch))

    return parent, run, children


def test_wait_all_blocks_until_all_children_exit(repo):
    parent, run, children = _setup_parent_child(repo, num_children=2)
    child_a, ch_a = children[0]
    child_b, ch_b = children[1]

    wc = WaitCondition(
        run=run.id, type=WaitConditionType.WAIT_ALL,
        pending=[str(child_a.id), str(child_b.id)],
    )
    repo.create_wait_condition(wc)

    # First child exits — parent should NOT be woken
    repo.append_channel_message(ChannelMessage(
        channel=ch_a.id, sender_process=child_a.id,
        payload={"type": "child:exited", "exit_code": 0, "process_id": str(child_a.id)},
    ))
    parent_now = repo.get_process(parent.id)
    assert parent_now.status == ProcessStatus.WAITING

    # Second child exits — parent SHOULD be woken
    repo.append_channel_message(ChannelMessage(
        channel=ch_b.id, sender_process=child_b.id,
        payload={"type": "child:exited", "exit_code": 0, "process_id": str(child_b.id)},
    ))
    parent_now = repo.get_process(parent.id)
    assert parent_now.status == ProcessStatus.RUNNABLE

    # Wait condition should be resolved
    assert repo.get_pending_wait_condition_for_process(parent.id) is None


def test_wait_any_wakes_on_first_child(repo):
    parent, run, children = _setup_parent_child(repo, num_children=2)
    child_a, ch_a = children[0]
    child_b, ch_b = children[1]

    wc = WaitCondition(
        run=run.id, type=WaitConditionType.WAIT_ANY,
        pending=[str(child_a.id), str(child_b.id)],
    )
    repo.create_wait_condition(wc)

    # First child exits — parent should be woken immediately
    repo.append_channel_message(ChannelMessage(
        channel=ch_a.id, sender_process=child_a.id,
        payload={"type": "child:exited", "exit_code": 0, "process_id": str(child_a.id)},
    ))
    parent_now = repo.get_process(parent.id)
    assert parent_now.status == ProcessStatus.RUNNABLE


def test_no_wait_condition_normal_wake(repo):
    """Without a wait condition, messages wake processes normally."""
    parent, run, children = _setup_parent_child(repo, num_children=1)
    child, ch = children[0]

    # No wait condition — should wake parent on any message
    repo.append_channel_message(ChannelMessage(
        channel=ch.id, sender_process=child.id,
        payload={"type": "child:exited", "exit_code": 0, "process_id": str(child.id)},
    ))
    parent_now = repo.get_process(parent.id)
    assert parent_now.status == ProcessStatus.RUNNABLE
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/cogos/db/test_delivery_gating.py::test_wait_all_blocks_until_all_children_exit -v`
Expected: FAIL — parent gets woken after first child because gating isn't implemented yet.

- [ ] **Step 3: Implement gating in local_repository.py**

In `src/cogos/db/local_repository.py`, modify `append_channel_message` (around line 1370). Replace the handler loop:

```python
# Auto-create deliveries for handlers bound to this channel
handlers = self.match_handlers_by_channel(msg.channel)
for handler in handlers:
    delivery = Delivery(message=msg.id, handler=handler.id, trace_id=msg.trace_id)
    _delivery_id, inserted = self.create_delivery(delivery)
    if inserted:
        proc = self.get_process(handler.process)
        if proc and proc.status == ProcessStatus.WAITING:
            # Check wait condition gating
            wc = self.get_pending_wait_condition_for_process(handler.process)
            if wc is None:
                # No wait condition — wake normally
                self.update_process_status(handler.process, ProcessStatus.RUNNABLE)
                self._nudge_ingress(process_id=handler.process)
            else:
                # Gate: update the wait condition
                sender_pid = str(msg.sender_process)
                remaining = self.remove_from_pending(wc.id, sender_pid)
                should_wake = (
                    wc.type.value in ("wait", "wait_any")
                    or (wc.type.value == "wait_all" and len(remaining) == 0)
                )
                if should_wake:
                    self.resolve_wait_condition(wc.id)
                    self.update_process_status(handler.process, ProcessStatus.RUNNABLE)
                    self._nudge_ingress(process_id=handler.process)
```

- [ ] **Step 4: Implement gating in repository.py**

In `src/cogos/db/repository.py`, modify `append_channel_message` (around line 2174). Same gating logic — replace the handler wakeup section:

```python
for handler in handlers:
    delivery = Delivery(message=msg_id, handler=handler.id, trace_id=msg.trace_id)
    _delivery_id, inserted = self.create_delivery(delivery)
    if inserted:
        proc = self.get_process(handler.process)
        if proc and proc.status == ProcessStatus.WAITING:
            wc = self.get_pending_wait_condition_for_process(handler.process)
            if wc is None:
                self.update_process_status(handler.process, ProcessStatus.RUNNABLE)
                self._nudge_ingress(process_id=handler.process)
            else:
                sender_pid = str(msg.sender_process)
                remaining = self.remove_from_pending(wc.id, sender_pid)
                should_wake = (
                    wc.type.value in ("wait", "wait_any")
                    or (wc.type.value == "wait_all" and len(remaining) == 0)
                )
                if should_wake:
                    self.resolve_wait_condition(wc.id)
                    self.update_process_status(handler.process, ProcessStatus.RUNNABLE)
                    self._nudge_ingress(process_id=handler.process)
```

- [ ] **Step 5: Implement gating in scheduler.py match_messages**

In `src/cogos/capabilities/scheduler.py`, in `match_messages()` (around line 118), same pattern:

Replace:
```python
proc = self.repo.get_process(handler.process)
if proc and proc.status == ProcessStatus.WAITING:
    self.repo.update_process_status(handler.process, ProcessStatus.RUNNABLE)
```

With:
```python
proc = self.repo.get_process(handler.process)
if proc and proc.status == ProcessStatus.WAITING:
    wc = self.repo.get_pending_wait_condition_for_process(handler.process)
    if wc is None:
        self.repo.update_process_status(handler.process, ProcessStatus.RUNNABLE)
    else:
        sender_pid = str(msg.sender_process) if hasattr(msg, 'sender_process') else None
        if sender_pid:
            remaining = self.repo.remove_from_pending(wc.id, sender_pid)
            should_wake = (
                wc.type.value in ("wait", "wait_any")
                or (wc.type.value == "wait_all" and len(remaining) == 0)
            )
            if should_wake:
                self.repo.resolve_wait_condition(wc.id)
                self.repo.update_process_status(handler.process, ProcessStatus.RUNNABLE)
```

Note: `match_messages` iterates messages from `list_channel_messages`, which returns `ChannelMessage` objects that have `sender_process`.

- [ ] **Step 6: Run tests**

Run: `pytest tests/cogos/db/test_delivery_gating.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/cogos/db/repository.py src/cogos/db/local_repository.py \
  src/cogos/capabilities/scheduler.py tests/cogos/db/test_delivery_gating.py
git commit -m "add delivery gating for wait conditions"
```

---

### Task 7: Catch WaitSuspend in executor handler and local runtime

**Files:**
- Modify: `src/cogos/executor/handler.py`
- Modify: `src/cogos/runtime/local.py`

- [ ] **Step 1: Add WaitSuspend import to handler.py**

At line 21 in `src/cogos/executor/handler.py`, add:

```python
from cogos.sandbox.executor import SandboxExecutor, VariableTable, WaitSuspend
```

(Replace the existing import on line 21 that only imports `SandboxExecutor, VariableTable`.)

- [ ] **Step 2: Catch WaitSuspend in _execute_python_process**

In `_execute_python_process` (around line 563), after `sandbox.execute(code)`, the `WaitSuspend` will propagate out. Wrap the execute call. Change lines 562-568 from:

```python
sandbox = SandboxExecutor(vt)
result = sandbox.execute(code)

run.result = {"output": result}
run.tokens_in = 0
run.tokens_out = 0
run.scope_log = sandbox.scope_log
```

to:

```python
sandbox = SandboxExecutor(vt)
try:
    result = sandbox.execute(code)
except WaitSuspend:
    run.tokens_in = 0
    run.tokens_out = 0
    run.scope_log = sandbox.scope_log
    raise
run.result = {"output": result}
run.tokens_in = 0
run.tokens_out = 0
run.scope_log = sandbox.scope_log
```

- [ ] **Step 3: Catch WaitSuspend in LLM converse loop tool execution**

At line 865 in `src/cogos/executor/handler.py`, the `sandbox.execute()` call for `run_code` needs to propagate `WaitSuspend`. Change:

```python
elif tool_name == "run_code":
    result = sandbox.execute(tool_input.get("code", ""))
```

to:

```python
elif tool_name == "run_code":
    try:
        result = sandbox.execute(tool_input.get("code", ""))
    except WaitSuspend:
        raise
```

(The `WaitSuspend` will propagate up through the for loop and the while loop, landing in the `except` block of `handler()`.)

- [ ] **Step 4: Catch WaitSuspend in handler() top-level**

In `src/cogos/executor/handler.py`, in the `handler()` function, add a `WaitSuspend` catch between the try block (line 313) and the `except Exception` (line 382). Insert before the `except Exception`:

```python
    except WaitSuspend:
        duration_ms = int((time.time() - start_time) * 1000)
        repo.complete_run(
            run.id,
            status=RunStatus.SUSPENDED,
            tokens_in=run.tokens_in,
            tokens_out=run.tokens_out,
            cost_usd=run.cost_usd or _estimate_cost(run.model_version or "", run.tokens_in, run.tokens_out),
            duration_ms=duration_ms,
            model_version=run.model_version,
            snapshot=run.snapshot,
            scope_log=run.scope_log,
        )
        # Process transitions to WAITING — will be woken when wait condition resolves
        repo.update_process_status(process.id, ProcessStatus.WAITING)
        logger.info("Run %s suspended (wait condition) for process %s", run_id, process.name)
        return {"statusCode": 200, "run_id": str(run_id), "suspended": True}
```

- [ ] **Step 5: Catch WaitSuspend in runtime/local.py**

In `src/cogos/runtime/local.py`, add import at the top (after line 18):

```python
from cogos.sandbox.executor import WaitSuspend
```

In `run_and_complete()`, add a `WaitSuspend` catch between the try success path (line 110) and the `except Exception` (line 112):

```python
    except WaitSuspend:
        duration_ms = int((time.time() - start) * 1000)
        repo.complete_run(
            run.id,
            status=RunStatus.SUSPENDED,
            tokens_in=run.tokens_in,
            tokens_out=run.tokens_out,
            cost_usd=run.cost_usd,
            duration_ms=duration_ms,
            snapshot=run.snapshot,
        )
        repo.update_process_status(process.id, ProcessStatus.WAITING)
        logger.info("Run %s suspended (wait condition) for process %s", run.id, process.name)
```

- [ ] **Step 6: Run existing tests to check nothing breaks**

Run: `pytest tests/cogos/ -v --timeout=30`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/cogos/executor/handler.py src/cogos/runtime/local.py
git commit -m "catch WaitSuspend in executor handler and local runtime"
```

---

### Task 8: Orphan cleanup on process disable

**Files:**
- Modify: `src/cogos/db/repository.py`
- Modify: `src/cogos/db/local_repository.py`

- [ ] **Step 1: Add cleanup to repository.py update_process_status**

In `src/cogos/db/repository.py`, at the end of `update_process_status` (after line 542), add:

```python
if status == ProcessStatus.DISABLED:
    self.resolve_wait_conditions_for_process(process_id)
```

- [ ] **Step 2: Add cleanup to local_repository.py update_process_status**

Same pattern — find `update_process_status` in `local_repository.py` and add:

```python
if status == ProcessStatus.DISABLED:
    self.resolve_wait_conditions_for_process(process_id)
```

- [ ] **Step 3: Run all tests**

Run: `pytest tests/cogos/ -v --timeout=30`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/cogos/db/repository.py src/cogos/db/local_repository.py
git commit -m "cleanup orphaned wait conditions when process is disabled"
```

---

### Task 9: Resume event enrichment with wait_results

**Files:**
- Modify: `src/cogos/executor/handler.py`
- Modify: `src/cogos/runtime/local.py`

- [ ] **Step 1: Add wait_results enrichment helper**

In `src/cogos/executor/handler.py`, add a helper function (near `_notify_parent_on_exit`):

```python
def _enrich_wait_results(repo: Repository, process: Process, event_data: dict) -> None:
    """If this process had a resolved wait condition, inject child exit payloads into event."""
    if not process.parent_process:
        return
    # Look for child:exited messages on spawn channels from all children
    children = repo.list_processes(parent_process=process.id)
    if not children:
        return
    wait_results: dict[str, Any] = {}
    for child in children:
        ch_name = f"spawn:{child.id}\u2192{process.id}"
        ch = repo.get_channel_by_name(ch_name)
        if not ch:
            continue
        msgs = repo.list_channel_messages(ch.id, limit=50)
        for m in msgs:
            if isinstance(m.payload, dict) and m.payload.get("type") == "child:exited":
                wait_results[str(child.id)] = m.payload
                break
    if wait_results:
        event_data["wait_results"] = {"children": wait_results}
```

Actually, this enrichment should happen on the process being *resumed* (the parent), not when the child runs. The parent's process is the one that called `wait()`. The enrichment should happen in the event-building phase before `execute_process` is called.

Better approach: In `handler()`, right before calling `execute_process` (line 315), check if the process has child exit data to inject. Add before the `execute_process` call:

```python
_enrich_wait_results(repo, process, event)
```

And the helper collects from children of THIS process:

```python
def _enrich_wait_results(repo: Repository, process: Process, event: dict) -> None:
    """Inject child exit payloads into event for processes resuming from a wait."""
    # Check if this process just came out of a wait (has resolved wait conditions)
    from cogos.db.models.wait_condition import WaitConditionStatus
    # Quick check: only enrich if there are recent resolved conditions
    children_procs = [p for p in repo.list_processes() if p.parent_process == process.id]
    if not children_procs:
        return
    wait_results: dict[str, Any] = {}
    for child in children_procs:
        ch_name = f"spawn:{child.id}\u2192{process.id}"
        ch = repo.get_channel_by_name(ch_name)
        if not ch:
            continue
        msgs = repo.list_channel_messages(ch.id, limit=50)
        for m in msgs:
            if isinstance(m.payload, dict) and m.payload.get("type") == "child:exited":
                wait_results[str(child.id)] = m.payload
                break
    if wait_results:
        event["wait_results"] = {"children": wait_results}
```

- [ ] **Step 2: Wire enrichment into handler()**

In `src/cogos/executor/handler.py`, at line 315 (before `execute_process` call), add:

```python
_enrich_wait_results(repo, process, event)
```

- [ ] **Step 3: Wire enrichment into local.py**

In `src/cogos/runtime/local.py`, before `execute_fn(process, event_data, run, config, repo)` (line 73), add:

```python
from cogos.executor.handler import _enrich_wait_results
_enrich_wait_results(repo, process, event_data)
```

- [ ] **Step 4: Run all tests**

Run: `pytest tests/cogos/ -v --timeout=30`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/cogos/executor/handler.py src/cogos/runtime/local.py
git commit -m "enrich resume events with wait_results from child exits"
```

---

### Task 10: Integration test — full wait_all lifecycle

**Files:**
- Create: `tests/cogos/test_wait_integration.py`

- [ ] **Step 1: Write integration test**

```python
"""Integration test — full wait_all lifecycle through local executor."""
from uuid import uuid4

import pytest

from cogos.db.local_repository import LocalRepository
from cogos.db.models import (
    Channel, ChannelMessage, ChannelType, Handler, Process, ProcessMode, ProcessStatus,
    Run, RunStatus,
)
from cogos.db.models.wait_condition import WaitCondition, WaitConditionStatus, WaitConditionType


def test_full_wait_all_lifecycle():
    """Parent spawns 2 children, calls wait_all, children exit, parent resumes."""
    repo = LocalRepository()

    # 1. Create parent process
    parent = Process(name="orchestrator", mode=ProcessMode.DAEMON, status=ProcessStatus.RUNNING)
    repo.upsert_process(parent)
    parent_run = Run(process=parent.id, status=RunStatus.RUNNING)
    repo.create_run(parent_run)

    # 2. Create children
    child_a = Process(name="worker-a", mode=ProcessMode.ONE_SHOT,
                      status=ProcessStatus.RUNNING, parent_process=parent.id)
    child_b = Process(name="worker-b", mode=ProcessMode.ONE_SHOT,
                      status=ProcessStatus.RUNNING, parent_process=parent.id)
    repo.upsert_process(child_a)
    repo.upsert_process(child_b)

    # 3. Create spawn channels (child->parent direction)
    ch_a = Channel(name=f"spawn:{child_a.id}\u2192{parent.id}",
                   owner_process=child_a.id, channel_type=ChannelType.SPAWN)
    ch_b = Channel(name=f"spawn:{child_b.id}\u2192{parent.id}",
                   owner_process=child_b.id, channel_type=ChannelType.SPAWN)
    repo.upsert_channel(ch_a)
    repo.upsert_channel(ch_b)

    # 4. Register parent as handler on both spawn channels
    repo.create_handler(Handler(process=parent.id, channel=ch_a.id))
    repo.create_handler(Handler(process=parent.id, channel=ch_b.id))

    # 5. Parent calls wait_all — simulate by creating the wait condition and suspending
    wc = WaitCondition(
        run=parent_run.id,
        type=WaitConditionType.WAIT_ALL,
        pending=[str(child_a.id), str(child_b.id)],
    )
    repo.create_wait_condition(wc)
    repo.complete_run(parent_run.id, status=RunStatus.SUSPENDED)
    repo.update_process_status(parent.id, ProcessStatus.WAITING)

    # 6. Child A exits
    repo.append_channel_message(ChannelMessage(
        channel=ch_a.id, sender_process=child_a.id,
        payload={"type": "child:exited", "exit_code": 0, "process_id": str(child_a.id),
                 "process_name": "worker-a", "duration_ms": 100},
    ))
    # Parent should still be WAITING
    assert repo.get_process(parent.id).status == ProcessStatus.WAITING

    # 7. Child B exits
    repo.append_channel_message(ChannelMessage(
        channel=ch_b.id, sender_process=child_b.id,
        payload={"type": "child:exited", "exit_code": 0, "process_id": str(child_b.id),
                 "process_name": "worker-b", "duration_ms": 200},
    ))
    # Now parent should be RUNNABLE
    assert repo.get_process(parent.id).status == ProcessStatus.RUNNABLE

    # 8. Wait condition should be resolved
    assert repo.get_pending_wait_condition_for_process(parent.id) is None
```

- [ ] **Step 2: Run test**

Run: `pytest tests/cogos/test_wait_integration.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/cogos/test_wait_integration.py
git commit -m "add wait_all integration test"
```
