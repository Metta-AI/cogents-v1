# History Capability Design

Expose run history, file mutation tracking, and cross-process queries through a new `history` capability — enabling supervisor auditing, post-mortem debugging, and recovery.

## What Already Exists

- `cogos_run` table: status, duration_ms, tokens_in/out, cost_usd, result, error, trace_id, parent_trace_id, scope_log, message FK, created_at, completed_at
- `cogos_file_version` table: full write history with versions, but no link to which run created them
- `repo.list_runs(process_id, limit, epoch)` — repo-layer only, not exposed through any capability

## The Gap

1. No link between runs and file mutations (`run_id` missing from `cogos_file_version`)
2. Run data not accessible through any capability API
3. No cross-process query capability
4. No scoped visibility (supervisor vs worker)

## New Capability: `history`

Standalone capability, separate from `procs`. Can be granted independently — read-only audit access without process management permissions.

### API

Two access patterns: per-process handle, and cross-cutting queries.

```python
# Per-process handle
h = history.process("worker-3")
h.runs(limit=10)           # → list[RunSummary]
h.files(run_id="...")       # → list[FileMutation]

# Cross-process queries
history.query(
    status="failed",
    process_name="worker-*",
    since="2026-03-17T00:00",
    limit=50,
)  # → list[RunSummary] (includes process_name, process_id)

# Shorthand
history.failed(since="1h", limit=20)
```

### Scope Schema

```python
{
    "ops": ["query", "process"],       # which operations allowed
    "process_ids": []                  # restrict to specific processes; empty = all
}
```

- Supervisor: full ops, no process_ids restriction
- Worker: `process` op only, `process_ids` = [self]

### Models

```python
class RunSummary(BaseModel):
    id: str
    process_id: str
    process_name: str
    status: str  # running|completed|failed|timeout|suspended|throttled
    duration_ms: int | None
    tokens_in: int
    tokens_out: int
    cost_usd: str
    error: str | None
    result: dict | None
    model_version: str | None
    created_at: str
    completed_at: str | None

class FileMutation(BaseModel):
    key: str
    version: int
    created_at: str
```

## DB Changes

### Migration: add `run_id` to `cogos_file_version`

```sql
ALTER TABLE cogos_file_version
  ADD COLUMN run_id UUID REFERENCES cogos_run(id);

CREATE INDEX idx_file_version_run_id ON cogos_file_version(run_id);
```

No new tables. Queries against existing `cogos_run` and `cogos_file_version`.

### New/Extended Repo Methods

```python
# Extend existing list_runs with more filters
repo.list_runs(
    process_id=None,
    process_ids=None,
    status=None,
    since=None,
    limit=50,
    epoch=None,
) -> list[Run]

# File mutations by run
repo.list_file_mutations(run_id: UUID) -> list[dict]
# → SELECT f.key, fv.version, fv.created_at
#   FROM cogos_file_version fv
#   JOIN cogos_file f ON f.id = fv.file_id
#   WHERE fv.run_id = :run_id

# Glob on process name for cross-process queries
repo.list_runs_by_process_glob(
    name_pattern: str,
    status=None,
    since=None,
    limit=50,
) -> list[Run]
```

### Wiring `run_id` Into File Writes

`FileStore.upsert()` gets an optional `run_id` parameter, threaded from `CogletRuntime`'s current run context.

## Capability Class

```python
class HistoryCapability:
    ALL_OPS = {"query", "process"}

    def process(self, name=None, id=None) -> ProcessHistory:
        self._check("process")
        self._check_process_access(resolved_process_id)
        return ProcessHistory(self.repo, process)

    def query(self, status=None, process_name=None,
              since=None, limit=50) -> list[RunSummary]:
        self._check("query")
        # enforce process_ids scope restriction
        ...

    def failed(self, since=None, limit=20) -> list[RunSummary]:
        return self.query(status="failed", since=since, limit=limit)


class ProcessHistory:
    def runs(self, limit=10) -> list[RunSummary]: ...
    def files(self, run_id) -> list[FileMutation]: ...
```

## Registry Entry

```python
{
    "name": "history",
    "description": "Run history, file mutation tracking, and cross-process audit queries.",
    "handler": "cogos.capabilities.history.HistoryCapability",
    "ALL_OPS": ["query", "process"],
    "scope_schema": {
        "ops": {"type": "array", "items": {"enum": ["query", "process"]}},
        "process_ids": {"type": "array", "items": {"type": "string"}, "description": "Restrict to these process IDs. Empty = all."},
    },
}
```

## Cogware Instructions Include

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
# All failed runs in the last hour
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
```

## Future Extensions (Not Building Now)

- Channel message history (what messages were sent/received per run)
- Immutable audit trail (DB-level enforcement on completed runs)
- Retention/rollup (summarize old runs, keep recent in full)
- Resource usage tracking (memory, CPU — depends on runner reporting)

## What We're NOT Building

- Read tracking (which files a process looked at)
- Real-time streaming/subscriptions
- DB-enforced immutability
- Retention policies
