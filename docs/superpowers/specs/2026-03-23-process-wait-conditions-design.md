# Process Wait Conditions (`wait`, `wait_any`, `wait_all`)

## Problem

CogOS processes can spawn children and receive `child:exited` notifications via spawn channels, but there is no mechanism to suspend a parent until a set of children complete. The existing `ProcessHandle.wait()`, `wait_any()`, and `wait_all()` methods return plain dicts that nothing interprets.

OS-level process synchronization (e.g. `waitpid`, `WaitForMultipleObjects`) lets a parent block until one or all children exit. CogOS needs the same primitive, implemented as suspend-and-resume rather than blocking.

## Design

### New table: `cogos_wait_condition`

```sql
CREATE TABLE IF NOT EXISTS cogos_wait_condition (
    id         TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    run        TEXT NOT NULL REFERENCES cogos_run(id),
    type       TEXT NOT NULL CHECK (type IN ('wait', 'wait_any', 'wait_all')),
    status     TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'resolved')),
    pending    TEXT NOT NULL DEFAULT '[]',
    created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE INDEX idx_wait_condition_run ON cogos_wait_condition(run);
CREATE INDEX idx_wait_condition_status ON cogos_wait_condition(status) WHERE status = 'pending';
```

- `run` FK to `cogos_run` (which has `process` FK). No denormalized `process` column; join through `run` when needed.
- `status`: `pending` while waiting, `resolved` once condition is met.
- `pending`: JSON array of child process UUIDs still awaited. Shrinks as children exit.

### Suspend mechanism: `WaitSuspend`

New exception type in `sandbox/executor.py`:

```python
class WaitSuspend(Exception):
    """Raised by wait()/wait_any()/wait_all() to suspend execution."""
    pass
```

`WaitSuspend` is NOT caught by `SandboxExecutor.execute()` — it propagates out so the handler can intercept it. This is distinct from `_SandboxExit` which is caught and swallowed inside the sandbox. The propagation chain:

- **Python executor path:** `sandbox.execute()` -> `_execute_python_process` catches `WaitSuspend`, returns run with suspended marker
- **LLM converse loop:** `sandbox.execute()` (tool result) -> caught around the tool execution, breaks the converse loop
- **`handle_run` top-level:** catches `WaitSuspend` distinctly from `except Exception`, checkpoints the session, sets process to `WAITING`, marks run as `SUSPENDED`

### Early-exit check: children already exited

Before suspending, `wait()`/`wait_any()`/`wait_all()` check if the awaited children have already posted `child:exited` messages on their spawn channels. If the condition is already satisfied (all children for `wait_all`, any child for `wait_any`), return immediately without suspending. For `wait_all` where some but not all children have exited, only put the still-pending children in the condition's `pending` list.

### ProcessHandle API changes

Methods become side-effecting. `ProcessHandle` gains a `_run_id` field set during capability setup (threaded from `ProcsCapability.run_id`).

```python
def wait(self) -> None:
    """Suspend until child exits. No-op if child already exited."""
    if self._child_already_exited(self._process.id):
        return
    self._repo.create_wait_condition(
        run_id=self._run_id, type="wait",
        pending=[str(self._process.id)],
    )
    raise WaitSuspend()

@staticmethod
def wait_any(handles: list[ProcessHandle]) -> None:
    repo = handles[0]._repo
    run_id = handles[0]._run_id
    if any(h._child_already_exited(h._process.id) for h in handles):
        return
    repo.create_wait_condition(
        run_id=run_id, type="wait_any",
        pending=[h.id for h in handles],
    )
    raise WaitSuspend()

@staticmethod
def wait_all(handles: list[ProcessHandle]) -> None:
    repo = handles[0]._repo
    run_id = handles[0]._run_id
    still_pending = [h.id for h in handles if not h._child_already_exited(h._process.id)]
    if not still_pending:
        return
    repo.create_wait_condition(
        run_id=run_id, type="wait_all",
        pending=still_pending,
    )
    raise WaitSuspend()
```

`_run_id` is sourced from the calling process's capability context, not from individual handles. All handles in a `wait_any`/`wait_all` call must belong to the same calling process (same `_run_id` and `_repo`).

### Handler: catch `WaitSuspend`

In `executor/handler.py`:

1. `_execute_python_process`: catch `WaitSuspend` from `sandbox.execute()`, return run with suspended marker
2. LLM converse loop: catch `WaitSuspend` around `sandbox.execute()` in tool result handling, break the loop
3. `handle_run` top-level: catch `WaitSuspend` distinctly from `except Exception`
   - Checkpoint the session
   - Mark the run as `RunStatus.SUSPENDED` (existing enum value)
   - Transition the process to `WAITING`

### Delivery gating

In **both** `repository.py`'s `append_channel_message` (hot path) and `scheduler.py`'s `match_messages()` (reconciliation backstop), after finding handlers for a channel, before waking the handler's process:

1. Join `cogos_wait_condition` through `cogos_run` to check if the handler's process has a `pending` wait condition
2. If no wait condition: existing behavior (create delivery, wake process)
3. If wait condition exists:
   - Extract the child process ID from the message sender
   - Atomically remove that ID from `pending` (Postgres: jsonb `- :child_id` operator; SQLite: `json_remove` in a transaction)
   - `wait_any` / `wait` (single): mark condition `resolved`, create delivery, wake process
   - `wait_all` with `pending` now empty: mark `resolved`, create delivery, wake process
   - `wait_all` with `pending` still non-empty: create delivery (bookkeeping), do NOT wake process

Same gating logic applies in `local_repository.py`'s `append_channel_message` for local/SQLite path.

### Resume with collected exit data

When the wait condition resolves and the parent resumes via session resume:

1. The event data is enriched with `wait_results` — collected dynamically from `child:exited` messages on spawn channels (`spawn:{child}→{parent}`) for each child in the original wait list
2. Format:
   ```json
   {
       "wait_type": "wait_all",
       "children": {
           "<child-pid>": {"exit_code": 0, "process_name": "worker-1", "duration_ms": 1200, "result": {}},
           "<child-pid>": {"exit_code": 1, "process_name": "worker-2", "error": "...", "result": null}
       }
   }
   ```
3. The parent can also call `handle.recv()` / `handle.runs()` / `handle.status()` on child handles as usual.

### Orphaned wait condition cleanup

When a process transitions to `DISABLED` (killed), resolve any pending wait conditions for that process. This prevents orphaned `pending` rows from accumulating. Added to `update_process_status` in the repository layer.

## Files changed

| File | Change |
|------|--------|
| `db/migrations/021_wait_condition.sql` | New table |
| `db/models/wait_condition.py` | New `WaitCondition` Pydantic model |
| `db/models/__init__.py` | Export |
| `db/repository.py` | `create_wait_condition`, `get_pending_wait_condition_for_process`, `remove_from_pending`, `resolve_wait_condition`; delivery gating in `append_channel_message`; orphan cleanup in `update_process_status` |
| `db/local_repository.py` | Same repo methods and delivery gating for local/SQLite path |
| `sandbox/executor.py` | `WaitSuspend` exception (not caught by sandbox — propagates to handler) |
| `capabilities/process_handle.py` | Side-effecting `wait()`/`wait_any()`/`wait_all()` with early-exit check; `_run_id` field |
| `capabilities/procs.py` | Pass `run_id` to `ProcessHandle` |
| `executor/handler.py` | Catch `WaitSuspend` in Python path, LLM converse loop, and top-level; use `RunStatus.SUSPENDED`; enrich resume event with `wait_results` |
| `capabilities/scheduler.py` | Delivery gating in `match_messages()` |
| `runtime/local.py` | Catch `WaitSuspend` in local runtime run loop |
| `tests/` | Wait condition lifecycle, delivery gating, early-exit, suspend/resume, orphan cleanup |
